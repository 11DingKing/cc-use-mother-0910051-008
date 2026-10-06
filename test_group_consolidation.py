"""
集团合并申报功能测试：

覆盖需求：
- 带成员生效区间的集团申报；区间不覆盖年度的成员不能纳入合并
- 成员先提交已封账版本（不可变快照，更正产生新版本，旧版本保留）
- 集团选择合并范围并生成只属于该版本的抵销项目
- 内部车型/积分转让重复计算被抵销；外部交易、跨年度结转不被误抵销
- 迟交、退出、更正形成新合并版本，并给出与前版的成员及金额差异
- 已采用(冻结)版本的监管结论不被改写
- 抵销后双方原始记录保留
- 集团与成员层级余额、缺口、合规状态相互勾稽
"""
import json
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import crud, schemas, group_crud, models
from app.models import (
    CreditRecordStatus,
    MembershipStatus,
    MemberFilingStatus,
    GroupFilingVersionStatus,
)


@pytest.fixture(scope="function")
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


YEAR = 2025


# --------------------------- 测试数据辅助函数 ---------------------------

def make_enterprise(db, name, code):
    return crud.create_enterprise(
        db, schemas.EnterpriseCreate(name=name, credit_code=code)
    )


def make_model(db, ent, code, power_consumption, output, curb_weight=1000.0):
    return crud.create_vehicle_model(db, schemas.VehicleModelCreate(
        enterprise_id=ent.id,
        model_name=f"车型{code}",
        model_code=code,
        curb_weight=curb_weight,
        power_consumption=power_consumption,
        range=400.0,
        annual_output=output,
        production_year=YEAR,
    ))


def confirm_record(db, model, year=YEAR):
    record = crud.create_credit_record(db, model.id, year)
    crud.update_credit_record_status(db, record.id, CreditRecordStatus.PUBLICIZED)
    crud.update_credit_record_status(db, record.id, CreditRecordStatus.CONFIRMED)
    return record


