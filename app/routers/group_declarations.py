from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from .. import crud_group, schemas
from ..database import get_db

router = APIRouter(prefix="/groups", tags=["groups"])


@router.post("/", response_model=schemas.EnterpriseGroup)
def create_group(group: schemas.EnterpriseGroupCreate, db: Session = Depends(get_db)):
    try:
        return crud_group.create_group(db=db, group=group)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[schemas.EnterpriseGroup])
def read_groups(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud_group.get_groups(db, skip=skip, limit=limit)


@router.get("/{group_id}", response_model=schemas.EnterpriseGroupWithMembers)
def read_group(group_id: int, db: Session = Depends(get_db)):
    group = crud_group.get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="集团不存在")
    return group


@router.post("/{group_id}/members", response_model=schemas.GroupMembership)
def add_member(
    group_id: int,
    membership: schemas.GroupMembershipCreate,
    db: Session = Depends(get_db),
):
    try:
        return crud_group.add_membership(db=db, group_id=group_id, membership=membership)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{group_id}/members", response_model=List[schemas.GroupMembershipWithEnterprise])
def read_members(
    group_id: int,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
):
    if not crud_group.get_group(db, group_id):
        raise HTTPException(status_code=404, detail="集团不存在")
    return crud_group.get_memberships(db, group_id, year=year)


@router.put("/{group_id}/members/{membership_id}", response_model=schemas.GroupMembership)
def update_member(
    group_id: int,
    membership_id: int,
    membership_update: schemas.GroupMembershipUpdate,
    db: Session = Depends(get_db),
):
    try:
        membership = crud_group.update_membership(
            db, group_id=group_id, membership_id=membership_id,
            membership_update=membership_update,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not membership:
        raise HTTPException(status_code=404, detail="集团成员关系不存在")
    return membership


@router.post("/{group_id}/declarations", response_model=schemas.MemberDeclaration)
def seal_declaration(
    group_id: int,
    payload: schemas.MemberDeclarationCreate,
    db: Session = Depends(get_db),
):
    try:
        return crud_group.seal_member_declaration(db=db, group_id=group_id, payload=payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{group_id}/declarations", response_model=List[schemas.MemberDeclaration])
def read_declarations(
    group_id: int,
    year: Optional[int] = None,
    enterprise_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    if not crud_group.get_group(db, group_id):
        raise HTTPException(status_code=404, detail="集团不存在")
    return crud_group.get_declarations(
        db, group_id, year=year, enterprise_id=enterprise_id
    )


@router.get("/{group_id}/declarations/{declaration_id}", response_model=schemas.MemberDeclarationWithDetail)
def read_declaration(group_id: int, declaration_id: int, db: Session = Depends(get_db)):
    declaration = crud_group.get_declaration(db, group_id, declaration_id)
    if not declaration:
        raise HTTPException(status_code=404, detail="成员封账版本不存在")
    return declaration


@router.post("/{group_id}/consolidations", response_model=schemas.GroupConsolidationWithDetail)
def generate_consolidation(
    group_id: int,
    payload: schemas.GroupConsolidationGenerate,
    db: Session = Depends(get_db),
):
    try:
        return crud_group.generate_consolidation(db=db, group_id=group_id, payload=payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{group_id}/consolidations", response_model=List[schemas.GroupConsolidation])
def read_consolidations(
    group_id: int,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
):
    if not crud_group.get_group(db, group_id):
        raise HTTPException(status_code=404, detail="集团不存在")
    return crud_group.get_consolidations(db, group_id, year=year)


@router.get("/{group_id}/consolidations/{consolidation_id}", response_model=schemas.GroupConsolidationWithDetail)
def read_consolidation(group_id: int, consolidation_id: int, db: Session = Depends(get_db)):
    consolidation = crud_group.get_consolidation(db, group_id, consolidation_id)
    if not consolidation:
        raise HTTPException(status_code=404, detail="集团合并版本不存在")
    return consolidation


@router.post("/{group_id}/consolidations/{consolidation_id}/adopt", response_model=schemas.GroupConsolidation)
def adopt_consolidation(group_id: int, consolidation_id: int, db: Session = Depends(get_db)):
    try:
        return crud_group.adopt_consolidation(
            db, group_id=group_id, consolidation_id=consolidation_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{group_id}/consolidations/{consolidation_id}/reconciliation")
def get_reconciliation(group_id: int, consolidation_id: int, db: Session = Depends(get_db)):
    try:
        return crud_group.get_reconciliation(
            db, group_id=group_id, consolidation_id=consolidation_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
