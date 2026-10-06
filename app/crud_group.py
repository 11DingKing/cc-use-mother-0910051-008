"""集团统一申报：成员封账版本、合并版本、内部交易抵销与勾稽。

设计约束：
- 成员提交即封账（SEALED），更正申报产生新版本，旧版本置 SUPERSEDED，内容不改写；
- 合并版本（GroupConsolidation）的抵销项目（GroupElimination）只属于生成它的版本；
- 仅抵销合并范围内成员之间、且属于合并年度的内部交易；
  外部交易与跨年度结转一律不参与抵销；
- 已采用（ADOPTED）的合并版本不可修改、不可删除，更正只产生新版本；
- 集团层级结果必须与成员层级封账快照相互勾稽。
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from . import crud, models, schemas
from .models import (
    CarryoverStatus,
    ConsolidationReason,
    ConsolidationStatus,
    DeclarationStatus,
)

OPEN_ENDED_YEAR = 9999
EPSILON = 0.01


# ---------------------------------------------------------------------------
# 集团基础
# ---------------------------------------------------------------------------

def create_group(db: Session, group: schemas.EnterpriseGroupCreate) -> models.EnterpriseGroup:
    existing = db.query(models.EnterpriseGroup).filter(
        models.EnterpriseGroup.name == group.name
    ).first()
    if existing:
        raise ValueError(f"集团名称 {group.name} 已存在")
    db_group = models.EnterpriseGroup(**group.model_dump())
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group


def get_group(db: Session, group_id: int) -> Optional[models.EnterpriseGroup]:
    return db.query(models.EnterpriseGroup).filter(
        models.EnterpriseGroup.id == group_id
    ).first()


def get_groups(db: Session, skip: int = 0, limit: int = 100) -> List[models.EnterpriseGroup]:
    return db.query(models.EnterpriseGroup).offset(skip).limit(limit).all()


# ---------------------------------------------------------------------------
# 集团成员（带生效区间）
# ---------------------------------------------------------------------------

def _intervals_overlap(
    from_a: int, to_a: Optional[int], from_b: int, to_b: Optional[int]
) -> bool:
    end_a = to_a if to_a is not None else OPEN_ENDED_YEAR
    end_b = to_b if to_b is not None else OPEN_ENDED_YEAR
    return from_a <= end_b and from_b <= end_a


def _validate_membership_interval(
    db: Session,
    enterprise_id: int,
    effective_from_year: int,
    effective_to_year: Optional[int],
    exclude_membership_id: Optional[int] = None,
) -> Optional[str]:
    """同一企业在同一年度只能属于一个集团（任一集团内区间不得重叠）"""
    if effective_to_year is not None and effective_to_year < effective_from_year:
        return "成员生效截止年度不能早于起始年度"

    query = db.query(models.GroupMembership).filter(
        models.GroupMembership.enterprise_id == enterprise_id
    )
    if exclude_membership_id is not None:
        query = query.filter(models.GroupMembership.id != exclude_membership_id)

    enterprise = crud.get_enterprise(db, enterprise_id)
    ent_name = enterprise.name if enterprise else str(enterprise_id)

    for m in query.all():
        if _intervals_overlap(
            effective_from_year, effective_to_year,
            m.effective_from_year, m.effective_to_year,
        ):
            overlap_from = max(effective_from_year, m.effective_from_year)
            overlap_to = min(
                effective_to_year if effective_to_year is not None else OPEN_ENDED_YEAR,
                m.effective_to_year if m.effective_to_year is not None else OPEN_ENDED_YEAR,
            )
            group = get_group(db, m.group_id)
            group_name = group.name if group else str(m.group_id)
            return (
                f"企业「{ent_name}」在 {overlap_from}-{overlap_to} 年度已属于"
                f"集团「{group_name}」，成员生效区间不得重叠"
            )
    return None


def add_membership(
    db: Session, group_id: int, membership: schemas.GroupMembershipCreate
) -> models.GroupMembership:
    group = get_group(db, group_id)
    if not group:
        raise ValueError("集团不存在")
    enterprise = crud.get_enterprise(db, membership.enterprise_id)
    if not enterprise:
        raise ValueError("企业不存在")

    error = _validate_membership_interval(
        db, membership.enterprise_id,
        membership.effective_from_year, membership.effective_to_year,
    )
    if error:
        raise ValueError(error)

    db_membership = models.GroupMembership(
        group_id=group_id,
        **membership.model_dump(),
    )
    db.add(db_membership)
    db.commit()
    db.refresh(db_membership)
    return db_membership


def update_membership(
    db: Session, group_id: int, membership_id: int,
    membership_update: schemas.GroupMembershipUpdate,
) -> Optional[models.GroupMembership]:
    db_membership = db.query(models.GroupMembership).filter(
        models.GroupMembership.id == membership_id,
        models.GroupMembership.group_id == group_id,
    ).first()
    if not db_membership:
        return None

    update_data = membership_update.model_dump(exclude_unset=True)
    new_from = update_data.get("effective_from_year", db_membership.effective_from_year)
    new_to = update_data.get("effective_to_year", db_membership.effective_to_year)

    error = _validate_membership_interval(
        db, db_membership.enterprise_id, new_from, new_to,
        exclude_membership_id=db_membership.id,
    )
    if error:
        raise ValueError(error)

    for key, value in update_data.items():
        setattr(db_membership, key, value)
    db.commit()
    db.refresh(db_membership)
    return db_membership


def get_memberships(
    db: Session, group_id: int, year: Optional[int] = None
) -> List[models.GroupMembership]:
    query = db.query(models.GroupMembership).filter(
        models.GroupMembership.group_id == group_id
    )
    memberships = query.all()
    if year is not None:
        memberships = [
            m for m in memberships
            if m.effective_from_year <= year <= (
                m.effective_to_year if m.effective_to_year is not None else OPEN_ENDED_YEAR
            )
        ]
    return memberships


def get_effective_memberships(
    db: Session, group_id: int, year: int
) -> List[models.GroupMembership]:
    return get_memberships(db, group_id, year=year)


def is_effective_member(db: Session, group_id: int, enterprise_id: int, year: int) -> bool:
    return any(
        m.enterprise_id == enterprise_id
        for m in get_effective_memberships(db, group_id, year)
    )


# ---------------------------------------------------------------------------
# 成员封账申报版本
# ---------------------------------------------------------------------------

def _enterprise_year_transactions(
    db: Session, enterprise_id: int, year: int
) -> List[models.CreditTransaction]:
    transactions = db.query(models.CreditTransaction).filter(
        (models.CreditTransaction.from_enterprise_id == enterprise_id) |
        (models.CreditTransaction.to_enterprise_id == enterprise_id)
    ).all()
    return [
        t for t in transactions
        if (t.transaction_date.year if t.transaction_date else year) == year
    ]


def seal_member_declaration(
    db: Session, group_id: int, payload: schemas.MemberDeclarationCreate
) -> models.MemberDeclaration:
    """成员提交封账版本：快照当年核算、交易与结转数据；更正产生新版本，旧版本不改写"""
    group = get_group(db, group_id)
    if not group:
        raise ValueError("集团不存在")
    enterprise = crud.get_enterprise(db, payload.enterprise_id)
    if not enterprise:
        raise ValueError("企业不存在")
    if not is_effective_member(db, group_id, payload.enterprise_id, payload.year):
        raise ValueError(
            f"企业「{enterprise.name}」在 {payload.year} 年度不是集团「{group.name}」"
            f"的生效成员，不能提交该年度封账申报"
        )

    base = crud.calculate_enterprise_credit_summary(db, payload.enterprise_id, payload.year)

    bought = sold = 0.0
    internal_bought = internal_sold = 0.0
    snapshots: List[models.MemberDeclarationTransaction] = []
    for txn in _enterprise_year_transactions(db, payload.enterprise_id, payload.year):
        if txn.to_enterprise_id == payload.enterprise_id:
            direction = "buy"
            counterparty_id = txn.from_enterprise_id
        else:
            direction = "sell"
            counterparty_id = txn.to_enterprise_id
        is_internal = is_effective_member(db, group_id, counterparty_id, payload.year)

        if direction == "buy":
            bought += txn.credit_amount
            if is_internal:
                internal_bought += txn.credit_amount
        else:
            sold += txn.credit_amount
            if is_internal:
                internal_sold += txn.credit_amount

        snapshots.append(models.MemberDeclarationTransaction(
            transaction_id=txn.id,
            transaction_no=txn.transaction_no,
            counterparty_enterprise_id=counterparty_id,
            direction=direction,
            credit_amount=round(txn.credit_amount, 2),
            is_internal=is_internal,
            transaction_year=payload.year,
        ))

    carryovers_in = crud.get_credit_carryovers(
        db, enterprise_id=payload.enterprise_id, to_year=payload.year,
        status=CarryoverStatus.APPROVED,
    )
    carryover_in = sum(c.carryover_amount for c in carryovers_in)
    carryovers_out = crud.get_credit_carryovers(
        db, enterprise_id=payload.enterprise_id, from_year=payload.year,
        status=CarryoverStatus.APPROVED,
    )
    carryover_out = sum(c.carryover_amount for c in carryovers_out)

    final_net = round(
        base.net_credit + carryover_in + bought - sold - carryover_out, 2
    )
    if final_net >= 0:
        credit_gap, credit_surplus, is_compliant = 0.0, final_net, True
    else:
        credit_gap, credit_surplus, is_compliant = round(abs(final_net), 2), 0.0, False

    previous_versions = db.query(models.MemberDeclaration).filter(
        models.MemberDeclaration.group_id == group_id,
        models.MemberDeclaration.enterprise_id == payload.enterprise_id,
        models.MemberDeclaration.year == payload.year,
    ).all()
    version_no = max((v.version_no for v in previous_versions), default=0) + 1
    for prev in previous_versions:
        if prev.status == DeclarationStatus.SEALED:
            prev.status = DeclarationStatus.SUPERSEDED

    db_declaration = models.MemberDeclaration(
        group_id=group_id,
        enterprise_id=payload.enterprise_id,
        year=payload.year,
        version_no=version_no,
        status=DeclarationStatus.SEALED,
        total_positive_credit=base.total_positive_credit,
        total_negative_credit=base.total_negative_credit,
        net_credit=base.net_credit,
        carryover_in=round(carryover_in, 2),
        carryover_out=round(carryover_out, 2),
        bought_credit=round(bought, 2),
        sold_credit=round(sold, 2),
        internal_bought_credit=round(internal_bought, 2),
        internal_sold_credit=round(internal_sold, 2),
        external_bought_credit=round(bought - internal_bought, 2),
        external_sold_credit=round(sold - internal_sold, 2),
        final_net_credit=final_net,
        credit_gap=credit_gap,
        credit_surplus=credit_surplus,
        is_compliant=is_compliant,
        remark=payload.remark,
    )
    db.add(db_declaration)
    db.flush()
    for snap in snapshots:
        snap.declaration_id = db_declaration.id
        db.add(snap)
    db.commit()
    db.refresh(db_declaration)
    return db_declaration


def get_declarations(
    db: Session,
    group_id: int,
    year: Optional[int] = None,
    enterprise_id: Optional[int] = None,
) -> List[models.MemberDeclaration]:
    query = db.query(models.MemberDeclaration).filter(
        models.MemberDeclaration.group_id == group_id
    )
    if year is not None:
        query = query.filter(models.MemberDeclaration.year == year)
    if enterprise_id is not None:
        query = query.filter(models.MemberDeclaration.enterprise_id == enterprise_id)
    return query.order_by(
        models.MemberDeclaration.enterprise_id, models.MemberDeclaration.version_no
    ).all()


def get_declaration(
    db: Session, group_id: int, declaration_id: int
) -> Optional[models.MemberDeclaration]:
    return db.query(models.MemberDeclaration).filter(
        models.MemberDeclaration.id == declaration_id,
        models.MemberDeclaration.group_id == group_id,
    ).first()


def get_latest_declaration(
    db: Session, group_id: int, enterprise_id: int, year: int
) -> Optional[models.MemberDeclaration]:
    return db.query(models.MemberDeclaration).filter(
        models.MemberDeclaration.group_id == group_id,
        models.MemberDeclaration.enterprise_id == enterprise_id,
        models.MemberDeclaration.year == year,
    ).order_by(models.MemberDeclaration.version_no.desc()).first()


# ---------------------------------------------------------------------------
# 集团合并版本
# ---------------------------------------------------------------------------

def _build_change_summary(
    db: Session,
    reason: str,
    previous: Optional[models.GroupConsolidation],
    selected: Dict[int, models.MemberDeclaration],
    missing_members: List[models.GroupMembership],
    aggregates: Dict[str, float],
) -> str:
    """生成与上一合并版本的成员及金额差异说明"""
    prev_member_map: Dict[int, models.GroupConsolidationMember] = {}
    if previous is not None:
        for pm in previous.members:
            prev_member_map[pm.enterprise_id] = pm

    current_ids = set(selected.keys())
    previous_ids = set(prev_member_map.keys())

    def _ent_name(enterprise_id: int) -> str:
        ent = crud.get_enterprise(db, enterprise_id)
        return ent.name if ent else str(enterprise_id)

    members_added = [
        {"enterprise_id": eid, "enterprise_name": _ent_name(eid)}
        for eid in sorted(current_ids - previous_ids)
    ]
    members_removed = [
        {"enterprise_id": eid, "enterprise_name": _ent_name(eid)}
        for eid in sorted(previous_ids - current_ids)
    ]
    members_version_changed = [
        {
            "enterprise_id": eid,
            "enterprise_name": _ent_name(eid),
            "from_declaration_version": prev_member_map[eid].declaration_version_no,
            "to_declaration_version": selected[eid].version_no,
        }
        for eid in sorted(current_ids & previous_ids)
        if prev_member_map[eid].declaration_version_no != selected[eid].version_no
    ]
    missing = [
        {
            "enterprise_id": m.enterprise_id,
            "enterprise_name": _ent_name(m.enterprise_id),
            "note": "当年生效成员但未纳入本次合并范围（未提交封账版本或未选择）",
        }
        for m in missing_members
    ]

    amount_keys = [
        ("net_credit", "当年净积分"),
        ("eliminated_amount", "内部交易抵销金额"),
        ("external_bought_credit", "外部买入积分"),
        ("external_sold_credit", "外部卖出积分"),
        ("carryover_in", "上年结转积分"),
        ("final_net_credit", "最终净积分"),
        ("credit_gap", "积分缺口"),
        ("credit_surplus", "积分钟余"),
    ]
    amount_changes = {}
    for key, label in amount_keys:
        current_value = round(aggregates[key], 2)
        previous_value = round(getattr(previous, key), 2) if previous is not None else None
        amount_changes[key] = {
            "label": label,
            "previous": previous_value,
            "current": current_value,
            "change": (
                round(current_value - previous_value, 2)
                if previous_value is not None else None
            ),
        }

    parts = []
    if previous is None:
        parts.append(
            f"首次合并：纳入成员{len(selected)}家，"
            f"抵销内部交易金额{aggregates['eliminated_amount']:.2f}分。"
        )
    else:
        parts.append(f"与上一版本V{previous.version_no}相比：")
        if members_added:
            parts.append("新增成员[" + "、".join(m["enterprise_name"] for m in members_added) + "]；")
        if members_removed:
            parts.append("移出成员[" + "、".join(m["enterprise_name"] for m in members_removed) + "]；")
        if members_version_changed:
            desc = "、".join(
                f"{m['enterprise_name']}(V{m['from_declaration_version']}→V{m['to_declaration_version']})"
                for m in members_version_changed
            )
            parts.append(f"成员申报版本变更[{desc}]；")
        for key, label in amount_keys:
            change = amount_changes[key]["change"]
            if change is not None and abs(change) > EPSILON:
                parts.append(
                    f"{label}由{amount_changes[key]['previous']:.2f}变为"
                    f"{amount_changes[key]['current']:.2f}({change:+.2f})；"
                )
        if not (members_added or members_removed or members_version_changed) and all(
            amount_changes[k]["change"] is None or abs(amount_changes[k]["change"]) <= EPSILON
            for k, _ in amount_keys
        ):
            parts.append("成员范围与金额均无实质变化；")
    if missing:
        parts.append(
            "未纳入成员[" + "、".join(m["enterprise_name"] for m in missing) + "]（迟交或未选择）。"
        )

    return json.dumps({
        "reason": reason,
        "previous_version": (
            {"id": previous.id, "version_no": previous.version_no}
            if previous is not None else None
        ),
        "members_added": members_added,
        "members_removed": members_removed,
        "members_version_changed": members_version_changed,
        "missing_members": missing,
        "amount_changes": amount_changes,
        "summary_text": "".join(parts),
    }, ensure_ascii=False)


def generate_consolidation(
    db: Session, group_id: int, payload: schemas.GroupConsolidationGenerate
) -> models.GroupConsolidation:
    """生成新的集团合并版本：选择合并范围，生成仅属于本版本的抵销项目"""
    group = get_group(db, group_id)
    if not group:
        raise ValueError("集团不存在")

    effective = get_effective_memberships(db, group_id, payload.year)
    effective_ids = {m.enterprise_id for m in effective}

    if payload.member_enterprise_ids:
        scope_ids = list(dict.fromkeys(payload.member_enterprise_ids))
        not_members = [eid for eid in scope_ids if eid not in effective_ids]
        if not_members:
            names = []
            for eid in not_members:
                ent = crud.get_enterprise(db, eid)
                names.append(ent.name if ent else str(eid))
            raise ValueError(
                f"企业[{'、'.join(names)}]在 {payload.year} 年度不是集团生效成员，"
                f"不能纳入合并范围"
            )
    else:
        scope_ids = sorted(effective_ids)

    pinned: Dict[int, models.MemberDeclaration] = {}
    if payload.declaration_ids:
        for declaration_id in payload.declaration_ids:
            declaration = get_declaration(db, group_id, declaration_id)
            if not declaration:
                raise ValueError(f"成员封账版本 {declaration_id} 不存在")
            if declaration.year != payload.year:
                raise ValueError(
                    f"成员封账版本 {declaration_id} 属于 {declaration.year} 年度，"
                    f"不能用于 {payload.year} 年度合并"
                )
            if declaration.enterprise_id not in scope_ids:
                raise ValueError(
                    f"成员封账版本 {declaration_id} 的企业不在本次合并范围内"
                )
            pinned[declaration.enterprise_id] = declaration

    selected: Dict[int, models.MemberDeclaration] = {}
    missing_ids: List[int] = []
    for eid in scope_ids:
        declaration = pinned.get(eid) or get_latest_declaration(
            db, group_id, eid, payload.year
        )
        if declaration is None:
            missing_ids.append(eid)
        else:
            selected[eid] = declaration

    if missing_ids and payload.member_enterprise_ids:
        names = []
        for eid in missing_ids:
            ent = crud.get_enterprise(db, eid)
            names.append(ent.name if ent else str(eid))
        raise ValueError(
            f"所选成员[{'、'.join(names)}]尚未提交 {payload.year} 年度封账版本，"
            f"不能纳入合并"
        )
    if not selected:
        raise ValueError(
            f"合并范围内没有成员已提交 {payload.year} 年度封账版本，无法生成合并版本"
        )

    missing_members = [m for m in effective if m.enterprise_id in missing_ids]

    # ---- 汇总成员封账快照 ----
    total_positive = sum(d.total_positive_credit for d in selected.values())
    total_negative = sum(d.total_negative_credit for d in selected.values())
    net_credit = sum(d.net_credit for d in selected.values())
    carryover_in = sum(d.carryover_in for d in selected.values())
    carryover_out = sum(d.carryover_out for d in selected.values())
    total_bought = sum(d.bought_credit for d in selected.values())
    total_sold = sum(d.sold_credit for d in selected.values())
    final_net = round(sum(d.final_net_credit for d in selected.values()), 2)

    # ---- 内部交易抵销：仅合并范围内成员之间、且属于合并年度的交易 ----
    eliminated_internal_bought = 0.0
    eliminated_internal_sold = 0.0
    elimination_candidates: Dict[int, dict] = {}
    for eid, declaration in selected.items():
        for snap in declaration.transactions:
            if snap.transaction_year != payload.year:
                continue  # 跨年度交易不抵销
            if snap.counterparty_enterprise_id not in selected:
                continue  # 外部交易不抵销
            if snap.direction == "buy":
                eliminated_internal_bought += snap.credit_amount
            else:
                eliminated_internal_sold += snap.credit_amount
            entry = elimination_candidates.setdefault(snap.transaction_id, {
                "transaction_no": snap.transaction_no,
                "credit_amount": snap.credit_amount,
                "captured_by_from": False,
                "captured_by_to": False,
            })
            original = snap.original_transaction or db.get(
                models.CreditTransaction, snap.transaction_id
            )
            if original is not None:
                entry["from_enterprise_id"] = original.from_enterprise_id
                entry["to_enterprise_id"] = original.to_enterprise_id
            if snap.direction == "sell":
                entry["captured_by_from"] = True
            else:
                entry["captured_by_to"] = True

    eliminated_internal_bought = round(eliminated_internal_bought, 2)
    eliminated_internal_sold = round(eliminated_internal_sold, 2)
    eliminated_amount = round(
        sum(e["credit_amount"] for e in elimination_candidates.values()), 2
    )
    external_bought = round(total_bought - eliminated_internal_bought, 2)
    external_sold = round(total_sold - eliminated_internal_sold, 2)

    if final_net >= 0:
        credit_gap, credit_surplus, is_compliant = 0.0, final_net, True
    else:
        credit_gap, credit_surplus, is_compliant = round(abs(final_net), 2), 0.0, False

    aggregates = {
        "net_credit": round(net_credit, 2),
        "eliminated_amount": eliminated_amount,
        "external_bought_credit": external_bought,
        "external_sold_credit": external_sold,
        "carryover_in": round(carryover_in, 2),
        "final_net_credit": final_net,
        "credit_gap": credit_gap,
        "credit_surplus": credit_surplus,
    }

    previous = db.query(models.GroupConsolidation).filter(
        models.GroupConsolidation.group_id == group_id,
        models.GroupConsolidation.year == payload.year,
    ).order_by(models.GroupConsolidation.version_no.desc()).first()
    version_no = (previous.version_no + 1) if previous else 1

    reason = payload.reason.value if payload.reason else (
        ConsolidationReason.INITIAL.value if previous is None
        else ConsolidationReason.OTHER.value
    )
    change_summary = _build_change_summary(
        db, reason, previous, selected, missing_members, aggregates
    )

    db_consolidation = models.GroupConsolidation(
        group_id=group_id,
        year=payload.year,
        version_no=version_no,
        status=ConsolidationStatus.GENERATED,
        reason=reason,
        previous_version_id=previous.id if previous else None,
        member_count=len(selected),
        total_positive_credit=round(total_positive, 2),
        total_negative_credit=round(total_negative, 2),
        net_credit=round(net_credit, 2),
        carryover_in=round(carryover_in, 2),
        carryover_out=round(carryover_out, 2),
        eliminated_internal_bought=eliminated_internal_bought,
        eliminated_internal_sold=eliminated_internal_sold,
        eliminated_amount=eliminated_amount,
        external_bought_credit=external_bought,
        external_sold_credit=external_sold,
        final_net_credit=final_net,
        credit_gap=credit_gap,
        credit_surplus=credit_surplus,
        is_compliant=is_compliant,
        change_summary=change_summary,
        remark=payload.remark,
    )
    db.add(db_consolidation)
    db.flush()

    for eid, declaration in selected.items():
        db.add(models.GroupConsolidationMember(
            consolidation_id=db_consolidation.id,
            declaration_id=declaration.id,
            enterprise_id=eid,
            declaration_version_no=declaration.version_no,
            final_net_credit=declaration.final_net_credit,
            credit_gap=declaration.credit_gap,
            credit_surplus=declaration.credit_surplus,
            is_compliant=declaration.is_compliant,
        ))

    for txn_id, entry in elimination_candidates.items():
        db.add(models.GroupElimination(
            consolidation_id=db_consolidation.id,
            transaction_id=txn_id,
            transaction_no=entry["transaction_no"],
            from_enterprise_id=entry.get("from_enterprise_id"),
            to_enterprise_id=entry.get("to_enterprise_id"),
            credit_amount=round(entry["credit_amount"], 2),
            eliminated_amount=round(entry["credit_amount"], 2),
            captured_by_from=entry["captured_by_from"],
            captured_by_to=entry["captured_by_to"],
            remark=f"{payload.year}年度集团内部交易抵销",
        ))

    db.commit()
    db.refresh(db_consolidation)
    return db_consolidation


def get_consolidations(
    db: Session, group_id: int, year: Optional[int] = None
) -> List[models.GroupConsolidation]:
    query = db.query(models.GroupConsolidation).filter(
        models.GroupConsolidation.group_id == group_id
    )
    if year is not None:
        query = query.filter(models.GroupConsolidation.year == year)
    return query.order_by(models.GroupConsolidation.version_no).all()


def get_consolidation(
    db: Session, group_id: int, consolidation_id: int
) -> Optional[models.GroupConsolidation]:
    return db.query(models.GroupConsolidation).filter(
        models.GroupConsolidation.id == consolidation_id,
        models.GroupConsolidation.group_id == group_id,
    ).first()


def adopt_consolidation(
    db: Session, group_id: int, consolidation_id: int
) -> models.GroupConsolidation:
    """采用合并版本作为监管结论：已采用内容不可改写，旧采用版本置为 superseded"""
    consolidation = get_consolidation(db, group_id, consolidation_id)
    if not consolidation:
        raise ValueError("合并版本不存在")
    if consolidation.status == ConsolidationStatus.ADOPTED:
        raise ValueError(f"合并版本V{consolidation.version_no}已被采用，无需重复采用")

    previously_adopted = db.query(models.GroupConsolidation).filter(
        models.GroupConsolidation.group_id == group_id,
        models.GroupConsolidation.year == consolidation.year,
        models.GroupConsolidation.status == ConsolidationStatus.ADOPTED,
        models.GroupConsolidation.id != consolidation.id,
    ).all()
    for old in previously_adopted:
        old.status = ConsolidationStatus.SUPERSEDED

    consolidation.status = ConsolidationStatus.ADOPTED
    consolidation.adopted_at = datetime.utcnow()
    db.commit()
    db.refresh(consolidation)
    return consolidation


# ---------------------------------------------------------------------------
# 集团与成员层级勾稽
# ---------------------------------------------------------------------------

def get_reconciliation(
    db: Session, group_id: int, consolidation_id: int
) -> dict:
    """勾稽报告：集团层级余额、缺口、合规状态与成员封账快照相互核对"""
    consolidation = get_consolidation(db, group_id, consolidation_id)
    if not consolidation:
        raise ValueError("合并版本不存在")

    declarations = [cm.declaration for cm in consolidation.members]

    member_sum = {
        "net_credit": round(sum(d.net_credit for d in declarations), 2),
        "final_net_credit": round(sum(d.final_net_credit for d in declarations), 2),
        "credit_gap": round(sum(d.credit_gap for d in declarations), 2),
        "credit_surplus": round(sum(d.credit_surplus for d in declarations), 2),
        "bought_credit": round(sum(d.bought_credit for d in declarations), 2),
        "sold_credit": round(sum(d.sold_credit for d in declarations), 2),
        "external_bought_credit": round(sum(d.external_bought_credit for d in declarations), 2),
        "external_sold_credit": round(sum(d.external_sold_credit for d in declarations), 2),
        "carryover_in": round(sum(d.carryover_in for d in declarations), 2),
        "carryover_out": round(sum(d.carryover_out for d in declarations), 2),
    }

    checks = []

    def _check(name: str, member_side: float, group_side: float) -> None:
        difference = round(group_side - member_side, 2)
        checks.append({
            "name": name,
            "member_side": round(member_side, 2),
            "group_side": round(group_side, 2),
            "difference": difference,
            "passed": abs(difference) <= EPSILON,
        })

    _check("集团当年净积分=成员封账净积分合计", member_sum["net_credit"], consolidation.net_credit)
    _check(
        "集团最终净积分=成员封账最终净积分合计(内部抵销自平衡)",
        member_sum["final_net_credit"], consolidation.final_net_credit,
    )
    _check(
        "内部抵销借贷平衡(成员间买入抵销=卖出抵销)",
        consolidation.eliminated_internal_sold, consolidation.eliminated_internal_bought,
    )
    elimination_total = round(sum(e.eliminated_amount for e in consolidation.eliminations), 2)
    _check(
        "抵销项目金额合计=内部交易抵销合计",
        consolidation.eliminated_internal_sold, elimination_total,
    )
    _check(
        "外部买入未被抵销(集团外部买入=成员外部买入合计)",
        member_sum["external_bought_credit"], consolidation.external_bought_credit,
    )
    _check(
        "外部卖出未被抵销(集团外部卖出=成员外部卖出合计)",
        member_sum["external_sold_credit"], consolidation.external_sold_credit,
    )
    _check(
        "跨年度结转转入未被抵销(集团=成员合计)",
        member_sum["carryover_in"], consolidation.carryover_in,
    )
    _check(
        "跨年度结转转出未被抵销(集团=成员合计)",
        member_sum["carryover_out"], consolidation.carryover_out,
    )
    _check(
        "缺口与结余勾稽(集团钟余-集团缺口=集团最终净积分)",
        consolidation.final_net_credit,
        round(consolidation.credit_surplus - consolidation.credit_gap, 2),
    )

    # 原始交易记录保留核对：抵销不删除、不改写双方原始记录
    missing_originals = []
    for elimination in consolidation.eliminations:
        original = db.query(models.CreditTransaction).filter(
            models.CreditTransaction.id == elimination.transaction_id
        ).first()
        if original is None:
            missing_originals.append(elimination.transaction_id)
        elif abs(original.credit_amount - elimination.credit_amount) > EPSILON:
            missing_originals.append(elimination.transaction_id)
    checks.append({
        "name": "抵销后双方原始交易记录完整保留",
        "member_side": float(len(consolidation.eliminations)),
        "group_side": float(len(consolidation.eliminations) - len(missing_originals)),
        "difference": float(-len(missing_originals)),
        "passed": len(missing_originals) == 0,
    })

    member_details = []
    for cm in consolidation.members:
        declaration = cm.declaration
        enterprise = crud.get_enterprise(db, cm.enterprise_id)
        member_details.append({
            "enterprise_id": cm.enterprise_id,
            "enterprise_name": enterprise.name if enterprise else "",
            "declaration_id": declaration.id,
            "declaration_version_no": cm.declaration_version_no,
            "net_credit": declaration.net_credit,
            "bought_credit": declaration.bought_credit,
            "sold_credit": declaration.sold_credit,
            "internal_bought_credit": declaration.internal_bought_credit,
            "internal_sold_credit": declaration.internal_sold_credit,
            "carryover_in": declaration.carryover_in,
            "carryover_out": declaration.carryover_out,
            "final_net_credit": declaration.final_net_credit,
            "credit_gap": declaration.credit_gap,
            "credit_surplus": declaration.credit_surplus,
            "is_compliant": declaration.is_compliant,
        })

    return {
        "consolidation_id": consolidation.id,
        "group_id": group_id,
        "year": consolidation.year,
        "version_no": consolidation.version_no,
        "status": consolidation.status.value,
        "group_level": {
            "net_credit": consolidation.net_credit,
            "eliminated_amount": consolidation.eliminated_amount,
            "eliminated_internal_bought": consolidation.eliminated_internal_bought,
            "eliminated_internal_sold": consolidation.eliminated_internal_sold,
            "external_bought_credit": consolidation.external_bought_credit,
            "external_sold_credit": consolidation.external_sold_credit,
            "carryover_in": consolidation.carryover_in,
            "carryover_out": consolidation.carryover_out,
            "final_net_credit": consolidation.final_net_credit,
            "credit_gap": consolidation.credit_gap,
            "credit_surplus": consolidation.credit_surplus,
            "is_compliant": consolidation.is_compliant,
        },
        "member_level": member_details,
        "member_sums": member_sum,
        "non_compliant_members": sum(1 for m in member_details if not m["is_compliant"]),
        "checks": checks,
        "all_passed": all(c["passed"] for c in checks),
    }