def make_transaction(db, from_id, to_id, amount, txn_date=None):
    txn = models.CreditTransaction(
        transaction_no=crud.generate_transaction_no(db),
        from_enterprise_id=from_id,
        to_enterprise_id=to_id,
        credit_amount=amount,
        unit_price=3000.0,
        total_amount=amount * 3000.0,
        transaction_date=txn_date or datetime(YEAR, 6, 1),
        status="completed",
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def setup_group_with_members(db, enterprises, from_dates=None):
    group = group_crud.create_group(
        db, schemas.EnterpriseGroupCreate(name="测试汽车集团", credit_code="GRP001")
    )
    from_dates = from_dates or {}
    for ent in enterprises:
        group_crud.add_membership(db, group.id, schemas.GroupMembershipCreate(
            enterprise_id=ent.id,
            effective_from=from_dates.get(ent.id, date(YEAR, 1, 1)),
        ))
    return group


def consolidate(db, group, enterprise_ids, reason=None, lock=False, filing_ids=None):
    filing_ids = filing_ids or {}
    return group_crud.create_group_consolidation_version(
        db,
        schemas.GroupConsolidationCreateRequest(
            group_id=group.id,
            year=YEAR,
            members=[
                schemas.GroupConsolidationMemberRequest(
                    enterprise_id=eid, member_filing_id=filing_ids.get(eid)
                )
                for eid in enterprise_ids
            ],
            change_reason=reason,
            lock_after_create=lock,
        ),
    )


# --------------------------- 成员与生效区间 ---------------------------

class TestMembership:

    def test_membership_effective_range(self, db):
        a = make_enterprise(db, "企业A", "EA")
        group = group_crud.create_group(
            db, schemas.EnterpriseGroupCreate(name="区间集团")
        )
        m = group_crud.add_membership(db, group.id, schemas.GroupMembershipCreate(
            enterprise_id=a.id, effective_from=date(YEAR, 3, 1)))
        assert m.status == MembershipStatus.ACTIVE
        assert m.effective_to is None

        rows = group_crud.list_memberships(db, group.id, on_date=date(YEAR, 2, 1))
        assert rows == []
        rows = group_crud.list_memberships(db, group.id, on_date=date(YEAR, 6, 1))
        assert len(rows) == 1 and rows[0]["enterprise_id"] == a.id

    def test_exit_sets_effective_to(self, db):
        a = make_enterprise(db, "企业A", "EA")
        group = setup_group_with_members(db, [a])
        exited = group_crud.exit_membership(
            db, group.id, a.id,
            schemas.GroupMembershipExit(effective_to=date(2026, 1, 1)),
        )
        assert exited.status == MembershipStatus.EXITED
        rows = group_crud.list_memberships(db, group.id, on_date=date(2026, 6, 1))
        assert rows == []

    def test_duplicate_membership_rejected(self, db):
        a = make_enterprise(db, "企业A", "EA")
        group = setup_group_with_members(db, [a])
        with pytest.raises(ValueError):
            group_crud.add_membership(db, group.id, schemas.GroupMembershipCreate(
                enterprise_id=a.id, effective_from=date(YEAR, 1, 1)))

    def test_member_out_of_year_range_cannot_consolidate(self, db):
        a = make_enterprise(db, "年中后才加入企业", "EA")
        group = group_crud.create_group(
            db, schemas.EnterpriseGroupCreate(name="区间外集团"))
        group_crud.add_membership(db, group.id, schemas.GroupMembershipCreate(
            enterprise_id=a.id, effective_from=date(2026, 1, 1)))
        with pytest.raises(ValueError, match="生效区间"):
            consolidate(db, group, [a.id])


# --------------------------- 成员封账 ---------------------------

class TestMemberFiling:

    def test_seal_requires_confirmed_records(self, db):
        a = make_enterprise(db, "无确认企业", "EA")
        make_model(db, a, "M1", 8.0, 100)  # 仅核算未确认
        with pytest.raises(ValueError, match="已确认"):
            group_crud.seal_member_filing(db, a.id, YEAR)

    def test_seal_creates_immutable_snapshot(self, db):
        a = make_enterprise(db, "封账企业", "EA")
        m = make_model(db, a, "M1", 8.0, 100)
        r = confirm_record(db, m)
        filing = group_crud.seal_member_filing(db, a.id, YEAR)

        snapshot = json.loads(filing.record_snapshot)
        assert len(snapshot) == 1 and snapshot[0]["id"] == r.id
        assert filing.net_credit == r.total_credit
        assert filing.status == MemberFilingStatus.SEALED

    def test_reseal_marks_prior_superseded_but_keeps_it(self, db):
        a = make_enterprise(db, "更正企业", "EA")
        confirm_record(db, make_model(db, a, "M1", 8.0, 100))
        f1 = group_crud.seal_member_filing(db, a.id, YEAR)

        # 成员更正：新增已确认车型后重新封账
        confirm_record(db, make_model(db, a, "M2", 9.0, 50))
        f2 = group_crud.seal_member_filing(db, a.id, YEAR, remark="补报车型M2")

        db.refresh(f1)
        assert f2.version_no == 2
        assert f1.status == MemberFilingStatus.SUPERSEDED
        assert f1.superseded_by_filing_id == f2.id
        # 旧版本快照不被改写
        assert len(json.loads(f1.record_snapshot)) == 1
        assert len(json.loads(f2.record_snapshot)) == 2
        assert f2.net_credit > f1.net_credit


# --------------------------- 合并、抵销与勾稽 ---------------------------

class TestConsolidation:

    def _three_members(self, db):
        """A 正积分、B 负积分(缺口)、C 正积分(迟交)，X 为集团外企业。"""
        a = make_enterprise(db, "成员A", "EA")
        b = make_enterprise(db, "成员B", "EB")
        c = make_enterprise(db, "成员C", "EC")
        x = make_enterprise(db, "集团外X", "EX")
        ra = confirm_record(db, make_model(db, a, "MA", 8.0, 1000))
        confirm_record(db, make_model(db, b, "MB", 18.0, 300, curb_weight=1500.0))
        rc = confirm_record(db, make_model(db, c, "MC", 8.5, 400))
        return a, b, c, x, ra, rc

    def test_consolidation_requires_sealed_filings(self, db):
        a, b, *_ = self._three_members(db)
        group = setup_group_with_members(db, [a, b])
        with pytest.raises(ValueError, match="封账版本"):
            consolidate(db, group, [a.id, b.id])

    def test_duplicate_member_in_scope_rejected(self, db):
        a, *_ = self._three_members(db)
        group = setup_group_with_members(db, [a])
        group_crud.seal_member_filing(db, a.id, YEAR)
        with pytest.raises(ValueError, match="多次"):
            group_crud.create_group_consolidation_version(
                db,
                schemas.GroupConsolidationCreateRequest(
                    group_id=group.id, year=YEAR,
                    members=[
                        schemas.GroupConsolidationMemberRequest(enterprise_id=a.id),
                        schemas.GroupConsolidationMemberRequest(enterprise_id=a.id),
                    ],
                ),
            )

    def test_internal_transfer_eliminated_external_kept(self, db):
        a, b, c, x, ra, rc = self._three_members(db)
        # 内部积分转让 A→B 100，外部交易 X→B 50
        make_transaction(db, a.id, b.id, 100)
        make_transaction(db, x.id, b.id, 50)
        # 内部车型转让 A↔C 重复申报 30（此时 C 尚未封账）
        group_crud.register_internal_model_transfer(
            db, schemas.InternalModelTransferCreate(
                year=YEAR, seller_enterprise_id=a.id, buyer_enterprise_id=c.id,
                model_name="共有车型", seller_record_id=ra.id, buyer_record_id=rc.id,
                duplicated_credit=30,
            ))

        fa = group_crud.seal_member_filing(db, a.id, YEAR)
        fb = group_crud.seal_member_filing(db, b.id, YEAR)
        group = setup_group_with_members(db, [a, b, c])

        v1 = consolidate(db, group, [a.id, b.id], reason="首次合并，C迟交")

        elim_types = {(e.entry_type, e.elimination_amount) for e in v1.eliminations}
        assert ("credit_transfer", 100.0) in elim_types
        # C 未封账，车型转让本版不抵销
        assert all(e.entry_type != "model_transfer" for e in v1.eliminations)

        # 外部交易保留：成员B买入150 = 内部抵销100 + 对外买入50
        assert v1.external_bought == 50.0
        assert v1.members_bought == 150.0
        # 积分转让是零和内部流，不改变合并净积分
        assert v1.consolidated_net == round(fa.net_credit + fb.net_credit, 2)

        rec = group_crud.get_version_reconciliation(db, v1)
        assert rec["all_balanced"] is True
        assert rec["external_balanced"] and rec["net_balanced"]
        assert rec["raw_records_preserved"] is True

    def test_model_transfer_eliminated_after_late_member_seals(self, db):
        a, b, c, x, ra, rc = self._three_members(db)
        group_crud.register_internal_model_transfer(
            db, schemas.InternalModelTransferCreate(
                year=YEAR, seller_enterprise_id=a.id, buyer_enterprise_id=c.id,
                model_name="共有车型", seller_record_id=ra.id, buyer_record_id=rc.id,
                duplicated_credit=30,
            ))
        fa = group_crud.seal_member_filing(db, a.id, YEAR)
        fc = group_crud.seal_member_filing(db, c.id, YEAR)
        group = setup_group_with_members(db, [a, c])

        v = consolidate(db, group, [a.id, c.id])
        model_elim = [e for e in v.eliminations if e.entry_type == "model_transfer"]
        assert len(model_elim) == 1 and model_elim[0].elimination_amount == 30.0

        # 车型重复申报冲减生产口径正积分
        assert v.consolidated_positive == round(
            fa.total_positive_credit + fc.total_positive_credit - 30.0, 2)
        assert v.consolidated_net == round(fa.net_credit + fc.net_credit - 30.0, 2)
        assert group_crud.get_version_reconciliation(db, v)["all_balanced"] is True

    def test_cross_year_carryover_not_eliminated(self, db):
        a, b, c, x, ra, rc = self._three_members(db)
        # 直接登记一笔经批准的跨年度结转（2024→2025，结转入40）
        carry = models.CreditCarryover(
            carryover_no=crud.generate_carryover_no(db),
            enterprise_id=a.id, from_year=2024, to_year=YEAR,
            original_amount=50, carryover_ratio=0.8, carryover_amount=40,
            used_amount=0.0, remaining_amount=40.0,
            status=models.CarryoverStatus.APPROVED,
        )
        db.add(carry)
        db.commit()

        group_crud.seal_member_filing(db, a.id, YEAR)
        group = setup_group_with_members(db, [a])
        v = consolidate(db, group, [a.id])

        # 结转原样进入合并口径，不产生任何抵销
        assert v.eliminations == []
        assert v.members_carryover_in == 40.0
        assert v.consolidated_carryover_in == 40.0
        rec = group_crud.get_version_reconciliation(db, v)
        assert rec["carryover_balanced"] is True
        assert rec["all_balanced"] is True

    def test_original_records_remain_after_elimination(self, db):
        a, b, c, x, ra, rb_ = self._three_members(db)
        make_transaction(db, a.id, b.id, 100)
        fa = group_crud.seal_member_filing(db, a.id, YEAR)
        fb = group_crud.seal_member_filing(db, b.id, YEAR)
        group = setup_group_with_members(db, [a, b])
        v = consolidate(db, group, [a.id, b.id])

        # 合并层有抵销，成员封账快照中原始积分与交易记录均保留
        assert len(v.eliminations) == 1
        assert len(json.loads(fa.record_snapshot)) == 1
        assert len(json.loads(fb.record_snapshot)) == 1
        assert len(json.loads(fa.transaction_snapshot)) == 1
        assert len(json.loads(fb.transaction_snapshot)) == 1
        # 底层原始交易记录也仍在
        assert db.query(models.CreditTransaction).count() == 1

    def test_eliminations_belong_to_a_specific_version(self, db):
        a, b, c, x, ra, rc = self._three_members(db)
        make_transaction(db, a.id, b.id, 100)
        group_crud.seal_member_filing(db, a.id, YEAR)
        group_crud.seal_member_filing(db, b.id, YEAR)
        group_crud.seal_member_filing(db, c.id, YEAR)
        group = setup_group_with_members(db, [a, b, c])

        v1 = consolidate(db, group, [a.id, b.id])
        v2 = consolidate(db, group, [a.id, b.id, c.id], reason="纳入C")
        # 各版本持有各自独立的抵销项目
        v1_elim_ids = {e.id for e in v1.eliminations}
        v2_elim_ids = {e.id for e in v2.eliminations}
        assert v1_elim_ids and v1_elim_ids.isdisjoint(v2_elim_ids)
        assert all(e.version_id == v1.id for e in v1.eliminations)
        assert all(e.version_id == v2.id for e in v2.eliminations)


# --------------------------- 版本链：迟交/退出/更正/冻结 ---------------------------

class TestVersionLifecycle:

    def _setup(self, db):
        a = make_enterprise(db, "成员A", "EA")
        b = make_enterprise(db, "成员B", "EB")
        c = make_enterprise(db, "成员C", "EC")
        make_model(db, a, "MA", 8.0, 1000)
        make_model(db, b, "MB", 18.0, 300, curb_weight=1500.0)
        make_model(db, c, "MC", 8.5, 400)
        for ent in (a, b, c):
            for m in crud.get_vehicle_models(db, enterprise_id=ent.id):
                confirm_record(db, m)
        return a, b, c

    def test_late_filer_creates_new_version_with_added_diff(self, db):
        a, b, c = self._setup(db)
        group_crud.seal_member_filing(db, a.id, YEAR)
        group_crud.seal_member_filing(db, b.id, YEAR)
        group = setup_group_with_members(db, [a, b, c])

        v1 = consolidate(db, group, [a.id, b.id], reason="C迟交")
        group_crud.seal_member_filing(db, c.id, YEAR)
        v2 = consolidate(db, group, [a.id, b.id, c.id], reason="C补报")

        assert v1.version_no == 1 and v2.version_no == 2
        diff = json.loads(v2.member_diff_json)
        added = diff["added"]
        assert len(added) == 1 and added[0]["enterprise_id"] == c.id
        assert diff["member_count_delta"] == 1
        amount_diff = json.loads(v2.amount_diff_json)
        assert amount_diff["prior_version_no"] == 1
        assert "members_aggregate_net" in amount_diff["changed_items"]

    def test_member_exit_creates_removed_diff_and_rescopes_eliminations(self, db):
        a, b, c = self._setup(db)
        make_transaction(db, a.id, b.id, 100)
        for ent in (a, b, c):
            group_crud.seal_member_filing(db, ent.id, YEAR)
        group = setup_group_with_members(db, [a, b, c])

        v1 = consolidate(db, group, [a.id, b.id, c.id])
        assert any(e.buyer_enterprise_id == b.id for e in v1.eliminations)

        group_crud.exit_membership(
            db, group.id, b.id,
            schemas.GroupMembershipExit(effective_to=date(2026, 1, 1)),
        )
        v2 = consolidate(db, group, [a.id, c.id], reason="B退出集团")
        diff = json.loads(v2.member_diff_json)
        assert len(diff["removed"]) == 1 and diff["removed"][0]["enterprise_id"] == b.id

        # B 退出后，涉及其的内部交易不再抵销；退出成员以 included=False 留痕
        assert all(
            e.seller_enterprise_id != b.id and e.buyer_enterprise_id != b.id
            for e in v2.eliminations
        )
        removed_rows = [m for m in v2.member_selections if not m.included]
        assert len(removed_rows) == 1 and removed_rows[0].enterprise_id == b.id
        assert group_crud.get_version_reconciliation(db, v2)["all_balanced"] is True

    def test_member_correction_creates_corrected_diff(self, db):
        a, b, c = self._setup(db)
        f1 = group_crud.seal_member_filing(db, a.id, YEAR)
        group = setup_group_with_members(db, [a])
        v1 = consolidate(db, group, [a.id])

        # A 更正申报：补报新车型并重新封账
        confirm_record(db, make_model(db, a, "MA2", 9.0, 200))
        f2 = group_crud.seal_member_filing(db, a.id, YEAR, remark="补报MA2")
        v2 = consolidate(db, group, [a.id], reason="A更正申报")

        diff = json.loads(v2.member_diff_json)
        corrected = diff["corrected"]
        assert len(corrected) == 1
        assert corrected[0]["member_filing_id"] == f2.id
        assert corrected[0]["prior_member_filing_id"] == f1.id
        assert corrected[0]["net_credit_delta"] == round(f2.net_credit - f1.net_credit, 2)
        # v1 数字原样保留
        assert v1.members_aggregate_net == f1.net_credit
        assert v2.members_aggregate_net == f2.net_credit

    def test_locked_version_conclusion_never_rewritten(self, db):
        a, b, c = self._setup(db)
        for ent in (a, b):
            group_crud.seal_member_filing(db, ent.id, YEAR)
        group = setup_group_with_members(db, [a, b, c])
        v1 = consolidate(db, group, [a.id, b.id], lock=True, reason="首版直接采用")

        locked_conclusion = v1.regulatory_conclusion
        locked_net = v1.consolidated_net
        assert v1.status == GroupFilingVersionStatus.LOCKED

        # 迟交产生 v2
        group_crud.seal_member_filing(db, c.id, YEAR)
        v2 = consolidate(db, group, [a.id, b.id, c.id], reason="C补报")

        db.refresh(v1)
        assert v1.status == GroupFilingVersionStatus.LOCKED
        assert v1.regulatory_conclusion == locked_conclusion
        assert v1.consolidated_net == locked_net
        assert v1.member_count == 2

        # 冻结版本不能再次冻结或修改
        with pytest.raises(ValueError, match="冻结"):
            group_crud.lock_group_version(db, v1.id)

        # 未冻结的前序版本在新版本生成后标记为 amended
        assert v2.status == GroupFilingVersionStatus.SUBMITTED

    def test_submitted_prior_version_marked_amended(self, db):
        a, b, c = self._setup(db)
        group_crud.seal_member_filing(db, a.id, YEAR)
        group = setup_group_with_members(db, [a])
        v1 = consolidate(db, group, [a.id])
        assert v1.status == GroupFilingVersionStatus.SUBMITTED
        v2 = consolidate(db, group, [a.id], reason="重报")
        db.refresh(v1)
        assert v1.status == GroupFilingVersionStatus.AMENDED
        assert v2.status == GroupFilingVersionStatus.SUBMITTED
        with pytest.raises(ValueError, match="替代"):
            group_crud.lock_group_version(db, v1.id)

    def test_compliance_state_reconciles_across_levels(self, db):
        """成员缺口经内部转让抵销后，集团合规状态与合并缺口勾稽一致。"""
        a, b, c = self._setup(db)
        make_transaction(db, a.id, b.id, 500, txn_date=datetime(YEAR, 6, 1))
        fa = group_crud.seal_member_filing(db, a.id, YEAR)
        fb = group_crud.seal_member_filing(db, b.id, YEAR)
        group = setup_group_with_members(db, [a, b])
        v = consolidate(db, group, [a.id, b.id])
        rec = group_crud.get_version_reconciliation(db, v)

        # B 自身可能未达标，但合并层余额、缺口、合规状态必须自洽
        assert rec["all_balanced"] is True
        assert v.is_compliant == (v.consolidated_gap == 0.0)
        # 成员明细中保留各自独立的合规状态，不被集团结论覆盖
        statuses = {d["enterprise_id"]: d["is_compliant"] for d in rec["member_details"]}
        assert statuses[fa.enterprise_id] == fa.is_compliant
        assert statuses[fb.enterprise_id] == fb.is_compliant


# --------------------------- HTTP 接口冒烟 ---------------------------

class TestGroupAPI:

    def test_api_full_flow(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            s = SessionLocal()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            # 建企业与数据
            def new_ent(name):
                return client.post("/api/v1/enterprises/", json={"name": name}).json()["id"]

            def new_model(ent_id, code, pc, out, weight=1000.0):
                return client.post("/api/v1/vehicle-models/", json={
                    "enterprise_id": ent_id, "model_name": f"车型{code}", "model_code": code,
                    "curb_weight": weight, "power_consumption": pc, "range": 400,
                    "annual_output": out, "production_year": YEAR,
                }).json()["id"]

            aid, bid = new_ent("接口成员A"), new_ent("接口成员B")
            for mid in (new_model(aid, "IMA", 8.0, 1000),
                        new_model(bid, "IMB", 18.0, 300, weight=1500.0)):
                client.post(f"/api/v1/credit-records/calculate/model/{mid}",
                            params={"year": YEAR})
            # 批量确认（按年度推进状态）
            client.patch(f"/api/v1/credit-records/year/{YEAR}/status",
                         json={"status": "publicized"})
            client.patch(f"/api/v1/credit-records/year/{YEAR}/status",
                         json={"status": "confirmed"})

            # 集团、成员、封账
            gid = client.post("/api/v1/group-filings/groups",
                              json={"name": "接口测试集团"}).json()["id"]
            for eid in (aid, bid):
                r = client.post(f"/api/v1/group-filings/groups/{gid}/memberships",
                                json={"enterprise_id": eid,
                                      "effective_from": f"{YEAR}-01-01"})
                assert r.status_code == 200, r.text
                r = client.post("/api/v1/group-filings/member-filings/seal",
                                json={"enterprise_id": eid, "year": YEAR})
                assert r.status_code == 200, r.text

            # 合并
            r = client.post("/api/v1/group-filings/consolidation-versions", json={
                "group_id": gid, "year": YEAR,
                "members": [{"enterprise_id": aid}, {"enterprise_id": bid}],
                "change_reason": "接口首次合并",
            })
            assert r.status_code == 200, r.text
            version = r.json()
            vid = version["id"]
            assert version["version_no"] == 1
            assert version["reconciliation"]["all_balanced"] is True

            # 冻结与勾稽查询
            r = client.post(f"/api/v1/group-filings/consolidation-versions/{vid}/lock")
            assert r.status_code == 200
            assert r.json()["status"] == "locked"
            r = client.get(
                f"/api/v1/group-filings/consolidation-versions/{vid}/reconciliation")
            assert r.status_code == 200 and r.json()["all_balanced"] is True

            # 成员清单按日期过滤
            r = client.get(f"/api/v1/group-filings/groups/{gid}/memberships",
                           params={"on_date": "2024-01-01"})
            assert r.status_code == 200 and r.json() == []
        finally:
            app.dependency_overrides.clear()
