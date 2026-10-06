"""
集团合并申报领域逻辑：

- 集团与成员（带生效区间）
- 成员封账申报（不可变快照）
- 集团内部车型转让登记
- 集团合并版本与抵销项目（抵销项目只属于生成它的版本）
- 版本差异（迟交/退出/更正）与监管结论冻结
- 集团层级与成员层级余额、缺口、合规状态的勾稽校验

设计原则：
1. 成员封账后数据不可变；更正只产生新封账版本，旧版本保留。
2. 每次合并生成全新版本，旧版本（含已被采用的监管结论）不被改写。
3. 抵销只冲减合并口径，双方原始记录始终保留在封账快照中。
4. 外部交易与跨年度结转永不抵销。
"""
import json
from datetime import datetime, date
from typing import List, Optional, Dict, Tuple

from sqlalchemy.orm import Session

from . import crud, models, schemas
from .models import (
    CreditRecordStatus,
    MembershipStatus,
    MemberFilingStatus,
    GroupFilingVersionStatus,
    MEMBER_CHANGE_INITIAL,
    MEMBER_CHANGE_ADDED,
    MEMBER_CHANGE_REMOVED,
    MEMBER_CHANGE_UNCHANGED,
    MEMBER_CHANGE_CORRECTED,
    ENTRY_CREDIT_TRANSFER,
    ENTRY_MODEL_TRANSFER,
)

EPS = 0.01


def _round2(v: float) -> float:
    return round(float(v or 0.0), 2)


# ============================ 集团与成员 ============================

def create_group(db: Session, group: schemas.EnterpriseGroupCreate) -> models.EnterpriseGroup:
    existing = db.query(models.EnterpriseGroup).filter(
        models.EnterpriseGroup.name == group.name
    ).first()
    if existing:
        raise ValueError("集团名称已存在")
    db_group = models.EnterpriseGroup(**group.model_dump())
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group


def get_group(db: Session, group_id: int) -> Optional[models.EnterpriseGroup]:
    return db.query(models.EnterpriseGroup).filter(
        models.EnterpriseGroup.id == group_id
    ).first()


def list_groups(db: Session, skip: int = 0, limit: int = 100) -> List[models.EnterpriseGroup]:
    return db.query(models.EnterpriseGroup).offset(skip).limit(limit).all()


def update_group(
    db: Session, group_id: int, group_update: schemas.EnterpriseGroupUpdate
) -> Optional[models.EnterpriseGroup]:
    db_group = get_group(db, group_id)
    if not db_group:
        return None
    for key, value in group_update.model_dump(exclude_unset=True).items():
        setattr(db_group, key, value)
    db_group.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_group)
    return db_group


