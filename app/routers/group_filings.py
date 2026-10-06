from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import group_crud, schemas
from ..database import get_db

router = APIRouter(prefix="/group-filings", tags=["group-filings"])


# ============================ 集团 ============================

@router.post("/groups", response_model=schemas.EnterpriseGroup)
def create_group(group: schemas.EnterpriseGroupCreate, db: Session = Depends(get_db)):
    try:
        return group_crud.create_group(db, group)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/groups", response_model=List[schemas.EnterpriseGroup])
def list_groups(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return group_crud.list_groups(db, skip=skip, limit=limit)


@router.get("/groups/{group_id}", response_model=schemas.EnterpriseGroup)
def get_group(group_id: int, db: Session = Depends(get_db)):
    group = group_crud.get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="集团不存在")
    return group


@router.patch("/groups/{group_id}", response_model=schemas.EnterpriseGroup)
def update_group(
    group_id: int,
    group_update: schemas.EnterpriseGroupUpdate,
    db: Session = Depends(get_db),
):
    group = group_crud.update_group(db, group_id, group_update)
    if not group:
        raise HTTPException(status_code=404, detail="集团不存在")
    return group


# ============================ 成员与生效区间 ============================

@router.post("/groups/{group_id}/memberships", response_model=schemas.GroupMembership)
def add_membership(
    group_id: int,
    req: schemas.GroupMembershipCreate,
    db: Session = Depends(get_db),
):
    try:
        m = group_crud.add_membership(db, group_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _membership_out(db, m)


@router.post("/groups/{group_id}/members/{enterprise_id}/exit", response_model=schemas.GroupMembership)
def exit_membership(
    group_id: int,
    enterprise_id: int,
    req: schemas.GroupMembershipExit,
    db: Session = Depends(get_db),
):
    try:
        m = group_crud.exit_membership(db, group_id, enterprise_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _membership_out(db, m)


@router.get("/groups/{group_id}/memberships", response_model=List[schemas.GroupMembership])
def list_memberships(
    group_id: int,
    on_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    import datetime as _dt
    target_date = None
    if on_date:
        try:
            target_date = _dt.date.fromisoformat(on_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="on_date 需为 YYYY-MM-DD 格式")
    return group_crud.list_memberships(db, group_id, on_date=target_date)


def _membership_out(db: Session, m) -> dict:
    from .. import crud
    enterprise = crud.get_enterprise(db, m.enterprise_id)
    return {
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
    }


# ============================ 成员封账 ============================

@router.post("/member-filings/seal", response_model=schemas.MemberFiling)
def seal_member_filing(
    req: schemas.MemberFilingSealRequest,
    db: Session = Depends(get_db),
):
    try:
        filing = group_crud.seal_member_filing(db, req.enterprise_id, req.year, req.remark)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _filing_out(db, filing)


@router.get("/member-filings", response_model=List[schemas.MemberFiling])
def list_member_filings(
    enterprise_id: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
):
    rows = group_crud.list_member_filings(db, enterprise_id=enterprise_id, year=year)
    return [_filing_out(db, f) for f in rows]


@router.get("/member-filings/{filing_id}", response_model=schemas.MemberFiling)
def get_member_filing(filing_id: int, db: Session = Depends(get_db)):
    filing = group_crud.get_member_filing(db, filing_id)
    if not filing:
        raise HTTPException(status_code=404, detail="成员封账版本不存在")
    return _filing_out(db, filing)


def _filing_out(db: Session, filing) -> dict:
    from .. import crud
    enterprise = crud.get_enterprise(db, filing.enterprise_id)
    return {
        "id": filing.id,
        "filing_no": filing.filing_no,
        "enterprise_id": filing.enterprise_id,
        "enterprise_name": enterprise.name if enterprise else "",
        "year": filing.year,
        "version_no": filing.version_no,
        "status": filing.status,
        "superseded_by_filing_id": filing.superseded_by_filing_id,
        "total_positive_credit": filing.total_positive_credit,
        "total_negative_credit": filing.total_negative_credit,
        "net_credit": filing.net_credit,
        "carryover_in": filing.carryover_in,
        "carryover_out": filing.carryover_out,
        "bought_credit": filing.bought_credit,
        "sold_credit": filing.sold_credit,
        "final_net_credit": filing.final_net_credit,
        "credit_gap": filing.credit_gap,
        "credit_surplus": filing.credit_surplus,
        "is_compliant": filing.is_compliant,
        "sealed_at": filing.sealed_at,
        "remark": filing.remark,
    }


# ============================ 集团内部车型转让登记 ============================

@router.post("/internal-model-transfers", response_model=schemas.InternalModelTransfer)
def register_internal_model_transfer(
    req: schemas.InternalModelTransferCreate,
    db: Session = Depends(get_db),
):
    try:
        tr = group_crud.register_internal_model_transfer(db, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _transfer_out(db, tr)


@router.get("/internal-model-transfers", response_model=List[schemas.InternalModelTransfer])
def list_internal_model_transfers(year: Optional[int] = None, db: Session = Depends(get_db)):
    rows = group_crud.list_internal_model_transfers(db, year=year)
    return [_transfer_out(db, t) for t in rows]


def _transfer_out(db: Session, tr) -> dict:
    from .. import crud
    seller = crud.get_enterprise(db, tr.seller_enterprise_id)
    buyer = crud.get_enterprise(db, tr.buyer_enterprise_id)
    return {
        "id": tr.id,
        "transfer_no": tr.transfer_no,
        "year": tr.year,
        "seller_enterprise_id": tr.seller_enterprise_id,
        "buyer_enterprise_id": tr.buyer_enterprise_id,
        "seller_enterprise_name": seller.name if seller else "",
        "buyer_enterprise_name": buyer.name if buyer else "",
        "model_name": tr.model_name,
        "seller_record_id": tr.seller_record_id,
        "buyer_record_id": tr.buyer_record_id,
        "duplicated_credit": tr.duplicated_credit,
        "remark": tr.remark,
        "created_at": tr.created_at,
    }


# ============================ 集团合并版本 ============================

@router.post("/consolidation-versions", response_model=schemas.GroupFilingVersionDetail)
def create_consolidation_version(
    req: schemas.GroupConsolidationCreateRequest,
    db: Session = Depends(get_db),
):
    try:
        version = group_crud.create_group_consolidation_version(db, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _version_detail(db, version)


@router.get("/groups/{group_id}/filings")
def list_group_filings(group_id: int, db: Session = Depends(get_db)):
    group = group_crud.get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="集团不存在")
    result = []
    for filing in group_crud.list_group_filings(db, group_id=group_id):
        result.append({
            "id": filing.id,
            "filing_no": filing.filing_no,
            "group_id": filing.group_id,
            "year": filing.year,
            "remark": filing.remark,
            "versions": [
                {
                    "id": v.id,
                    "version_no": v.version_no,
                    "status": v.status,
                    "change_reason": v.change_reason,
                    "member_count": v.member_count,
                    "consolidated_net": v.consolidated_net,
                    "consolidated_gap": v.consolidated_gap,
                    "consolidated_surplus": v.consolidated_surplus,
                    "is_compliant": v.is_compliant,
                    "created_at": v.created_at,
                }
                for v in group_crud.list_group_versions(db, filing.id)
            ],
        })
    return result


@router.get("/consolidation-versions/{version_id}", response_model=schemas.GroupFilingVersionDetail)
def get_consolidation_version(version_id: int, db: Session = Depends(get_db)):
    version = group_crud.get_group_version(db, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="合并版本不存在")
    return _version_detail(db, version)


@router.post("/consolidation-versions/{version_id}/lock", response_model=schemas.GroupFilingVersionDetail)
def lock_consolidation_version(version_id: int, db: Session = Depends(get_db)):
    try:
        version = group_crud.lock_group_version(db, version_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _version_detail(db, version)


@router.get("/consolidation-versions/{version_id}/reconciliation")
def get_consolidation_reconciliation(version_id: int, db: Session = Depends(get_db)):
    version = group_crud.get_group_version(db, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="合并版本不存在")
    return group_crud.get_version_reconciliation(db, version)


def _version_detail(db: Session, version) -> dict:
    from .. import crud
    members = []
    for svm in version.member_selections:
        filing = svm.member_filing
        enterprise = crud.get_enterprise(db, svm.enterprise_id)
        members.append({
            "enterprise_id": svm.enterprise_id,
            "enterprise_name": enterprise.name if enterprise else "",
            "member_filing_id": svm.member_filing_id,
            "member_filing_version_no": filing.version_no,
            "change_type": svm.change_type,
            "prior_filing_id": svm.prior_filing_id,
            "included": svm.included,
            "net_credit": filing.net_credit,
            "credit_gap": filing.credit_gap,
            "credit_surplus": filing.credit_surplus,
            "is_compliant": filing.is_compliant,
        })

    eliminations = []
    for e in version.eliminations:
        eliminations.append({
            "id": e.id,
            "elimination_no": e.elimination_no,
            "entry_type": e.entry_type,
            "year": e.year,
            "seller_enterprise_id": e.seller_enterprise_id,
            "buyer_enterprise_id": e.buyer_enterprise_id,
            "seller_enterprise_name": e.seller_enterprise.name if e.seller_enterprise else "",
            "buyer_enterprise_name": e.buyer_enterprise.name if e.buyer_enterprise else "",
            "source_transaction_id": e.source_transaction_id,
            "seller_record_id": e.seller_record_id,
            "buyer_record_id": e.buyer_record_id,
            "gross_amount": e.gross_amount,
            "elimination_amount": e.elimination_amount,
            "remark": e.remark,
        })

    base = {
        "id": version.id,
        "group_filing_id": version.group_filing_id,
        "version_no": version.version_no,
        "status": version.status,
        "change_reason": version.change_reason,
        "member_count": version.member_count,
        "members_aggregate_positive": version.members_aggregate_positive,
        "members_aggregate_negative": version.members_aggregate_negative,
        "members_aggregate_net": version.members_aggregate_net,
        "members_aggregate_gap": version.members_aggregate_gap,
        "members_aggregate_surplus": version.members_aggregate_surplus,
        "members_carryover_in": version.members_carryover_in,
        "members_carryover_out": version.members_carryover_out,
        "members_bought": version.members_bought,
        "members_sold": version.members_sold,
        "internal_gross": version.internal_gross,
        "elimination_total": version.elimination_total,
        "consolidated_positive": version.consolidated_positive,
        "consolidated_negative": version.consolidated_negative,
        "consolidated_net": version.consolidated_net,
        "consolidated_carryover_in": version.consolidated_carryover_in,
        "consolidated_carryover_out": version.consolidated_carryover_out,
        "external_bought": version.external_bought,
        "external_sold": version.external_sold,
        "consolidated_final_net": version.consolidated_final_net,
        "consolidated_gap": version.consolidated_gap,
        "consolidated_surplus": version.consolidated_surplus,
        "is_compliant": version.is_compliant,
        "member_diff_json": version.member_diff_json,
        "amount_diff_json": version.amount_diff_json,
        "regulatory_conclusion": version.regulatory_conclusion,
        "created_at": version.created_at,
        "members": members,
        "eliminations": eliminations,
    }
    base["reconciliation"] = group_crud.get_version_reconciliation(db, version)
    return base