def add_membership(
    db: Session, group_id: int, req: schemas.GroupMembershipCreate
) -> models.GroupMembership:
    group = get_group(db, group_id)
    if not group:
        raise ValueError("集团不存在")
    enterprise = crud.get_enterprise(db, req.enterprise_id)
    if not enterprise:
        raise ValueError("成员企业不存在")
    if req.effective_to is not None and req.effective_to <= req.effective_from:
        raise ValueError("退出日期必须晚于生效日期")

    existing = db.query(models.GroupMembership).filter(
        models.GroupMembership.group_id == group_id,
        models.GroupMembership.enterprise_id == req.enterprise_id,
    ).first()
    if existing:
        raise ValueError("该企业已经是集团成员，如需调整请办理退出或变更生效区间")

    membership = models.GroupMembership(
        group_id=group_id,
        enterprise_id=req.enterprise_id,
        effective_from=req.effective_from,
        effective_to=req.effective_to,
        status=MembershipStatus.EXITED if req.effective_to else MembershipStatus.ACTIVE,
        remark=req.remark,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


def exit_membership(
    db: Session, group_id: int, enterprise_id: int, req: schemas.GroupMembershipExit
) -> models.GroupMembership:
    membership = db.query(models.GroupMembership).filter(
        models.GroupMembership.group_id == group_id,
        models.GroupMembership.enterprise_id == enterprise_id,
    ).first()
    if not membership:
        raise ValueError("成员关系不存在")
    if membership.status == MembershipStatus.EXITED:
        raise ValueError("该成员已退出集团")
    if req.effective_to <= membership.effective_from:
        raise ValueError("退出日期必须晚于生效日期")
    membership.effective_to = req.effective_to
    membership.status = MembershipStatus.EXITED
    if req.remark:
        membership.remark = req.remark
    membership.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(membership)
    return membership


def list_memberships(
    db: Session,
    group_id: int,
    on_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[Dict]:
    """返回成员关系；on_date 给定时仅返回当日处于生效区间内的成员。"""
    query = db.query(models.GroupMembership).filter(
        models.GroupMembership.group_id == group_id
    )
    rows = query.order_by(models.GroupMembership.effective_from.asc()).offset(skip).limit(limit).all()
    result = []
    for m in rows:
        if on_date is not None:
            if m.effective_from > on_date:
                continue
            if m.effective_to is not None and m.effective_to <= on_date:
                continue
        enterprise = crud.get_enterprise(db, m.enterprise_id)
        result.append({
            "id": m.id,
            "group_id": m.group_id,
            "enterprise_id": m.enterprise_id,
            "enterprise_name": enterprise.name if enterprise else "",
            "effective_from": m.effective_from,
            "effective_to": m.effective_to,
            "status": m.status,
            "remark": m.remark,
            "created_at": m.created_at,
            "updated_at": m.updated_at,
        })
    return result


def _membership_covers_year(membership: models.GroupMembership, year: int) -> bool:
    """成员生效区间是否与申报年度有交集（effective_to 为不含边界）。"""
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    if membership.effective_from > year_end:
        return False
    if membership.effective_to is not None and membership.effective_to <= year_start:
        return False
    return True


# ============================ 成员封账 ============================

def _generate_member_filing_no(db: Session, enterprise_id: int, year: int, version_no: int) -> str:
    return f"MF{year}{enterprise_id:04d}V{version_no:02d}"


def get_member_filing(db: Session, filing_id: int) -> Optional[models.MemberFiling]:
    return db.query(models.MemberFiling).filter(models.MemberFiling.id == filing_id).first()


def get_latest_sealed_filing(
    db: Session, enterprise_id: int, year: int
) -> Optional[models.MemberFiling]:
    return db.query(models.MemberFiling).filter(
        models.MemberFiling.enterprise_id == enterprise_id,
        models.MemberFiling.year == year,
        models.MemberFiling.status == MemberFilingStatus.SEALED,
    ).order_by(models.MemberFiling.version_no.desc()).first()


def list_member_filings(
    db: Session, enterprise_id: Optional[int] = None, year: Optional[int] = None
) -> List[models.MemberFiling]:
    query = db.query(models.MemberFiling)
    if enterprise_id:
        query = query.filter(models.MemberFiling.enterprise_id == enterprise_id)
    if year:
        query = query.filter(models.MemberFiling.year == year)
    return query.order_by(
        models.MemberFiling.year.desc(),
        models.MemberFiling.enterprise_id.asc(),
        models.MemberFiling.version_no.desc(),
    ).all()


def seal_member_filing(
    db: Session, enterprise_id: int, year: int, remark: Optional[str] = None
) -> models.MemberFiling:
    """
    成员封账：对当年已确认积分记录、年度交易、跨年度结转做不可变快照。
    已封账后如数据发生更正，应再次封账形成新版本；旧版本标记 superseded 但永不删除/改写。
    """
    enterprise = crud.get_enterprise(db, enterprise_id)
    if not enterprise:
        raise ValueError("企业不存在")

    records = db.query(models.CreditRecord).join(models.VehicleModel).filter(
        models.VehicleModel.enterprise_id == enterprise_id,
        models.CreditRecord.year == year,
        models.CreditRecord.status == CreditRecordStatus.CONFIRMED,
    ).all()
    if not records:
        raise ValueError("该企业当年没有已确认的积分记录，无法封账；请先完成核算与确认")

    # 重新计算年度汇总，确保封账快照反映最新交易与结转（成员原始记录仍保留）。
    summary = crud.update_annual_summary_with_transactions(db, enterprise_id, year)

    transactions = crud.get_credit_transactions(db, enterprise_id=enterprise_id, limit=10000)
    txn_snapshot = []
    for t in transactions:
        txn_year = t.transaction_date.year if t.transaction_date else year
        if txn_year != year:
            continue
        txn_snapshot.append({
            "id": t.id,
            "transaction_no": t.transaction_no,
            "from_enterprise_id": t.from_enterprise_id,
            "to_enterprise_id": t.to_enterprise_id,
            "credit_amount": _round2(t.credit_amount),
            "unit_price": t.unit_price,
            "total_amount": t.total_amount,
            "transaction_date": t.transaction_date.isoformat() if t.transaction_date else None,
            "status": t.status,
        })

    carryovers = db.query(models.CreditCarryover).filter(
        models.CreditCarryover.enterprise_id == enterprise_id,
        ((models.CreditCarryover.to_year == year) | (models.CreditCarryover.from_year == year)),
    ).all()
    carryover_snapshot = []
    for c in carryovers:
        carryover_snapshot.append({
            "id": c.id,
            "carryover_no": c.carryover_no,
            "from_year": c.from_year,
            "to_year": c.to_year,
            "original_amount": _round2(c.original_amount),
            "carryover_ratio": c.carryover_ratio,
            "carryover_amount": _round2(c.carryover_amount),
            "used_amount": _round2(c.used_amount),
            "remaining_amount": _round2(c.remaining_amount),
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
        })

    record_snapshot = []
    for r in records:
        vm = r.vehicle_model
        record_snapshot.append({
            "id": r.id,
            "vehicle_model_id": r.vehicle_model_id,
            "model_name": vm.model_name if vm else "",
            "model_code": vm.model_code if vm else "",
            "year": r.year,
            "unit_credit": r.unit_credit,
            "total_credit": _round2(r.total_credit),
            "annual_output": r.annual_output,
            "status": r.status.value,
            "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
        })

    prior = get_latest_sealed_filing(db, enterprise_id, year)
    version_no = (prior.version_no + 1) if prior else 1

    filing = models.MemberFiling(
        filing_no=_generate_member_filing_no(db, enterprise_id, year, version_no),
        enterprise_id=enterprise_id,
        year=year,
        version_no=version_no,
        status=MemberFilingStatus.SEALED,
        total_positive_credit=summary.total_positive_credit,
        total_negative_credit=summary.total_negative_credit,
        net_credit=summary.net_credit,
        carryover_in=summary.carryover_in,
        carryover_out=summary.carryover_out,
        bought_credit=summary.bought_credit,
        sold_credit=summary.sold_credit,
        final_net_credit=summary.final_net_credit,
        credit_gap=summary.credit_gap,
        credit_surplus=summary.credit_surplus,
        is_compliant=summary.is_compliant,
        record_snapshot=json.dumps(record_snapshot, ensure_ascii=False),
        transaction_snapshot=json.dumps(txn_snapshot, ensure_ascii=False),
        carryover_snapshot=json.dumps(carryover_snapshot, ensure_ascii=False),
        sealed_at=datetime.utcnow(),
        remark=remark,
    )
    db.add(filing)
    db.flush()

    if prior:
        prior.status = MemberFilingStatus.SUPERSEDED
        prior.superseded_by_filing_id = filing.id

    db.commit()
    db.refresh(filing)
    return filing


# ============================ 集团内部车型转让登记 ============================

def register_internal_model_transfer(
    db: Session, req: schemas.InternalModelTransferCreate
) -> models.InternalModelTransfer:
    if req.seller_enterprise_id == req.buyer_enterprise_id:
        raise ValueError("车型转让双方不能是同一企业")
    seller = crud.get_enterprise(db, req.seller_enterprise_id)
    buyer = crud.get_enterprise(db, req.buyer_enterprise_id)
    if not seller or not buyer:
        raise ValueError("转让双方企业必须存在")

    def _check_record(rid: Optional[int], enterprise_id: int, side: str):
        if rid is None:
            return
        record = db.query(models.CreditRecord).join(models.VehicleModel).filter(
            models.CreditRecord.id == rid,
            models.VehicleModel.enterprise_id == enterprise_id,
        ).first()
        if not record:
            raise ValueError(f"{side}原始积分记录不存在或不属于该企业")
        if record.year != req.year:
            raise ValueError(f"{side}原始积分记录年度与转让年度不一致")

    _check_record(req.seller_record_id, req.seller_enterprise_id, "让出方")
    _check_record(req.buyer_record_id, req.buyer_enterprise_id, "受让方")

    now = datetime.now().strftime("%Y%m%d%H%M%S")
    count = db.query(models.InternalModelTransfer).count() + 1
    transfer = models.InternalModelTransfer(
        transfer_no=f"IMT{now}{count:04d}",
        year=req.year,
        seller_enterprise_id=req.seller_enterprise_id,
        buyer_enterprise_id=req.buyer_enterprise_id,
        model_name=req.model_name,
        seller_record_id=req.seller_record_id,
        buyer_record_id=req.buyer_record_id,
        duplicated_credit=_round2(req.duplicated_credit),
        remark=req.remark,
    )
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer


def list_internal_model_transfers(
    db: Session, year: Optional[int] = None, group_scope_enterprise_ids: Optional[set] = None
) -> List[models.InternalModelTransfer]:
    query = db.query(models.InternalModelTransfer)
    if year is not None:
        query = query.filter(models.InternalModelTransfer.year == year)
    rows = query.order_by(models.InternalModelTransfer.id.asc()).all()
    if group_scope_enterprise_ids is not None:
        rows = [
            r for r in rows
            if r.seller_enterprise_id in group_scope_enterprise_ids
            and r.buyer_enterprise_id in group_scope_enterprise_ids
        ]
    return rows


# ============================ 集团合并版本 ============================

def _get_or_create_group_filing(
    db: Session, group_id: int, year: int
) -> models.GroupFiling:
    filing = db.query(models.GroupFiling).filter(
        models.GroupFiling.group_id == group_id,
        models.GroupFiling.year == year,
    ).first()
    if filing:
        return filing
    filing = models.GroupFiling(
        filing_no="PENDING",
        group_id=group_id,
        year=year,
        remark=f"{year}年度集团合并申报",
    )
    db.add(filing)
    db.flush()
    filing.filing_no = f"GF{year}{group_id:04d}{filing.id:04d}"
    db.flush()
    return filing


def _load_filing_snapshots(filing: models.MemberFiling) -> Tuple[List[dict], List[dict], List[dict], set, set]:
    records = json.loads(filing.record_snapshot or "[]")
    txns = json.loads(filing.transaction_snapshot or "[]")
    carryovers = json.loads(filing.carryover_snapshot or "[]")
    record_ids = {r["id"] for r in records}
    txn_ids = {t["id"] for t in txns}
    return records, txns, carryovers, record_ids, txn_ids


def _resolve_member_filing(
    db: Session,
    enterprise_id: int,
    year: int,
    explicit_filing_id: Optional[int],
) -> models.MemberFiling:
    if explicit_filing_id is not None:
        filing = get_member_filing(db, explicit_filing_id)
        if not filing:
            raise ValueError(f"企业{enterprise_id}指定的封账版本不存在")
        if filing.enterprise_id != enterprise_id:
            raise ValueError("封账版本与成员企业不匹配")
        if filing.year != year:
            raise ValueError("封账版本年度与集团申报年度不一致")
        return filing
    filing = get_latest_sealed_filing(db, enterprise_id, year)
    if not filing:
        raise ValueError(f"成员企业{enterprise_id}尚未提交{year}年度封账版本，不能纳入合并")
    return filing


def create_group_consolidation_version(
    db: Session, req: schemas.GroupConsolidationCreateRequest
) -> models.GroupFilingVersion:
    group = get_group(db, req.group_id)
    if not group:
        raise ValueError("集团不存在")
    if not req.members:
        raise ValueError("合并范围不能为空")

    enterprise_ids = [m.enterprise_id for m in req.members]
    if len(set(enterprise_ids)) != len(enterprise_ids):
        raise ValueError("同一成员在合并范围中出现了多次")

    # 1) 校验成员生效区间覆盖申报年度，并解析各自封账版本
    resolved: Dict[int, models.MemberFiling] = {}
    for item in req.members:
        membership = db.query(models.GroupMembership).filter(
            models.GroupMembership.group_id == req.group_id,
            models.GroupMembership.enterprise_id == item.enterprise_id,
        ).first()
        if not membership:
            raise ValueError(f"企业{item.enterprise_id}不是集团成员")
        if not _membership_covers_year(membership, req.year):
            raise ValueError(
                f"企业{item.enterprise_id}的成员生效区间不覆盖{req.year}年度，不能纳入该年度合并"
            )
        resolved[item.enterprise_id] = _resolve_member_filing(
            db, item.enterprise_id, req.year, item.member_filing_id
        )

    group_filing = _get_or_create_group_filing(db, req.group_id, req.year)

    prior_version = db.query(models.GroupFilingVersion).filter(
        models.GroupFilingVersion.group_filing_id == group_filing.id
    ).order_by(models.GroupFilingVersion.version_no.desc()).first()

    prior_selection: Dict[int, models.GroupVersionMember] = {}
    if prior_version:
        for svm in prior_version.member_selections:
            if svm.included:
                prior_selection[svm.enterprise_id] = svm

    # 2) 成员范围差异分类
    member_changes: Dict[int, str] = {}
    prior_filing_map: Dict[int, int] = {}
    for ent_id, filing in resolved.items():
        if not prior_version:
            member_changes[ent_id] = MEMBER_CHANGE_INITIAL
        elif ent_id not in prior_selection:
            member_changes[ent_id] = MEMBER_CHANGE_ADDED
        elif prior_selection[ent_id].member_filing_id != filing.id:
            member_changes[ent_id] = MEMBER_CHANGE_CORRECTED
            prior_filing_map[ent_id] = prior_selection[ent_id].member_filing_id
        else:
            member_changes[ent_id] = MEMBER_CHANGE_UNCHANGED

    removed_ent_ids = [e for e in prior_selection if e not in resolved]

    # 3) 成员封账口径合计（抵销前）
    agg_positive = sum(f.total_positive_credit for f in resolved.values())
    agg_negative = sum(f.total_negative_credit for f in resolved.values())
    agg_net = sum(f.net_credit for f in resolved.values())
    agg_gap = sum(f.credit_gap for f in resolved.values())
    agg_surplus = sum(f.credit_surplus for f in resolved.values())
    agg_carry_in = sum(f.carryover_in for f in resolved.values())
    agg_carry_out = sum(f.carryover_out for f in resolved.values())
    agg_bought = sum(f.bought_credit for f in resolved.values())
    agg_sold = sum(f.sold_credit for f in resolved.values())

    scope_ids = set(resolved.keys())

    # 快照索引：以封账数据为唯一准据
    snapshot_data: Dict[int, Tuple] = {
        ent_id: _load_filing_snapshots(filing) for ent_id, filing in resolved.items()
    }

    # 4) 内部积分转让抵销：双方都在范围内，且交易同时出现在双方封账快照中
    #    （用卖方快照去重，买方快照校验“双方数据里都有”）
    eliminations_in: List[dict] = []
    seen_txn_ids = set()
    skip_notes: List[str] = []
    for seller_id, seller_filing in resolved.items():
        _, seller_txns, _, _, seller_txn_ids = snapshot_data[seller_id]
        for t in seller_txns:
            buyer_id = t["to_enterprise_id"]
            if t["from_enterprise_id"] != seller_id:
                continue
            if buyer_id not in scope_ids:
                continue  # 外部交易，不得抵销
            if t["id"] in seen_txn_ids:
                continue
            txn_year = None
            if t.get("transaction_date"):
                txn_year = datetime.fromisoformat(t["transaction_date"]).year
            if txn_year != req.year:
                continue  # 跨年度数据不得在本年度抵销
            buyer_txn_ids = snapshot_data[buyer_id][4]
            if t["id"] not in buyer_txn_ids:
                skip_notes.append(
                    f"内部交易{t['transaction_no']}未同时出现在受让方封账版本中，本版暂不抵销"
                )
                continue
            seen_txn_ids.add(t["id"])
            eliminations_in.append({
                "entry_type": ENTRY_CREDIT_TRANSFER,
                "seller_enterprise_id": seller_id,
                "buyer_enterprise_id": buyer_id,
                "source_transaction_id": t["id"],
                "seller_record_id": None,
                "buyer_record_id": None,
                "gross_amount": _round2(t["credit_amount"]),
                "elimination_amount": _round2(t["credit_amount"]),
                "remark": f"内部积分转让抵销（交易单号 {t['transaction_no']}），双方原始记录保留",
            })

    # 5) 内部车型转让抵销：双方均纳入、且引用的原始记录都在各自封账快照中
    model_transfers = list_internal_model_transfers(
        db, year=req.year, group_scope_enterprise_ids=scope_ids
    )
    for tr in model_transfers:
        seller_records = snapshot_data[tr.seller_enterprise_id][3]
        buyer_records = snapshot_data[tr.buyer_enterprise_id][3]
        if tr.seller_record_id is not None and tr.seller_record_id not in seller_records:
            skip_notes.append(f"车型转让{tr.transfer_no}的让出方记录未封账，本版暂不抵销")
            continue
        if tr.buyer_record_id is not None and tr.buyer_record_id not in buyer_records:
            skip_notes.append(f"车型转让{tr.transfer_no}的受让方记录未封账，本版暂不抵销")
            continue
        eliminations_in.append({
            "entry_type": ENTRY_MODEL_TRANSFER,
            "seller_enterprise_id": tr.seller_enterprise_id,
            "buyer_enterprise_id": tr.buyer_enterprise_id,
            "source_transaction_id": None,
            "seller_record_id": tr.seller_record_id,
            "buyer_record_id": tr.buyer_record_id,
            "gross_amount": _round2(tr.duplicated_credit),
            "elimination_amount": _round2(tr.duplicated_credit),
            "remark": f"内部车型“{tr.model_name}”转让重复申报抵销（登记单号 {tr.transfer_no}），双方原始记录保留",
        })

    credit_transfer_elim = sum(
        e["elimination_amount"] for e in eliminations_in
        if e["entry_type"] == ENTRY_CREDIT_TRANSFER
    )
    model_transfer_elim = sum(
        e["elimination_amount"] for e in eliminations_in
        if e["entry_type"] == ENTRY_MODEL_TRANSFER
    )
    elimination_total = credit_transfer_elim + model_transfer_elim
    internal_gross = sum(e["gross_amount"] for e in eliminations_in)

    # 6) 合并口径：
    #    - 车型转让重复申报 → 冲减生产口径正积分/净积分；
    #    - 积分转让为零和内部流，只冲减买卖总额，不影响净积分；
    #    - 外部交易、跨年度结转不抵销。
    consolidated_positive = agg_positive - model_transfer_elim
    consolidated_negative = agg_negative
    consolidated_net = agg_net - model_transfer_elim

    # 对外买卖 = 成员买卖总额 - 内部抵销额（内部买卖双向各计一次）
    external_bought = agg_bought - credit_transfer_elim
    external_sold = agg_sold - credit_transfer_elim
    consolidated_carry_in = agg_carry_in
    consolidated_carry_out = agg_carry_out

    consolidated_final_net = (
        consolidated_net
        + consolidated_carry_in
        + external_bought
        - external_sold
        - consolidated_carry_out
    )
    if consolidated_final_net >= 0:
        consolidated_gap = 0.0
        consolidated_surplus = _round2(consolidated_final_net)
        is_compliant = True
    else:
        consolidated_gap = _round2(abs(consolidated_final_net))
        consolidated_surplus = 0.0
        is_compliant = False

    # 7) 与前版的成员/金额差异
    member_diff = _build_member_diff(
        db, resolved, member_changes, prior_filing_map, removed_ent_ids, prior_version
    )
    amount_diff = _build_amount_diff(
        prior_version,
        agg_positive, agg_negative, agg_net, agg_gap, agg_surplus,
        agg_carry_in, agg_carry_out, agg_bought, agg_sold,
        elimination_total, internal_gross,
        consolidated_positive, consolidated_negative, consolidated_net,
        consolidated_carry_in, consolidated_carry_out,
        external_bought, external_sold,
        consolidated_final_net, consolidated_gap, consolidated_surplus, is_compliant,
    )

    version_no = (prior_version.version_no + 1) if prior_version else 1
    status = (
        GroupFilingVersionStatus.LOCKED if req.lock_after_create
        else GroupFilingVersionStatus.SUBMITTED
    )
    conclusion = {
        "group_filing_no": group_filing.filing_no,
        "year": req.year,
        "version_no": version_no,
        "generated_at": datetime.utcnow().isoformat(),
        "member_count": len(resolved),
        "consolidated_net": _round2(consolidated_net),
        "consolidated_final_net": _round2(consolidated_final_net),
        "consolidated_gap": _round2(consolidated_gap),
        "consolidated_surplus": _round2(consolidated_surplus),
        "elimination_total": _round2(elimination_total),
        "is_compliant": is_compliant,
        "frozen": bool(req.lock_after_create),
        "note": "监管结论随版本留存；版本一经采用即冻结，更正须另出合并版本，不得改写本结论。",
    }

    version = models.GroupFilingVersion(
        group_filing_id=group_filing.id,
        version_no=version_no,
        status=status,
        change_reason=req.change_reason,
        member_count=len(resolved),
        members_aggregate_positive=_round2(agg_positive),
        members_aggregate_negative=_round2(agg_negative),
        members_aggregate_net=_round2(agg_net),
        members_aggregate_gap=_round2(agg_gap),
        members_aggregate_surplus=_round2(agg_surplus),
        members_carryover_in=_round2(agg_carry_in),
        members_carryover_out=_round2(agg_carry_out),
        members_bought=_round2(agg_bought),
        members_sold=_round2(agg_sold),
        internal_gross=_round2(internal_gross),
        elimination_total=_round2(elimination_total),
        consolidated_positive=_round2(consolidated_positive),
        consolidated_negative=_round2(consolidated_negative),
        consolidated_net=_round2(consolidated_net),
        consolidated_carryover_in=_round2(consolidated_carry_in),
        consolidated_carryover_out=_round2(consolidated_carry_out),
        external_bought=_round2(external_bought),
        external_sold=_round2(external_sold),
        consolidated_final_net=_round2(consolidated_final_net),
        consolidated_gap=_round2(consolidated_gap),
        consolidated_surplus=_round2(consolidated_surplus),
        is_compliant=is_compliant,
        member_diff_json=json.dumps(member_diff, ensure_ascii=False),
        amount_diff_json=json.dumps(amount_diff, ensure_ascii=False),
        regulatory_conclusion=json.dumps(conclusion, ensure_ascii=False),
    )
    db.add(version)
    db.flush()

    # 成员选择（含本版排除的退出成员，included=False 留痕）
    for ent_id, filing in resolved.items():
        db.add(models.GroupVersionMember(
            version_id=version.id,
            enterprise_id=ent_id,
            member_filing_id=filing.id,
            change_type=member_changes[ent_id],
            prior_filing_id=prior_filing_map.get(ent_id),
            included=True,
        ))
    for ent_id in removed_ent_ids:
        prior = prior_selection[ent_id]
        db.add(models.GroupVersionMember(
            version_id=version.id,
            enterprise_id=ent_id,
            member_filing_id=prior.member_filing_id,
            change_type=MEMBER_CHANGE_REMOVED,
            prior_filing_id=prior.member_filing_id,
            included=False,
        ))

    for idx, e in enumerate(eliminations_in, start=1):
        db.add(models.ConsolidationElimination(
            version_id=version.id,
            elimination_no=f"EL{version.id:06d}-{idx:03d}",
            entry_type=e["entry_type"],
            year=req.year,
            seller_enterprise_id=e["seller_enterprise_id"],
            buyer_enterprise_id=e["buyer_enterprise_id"],
            source_transaction_id=e["source_transaction_id"],
            seller_record_id=e["seller_record_id"],
            buyer_record_id=e["buyer_record_id"],
            gross_amount=e["gross_amount"],
            elimination_amount=e["elimination_amount"],
            remark=e["remark"],
        ))

    # 已被取代的“已提交（未冻结）”版本标记为 amended；LOCKED 版本保持冻结、绝不改写。
    if prior_version and prior_version.status == GroupFilingVersionStatus.SUBMITTED:
        prior_version.status = GroupFilingVersionStatus.AMENDED

    group_filing.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(version)
    return version


def _build_member_diff(
    db: Session,
    resolved: Dict[int, models.MemberFiling],
    member_changes: Dict[int, str],
    prior_filing_map: Dict[int, int],
    removed_ent_ids: List[int],
    prior_version: Optional[models.GroupFilingVersion],
) -> dict:
    def ent_name(eid: int) -> str:
        e = crud.get_enterprise(db, eid)
        return e.name if e else str(eid)

    diff = {
        "prior_version_no": prior_version.version_no if prior_version else None,
        "added": [],
        "removed": [],
        "corrected": [],
        "unchanged": [],
        "initial": [],
    }
    for ent_id, change in member_changes.items():
        entry = {
            "enterprise_id": ent_id,
            "enterprise_name": ent_name(ent_id),
            "member_filing_id": resolved[ent_id].id,
            "member_filing_version_no": resolved[ent_id].version_no,
        }
        if change == MEMBER_CHANGE_CORRECTED:
            entry["prior_member_filing_id"] = prior_filing_map.get(ent_id)
            prior_filing = get_member_filing(db, prior_filing_map[ent_id])
            entry["net_credit_delta"] = _round2(
                resolved[ent_id].net_credit - (prior_filing.net_credit if prior_filing else 0.0)
            )
            entry["final_net_credit_delta"] = _round2(
                resolved[ent_id].final_net_credit
                - (prior_filing.final_net_credit if prior_filing else 0.0)
            )
        if change in diff:
            diff[change].append(entry)
    for ent_id in removed_ent_ids:
        prior = prior_version and next(
            (m for m in prior_version.member_selections if m.enterprise_id == ent_id), None
        )
        diff["removed"].append({
            "enterprise_id": ent_id,
            "enterprise_name": ent_name(ent_id),
            "member_filing_id": prior.member_filing_id if prior else None,
            "reason": "成员退出集团或本版未纳入合并范围",
        })
    diff["member_count_prior"] = len(prior_selection_ids(prior_version))
    diff["member_count_current"] = len(resolved)
    diff["member_count_delta"] = len(resolved) - diff["member_count_prior"]
    return diff


def prior_selection_ids(prior_version: Optional[models.GroupFilingVersion]) -> List[int]:
    if not prior_version:
        return []
    return [m.enterprise_id for m in prior_version.member_selections if m.included]


def _build_amount_diff(prior_version: Optional[models.GroupFilingVersion], *current_values) -> dict:
    names = [
        "members_aggregate_positive", "members_aggregate_negative", "members_aggregate_net",
        "members_aggregate_gap", "members_aggregate_surplus",
        "members_carryover_in", "members_carryover_out", "members_bought", "members_sold",
        "elimination_total", "internal_gross",
        "consolidated_positive", "consolidated_negative", "consolidated_net",
        "consolidated_carryover_in", "consolidated_carryover_out",
        "external_bought", "external_sold",
        "consolidated_final_net", "consolidated_gap", "consolidated_surplus",
    ]
    if not prior_version:
        return {"prior_version_no": None, "deltas": None,
                "note": "首版合并，无前版金额差异"}
    prior_values = [
        prior_version.members_aggregate_positive, prior_version.members_aggregate_negative,
        prior_version.members_aggregate_net, prior_version.members_aggregate_gap,
        prior_version.members_aggregate_surplus,
        prior_version.members_carryover_in, prior_version.members_carryover_out,
        prior_version.members_bought, prior_version.members_sold,
        prior_version.elimination_total, prior_version.internal_gross,
        prior_version.consolidated_positive, prior_version.consolidated_negative,
        prior_version.consolidated_net,
        prior_version.consolidated_carryover_in, prior_version.consolidated_carryover_out,
        prior_version.external_bought, prior_version.external_sold,
        prior_version.consolidated_final_net, prior_version.consolidated_gap,
        prior_version.consolidated_surplus,
    ]
    deltas = {}
    for name, old, new in zip(names, prior_values, current_values[:len(names)]):
        old = _round2(old or 0.0)
        new = _round2(new or 0.0)
        if abs(new - old) > EPS:
            deltas[name] = {"prior": old, "current": new, "delta": _round2(new - old)}
    return {
        "prior_version_no": prior_version.version_no,
        "prior_status": prior_version.status.value,
        "changed_items": deltas,
        "compliance_changed": current_values[-1] != (prior_version.is_compliant if prior_version else True),
        "note": "差异按版本口径列示；前版已采用的监管结论保持不变，本版另存新结论。",
    }


def lock_group_version(db: Session, version_id: int) -> models.GroupFilingVersion:
    """采用并冻结版本：冻结后监管结论不可改写；更正只能另出新版本。"""
    version = get_group_version(db, version_id)
    if not version:
        raise ValueError("合并版本不存在")
    if version.status == GroupFilingVersionStatus.LOCKED:
        raise ValueError("该版本已被采用并冻结，不能重复冻结或修改")
    if version.status == GroupFilingVersionStatus.AMENDED:
        raise ValueError("该版本已被后续版本替代，不能再冻结，请冻结最新版本")
    version.status = GroupFilingVersionStatus.LOCKED
    conclusion = json.loads(version.regulatory_conclusion or "{}")
    conclusion["frozen"] = True
    conclusion["locked_at"] = datetime.utcnow().isoformat()
    version.regulatory_conclusion = json.dumps(conclusion, ensure_ascii=False)
    db.commit()
    db.refresh(version)
    return version


def get_group_filing(db: Session, group_filing_id: int) -> Optional[models.GroupFiling]:
    return db.query(models.GroupFiling).filter(models.GroupFiling.id == group_filing_id).first()


def get_group_version(db: Session, version_id: int) -> Optional[models.GroupFilingVersion]:
    return db.query(models.GroupFilingVersion).filter(
        models.GroupFilingVersion.id == version_id
    ).first()


def list_group_filings(db: Session, group_id: Optional[int] = None) -> List[models.GroupFiling]:
    query = db.query(models.GroupFiling)
    if group_id:
        query = query.filter(models.GroupFiling.group_id == group_id)
    return query.order_by(models.GroupFiling.year.desc(), models.GroupFiling.id.desc()).all()


def list_group_versions(
    db: Session, group_filing_id: int
) -> List[models.GroupFilingVersion]:
    return db.query(models.GroupFilingVersion).filter(
        models.GroupFilingVersion.group_filing_id == group_filing_id
    ).order_by(models.GroupFilingVersion.version_no.asc()).all()


# ============================ 勾稽校验 ============================

def get_version_reconciliation(db: Session, version: models.GroupFilingVersion) -> dict:
    """
    集团层级与成员层级余额、缺口、合规状态相互勾稽：
      ① 成员净积分合计 - 车型转让抵销 = 合并净积分（积分转让为零和内部流，不影响净额）
      ② 成员买入合计 = 对外买入 + 内部积分转让抵销；卖出同理（外部交易不被误抵销）
      ③ 跨年度结转合计 = 合并口径结转（结转不被抵销）
      ④ 合并结余 - 合并缺口 = 合并最终净积分，与合规状态一致
    """
    eliminations = version.eliminations
    credit_elim = _round2(sum(
        e.elimination_amount for e in eliminations
        if e.entry_type == ENTRY_CREDIT_TRANSFER
    ))
    model_elim = _round2(sum(
        e.elimination_amount for e in eliminations
        if e.entry_type == ENTRY_MODEL_TRANSFER
    ))

    check_details: List[str] = []

    net_expected = _round2(version.members_aggregate_net - model_elim)
    net_balanced = abs(net_expected - version.consolidated_net) <= EPS
    check_details.append(
        f"净积分勾稽：成员合计 {version.members_aggregate_net} - 车型转让抵销 {model_elim} "
        f"= {net_expected}，合并净积分 {version.consolidated_net} → {'一致' if net_balanced else '不一致'}"
    )

    buy_expected = _round2(version.external_bought + credit_elim)
    sell_expected = _round2(version.external_sold + credit_elim)
    external_balanced = (
        abs(buy_expected - version.members_bought) <= EPS
        and abs(sell_expected - version.members_sold) <= EPS
    )
    check_details.append(
        f"对外交易勾稽：成员买入 {version.members_bought} = 对外买入 {version.external_bought} "
        f"+ 内部积分转让抵销 {credit_elim}（={buy_expected}）；"
        f"成员卖出 {version.members_sold} = 对外卖出 {version.external_sold} "
        f"+ 内部抵销 {credit_elim}（={sell_expected}） → {'一致' if external_balanced else '不一致'}"
    )

    carryover_balanced = (
        abs(version.members_carryover_in - version.consolidated_carryover_in) <= EPS
        and abs(version.members_carryover_out - version.consolidated_carryover_out) <= EPS
        and credit_elim >= 0  # 抵销项目中不含结转类
    )
    check_details.append(
        f"跨年度结转勾稽：成员结转入 {version.members_carryover_in} / 出 {version.members_carryover_out}，"
        f"合并口径 {version.consolidated_carryover_in} / {version.consolidated_carryover_out}，"
        f"结转不参与抵销 → {'一致' if carryover_balanced else '不一致'}"
    )

    final_from_net = _round2(
        version.consolidated_net + version.consolidated_carryover_in
        + version.external_bought - version.external_sold - version.consolidated_carryover_out
    )
    surplus_gap_balanced = (
        abs(final_from_net - version.consolidated_final_net) <= EPS
        and abs(_round2(version.consolidated_surplus - version.consolidated_gap)
                - version.consolidated_final_net) <= EPS
        and (version.is_compliant == (version.consolidated_gap <= EPS))
    )
    check_details.append(
        f"结余/缺口勾稽：合并净积分 {version.consolidated_net} + 结转入 "
        f"{version.consolidated_carryover_in} + 对外买入 {version.external_bought} - 对外卖出 "
        f"{version.external_sold} - 结转出 {version.consolidated_carryover_out} = {final_from_net}；"
        f"结余 {version.consolidated_surplus} - 缺口 {version.consolidated_gap} = "
        f"{_round2(version.consolidated_surplus - version.consolidated_gap)}，"
        f"最终净积分 {version.consolidated_final_net}，"
        f"合规状态 {'达标' if version.is_compliant else '未达标'} → "
        f"{'一致' if surplus_gap_balanced else '不一致'}"
    )

    # 成员级明细与原始记录保留校验
    member_details = []
    raw_preserved = True
    for svm in version.member_selections:
        if not svm.included:
            continue
        filing = svm.member_filing
        records = json.loads(filing.record_snapshot or "[]")
        txns = json.loads(filing.transaction_snapshot or "[]")
        if not records:
            raw_preserved = False
        member_details.append({
            "enterprise_id": svm.enterprise_id,
            "enterprise_name": svm.enterprise.name if svm.enterprise else str(svm.enterprise_id),
            "member_filing_id": filing.id,
            "member_filing_version_no": filing.version_no,
            "change_type": svm.change_type,
            "net_credit": filing.net_credit,
            "final_net_credit": filing.final_net_credit,
            "credit_gap": filing.credit_gap,
            "credit_surplus": filing.credit_surplus,
            "is_compliant": filing.is_compliant,
            "raw_record_count": len(records),
            "raw_transaction_count": len(txns),
        })
    check_details.append(
        f"原始记录保留：各成员封账快照中的原始积分记录均未因抵销而删除 → "
        f"{'完好' if raw_preserved else '存在缺失'}"
    )

    all_balanced = (
        net_balanced and external_balanced and carryover_balanced
        and surplus_gap_balanced and raw_preserved
    )

    return {
        "year": version.group_filing.year if version.group_filing else None,
        "version_no": version.version_no,
        "status": version.status.value,
        "member_count": version.member_count,
        "members_aggregate_net": version.members_aggregate_net,
        "credit_transfer_elimination": credit_elim,
        "model_transfer_elimination": model_elim,
        "elimination_total": version.elimination_total,
        "consolidated_net": version.consolidated_net,
        "members_aggregate_gap": version.members_aggregate_gap,
        "members_aggregate_surplus": version.members_aggregate_surplus,
        "consolidated_gap": version.consolidated_gap,
        "consolidated_surplus": version.consolidated_surplus,
        "members_carryover_in": version.members_carryover_in,
        "members_carryover_out": version.members_carryover_out,
        "consolidated_carryover_in": version.consolidated_carryover_in,
        "consolidated_carryover_out": version.consolidated_carryover_out,
        "external_bought": version.external_bought,
        "external_sold": version.external_sold,
        "members_bought": version.members_bought,
        "members_sold": version.members_sold,
        "net_balanced": net_balanced,
        "carryover_balanced": carryover_balanced,
        "external_balanced": external_balanced,
        "surplus_gap_balanced": surplus_gap_balanced,
        "raw_records_preserved": raw_preserved,
        "all_balanced": all_balanced,
        "is_compliant": version.is_compliant,
        "member_details": member_details,
        "check_details": check_details,
    }
