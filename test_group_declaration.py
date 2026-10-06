import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import crud, crud_group, schemas
from app.models import (
    CarryoverStatus,
    ConsolidationStatus,
    CreditRecordStatus,
    DeclarationStatus,
)


TEST_DATABASE_URL = "sqlite:///:memory:"
YEAR = datetime.now().year


@pytest.fixture(scope="function")
def db():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


class GroupScenario:
    """集团申报测试场景：A正积分、B负积分、C集团外企业、D迟交成员"""

    def __init__(self, db):
        self.db = db
        self.ent_a = crud.create_enterprise(db, schemas.EnterpriseCreate(
            name="集团成员A-正积分", short_name="成员A", credit_code="GRP-A"))
        self.ent_b = crud.create_enterprise(db, schemas.EnterpriseCreate(
            name="集团成员B-负积分", short_name="成员B", credit_code="GRP-B"))
        self.ent_c = crud.create_enterprise(db, schemas.EnterpriseCreate(
            name="集团外企业C", short_name="外部C", credit_code="GRP-C"))
        self.ent_d = crud.create_enterprise(db, schemas.EnterpriseCreate(
            name="集团成员D-迟交", short_name="成员D", credit_code="GRP-D"))

        # A: 限值10.5 电耗8.0 → 单车0.5952 × 1000 = 595.2 正积分
        model_a = crud.create_vehicle_model(db, schemas.VehicleModelCreate(
            enterprise_id=self.ent_a.id, model_name="A1", model_code="GRP-A1",
            curb_weight=1000.0, power_consumption=8.0, range=500.0,
            annual_output=1000, production_year=YEAR))
        # B: 限值13.5 电耗15.0 → 单车-0.2778 × 1000 = -277.8 负积分
        model_b = crud.create_vehicle_model(db, schemas.VehicleModelCreate(
            enterprise_id=self.ent_b.id, model_name="B1", model_code="GRP-B1",
            curb_weight=1500.0, power_consumption=15.0, range=300.0,
            annual_output=1000, production_year=YEAR))
        # D: 限值11.5 电耗10.0 → 单车0.3261 × 500 = 163.05 正积分
        model_d = crud.create_vehicle_model(db, schemas.VehicleModelCreate(
            enterprise_id=self.ent_d.id, model_name="D1", model_code="GRP-D1",
            curb_weight=1200.0, power_consumption=10.0, range=450.0,
            annual_output=500, production_year=YEAR))

        for model in (model_a, model_b, model_d):
            record = crud.create_credit_record(db, model.id, YEAR)
            crud.update_credit_record_status(db, record.id, CreditRecordStatus.PUBLICIZED)
            crud.update_credit_record_status(db, record.id, CreditRecordStatus.CONFIRMED)

        # 内部交易 A→B 100分；外部交易 C→B 50分（交易日期默认为当前时间，属于YEAR年度）
        self.txn_internal = crud.create_credit_transaction(db, schemas.CreditTransactionCreate(
            from_enterprise_id=self.ent_a.id, to_enterprise_id=self.ent_b.id,
            credit_amount=100.0, unit_price=3000.0, remark="集团内部转让"))
        self.txn_external = crud.create_credit_transaction(db, schemas.CreditTransactionCreate(
            from_enterprise_id=self.ent_c.id, to_enterprise_id=self.ent_b.id,
            credit_amount=50.0, unit_price=3000.0, remark="集团外部购买"))

        # A 的跨年度结转：上年结转入 30 分
        self.carryover = crud.create_credit_carryover(db, schemas.CreditCarryoverCreate(
            enterprise_id=self.ent_a.id, from_year=YEAR - 1, to_year=YEAR,
            original_amount=37.5, carryover_ratio=0.8, carryover_amount=30.0,
            remark="上年结转入"))

        self.group = crud_group.create_group(db, schemas.EnterpriseGroupCreate(
            name="测试汽车集团", group_code="TG001"))
        self.mem_a = crud_group.add_membership(db, self.group.id, schemas.GroupMembershipCreate(
            enterprise_id=self.ent_a.id, effective_from_year=YEAR))
        self.mem_b = crud_group.add_membership(db, self.group.id, schemas.GroupMembershipCreate(
            enterprise_id=self.ent_b.id, effective_from_year=YEAR))
        self.mem_d = crud_group.add_membership(db, self.group.id, schemas.GroupMembershipCreate(
            enterprise_id=self.ent_d.id, effective_from_year=YEAR - 2))

    def seal_ab(self):
        decl_a = crud_group.seal_member_declaration(self.db, self.group.id, schemas.MemberDeclarationCreate(
            enterprise_id=self.ent_a.id, year=YEAR, remark="A封账V1"))
        decl_b = crud_group.seal_member_declaration(self.db, self.group.id, schemas.MemberDeclarationCreate(
            enterprise_id=self.ent_b.id, year=YEAR, remark="B封账V1"))
        return decl_a, decl_b


class TestMemberDeclaration:
    """成员封账版本：提交即封账、快照不可变、更正产生新版本"""

    def test_seal_snapshots_amounts_and_transactions(self, db):
        s = GroupScenario(db)
        decl_a, decl_b = s.seal_ab()

        # A：净积分595.2，内部卖出100，结转转入30 → 最终 595.2+30-100 = 525.2
        assert decl_a.version_no == 1
        assert decl_a.status == DeclarationStatus.SEALED
        assert decl_a.net_credit == 595.2
        assert decl_a.sold_credit == 100.0
        assert decl_a.internal_sold_credit == 100.0
        assert decl_a.external_sold_credit == 0.0
        assert decl_a.carryover_in == 30.0
        assert decl_a.final_net_credit == 525.2
        assert decl_a.credit_surplus == 525.2
        assert decl_a.credit_gap == 0.0
        assert decl_a.is_compliant is True

        # B：净积分-277.8，买入150（内部100+外部50）→ 最终 -277.8+150 = -127.8
        assert decl_b.net_credit == -277.8
        assert decl_b.bought_credit == 150.0
        assert decl_b.internal_bought_credit == 100.0
        assert decl_b.external_bought_credit == 50.0
        assert decl_b.final_net_credit == -127.8
        assert decl_b.credit_gap == 127.8
        assert decl_b.is_compliant is False

        # 双方原始交易记录都进入各自封账快照
        txn_snaps_a = [t for t in decl_a.transactions]
        txn_snaps_b = [t for t in decl_b.transactions]
        assert len(txn_snaps_a) == 1
        assert txn_snaps_a[0].transaction_id == s.txn_internal.id
        assert txn_snaps_a[0].direction == "sell"
        assert txn_snaps_a[0].is_internal is True
        assert len(txn_snaps_b) == 2
        snap_internal_b = [t for t in txn_snaps_b if t.transaction_id == s.txn_internal.id][0]
        snap_external_b = [t for t in txn_snaps_b if t.transaction_id == s.txn_external.id][0]
        assert snap_internal_b.direction == "buy" and snap_internal_b.is_internal is True
        assert snap_external_b.direction == "buy" and snap_external_b.is_internal is False

    def test_seal_requires_effective_membership(self, db):
        s = GroupScenario(db)
        # 集团外企业C不能提交封账申报
        with pytest.raises(ValueError, match="不是集团"):
            crud_group.seal_member_declaration(db, s.group.id, schemas.MemberDeclarationCreate(
                enterprise_id=s.ent_c.id, year=YEAR))
        # 成员A不能提交生效区间之外年度的封账申报（A自YEAR年起生效）
        with pytest.raises(ValueError, match="不是集团"):
            crud_group.seal_member_declaration(db, s.group.id, schemas.MemberDeclarationCreate(
                enterprise_id=s.ent_a.id, year=YEAR - 5))

    def test_correction_creates_new_version_without_rewriting(self, db):
        s = GroupScenario(db)
        decl_a_v1, _ = s.seal_ab()

        # 更正申报：A 重新封账（期间又发生一笔内部转让 A→B 20分）
        crud.create_credit_transaction(db, schemas.CreditTransactionCreate(
            from_enterprise_id=s.ent_a.id, to_enterprise_id=s.ent_b.id,
            credit_amount=20.0, unit_price=3000.0, remark="补充内部转让"))
        decl_a_v2 = crud_group.seal_member_declaration(db, s.group.id, schemas.MemberDeclarationCreate(
            enterprise_id=s.ent_a.id, year=YEAR, remark="A更正封账V2"))

        assert decl_a_v2.version_no == 2
        assert decl_a_v2.status == DeclarationStatus.SEALED
        assert decl_a_v2.sold_credit == 120.0
        assert decl_a_v2.final_net_credit == 505.2

        # 旧版本保留且内容不改写，仅状态置为 superseded
        db.refresh(decl_a_v1)
        assert decl_a_v1.status == DeclarationStatus.SUPERSEDED
        assert decl_a_v1.sold_credit == 100.0
        assert decl_a_v1.final_net_credit == 525.2

        latest = crud_group.get_latest_declaration(db, s.group.id, s.ent_a.id, YEAR)
        assert latest.id == decl_a_v2.id


class TestMembership:
    """集团成员生效区间"""

    def test_overlap_rejected_within_and_across_groups(self, db):
        s = GroupScenario(db)
        # 同一集团内区间重叠
        with pytest.raises(ValueError, match="不得重叠"):
            crud_group.add_membership(db, s.group.id, schemas.GroupMembershipCreate(
                enterprise_id=s.ent_a.id, effective_from_year=YEAR - 1))
        # 跨集团区间重叠
        group2 = crud_group.create_group(db, schemas.EnterpriseGroupCreate(
            name="另一集团", group_code="TG002"))
        with pytest.raises(ValueError, match="不得重叠"):
            crud_group.add_membership(db, group2.id, schemas.GroupMembershipCreate(
                enterprise_id=s.ent_a.id, effective_from_year=YEAR))
        # 不重叠的区间可以加入（A 在另一集团的过去年度）
        membership = crud_group.add_membership(db, group2.id, schemas.GroupMembershipCreate(
            enterprise_id=s.ent_a.id,
            effective_from_year=YEAR - 5, effective_to_year=YEAR - 3))
        assert membership.effective_to_year == YEAR - 3

    def test_invalid_interval_rejected(self, db):
        s = GroupScenario(db)
        with pytest.raises(ValueError, match="截止年度不能早于起始年度"):
            crud_group.add_membership(db, s.group.id, schemas.GroupMembershipCreate(
                enterprise_id=s.ent_c.id,
                effective_from_year=YEAR, effective_to_year=YEAR - 1))
        with pytest.raises(ValueError, match="截止年度不能早于起始年度"):
            crud_group.update_membership(
                db, s.group.id, s.mem_a.id,
                schemas.GroupMembershipUpdate(effective_to_year=YEAR - 1))

    def test_exit_updates_effective_interval(self, db):
        s = GroupScenario(db)
        # D 退出集团：生效区间截止于上年
        updated = crud_group.update_membership(
            db, s.group.id, s.mem_d.id,
            schemas.GroupMembershipUpdate(effective_to_year=YEAR - 1, remark="退出集团"))
        assert updated.effective_to_year == YEAR - 1
        effective = crud_group.get_effective_memberships(db, s.group.id, YEAR)
        assert s.ent_d.id not in {m.enterprise_id for m in effective}
        # 退出后 D 不能再提交当年封账申报
        with pytest.raises(ValueError, match="不是集团"):
            crud_group.seal_member_declaration(db, s.group.id, schemas.MemberDeclarationCreate(
                enterprise_id=s.ent_d.id, year=YEAR))


class TestGroupConsolidation:
    """集团合并版本：抵销、版本差异、勾稽与监管结论不可改写"""

    def test_consolidation_eliminates_only_internal_transactions(self, db):
        s = GroupScenario(db)
        s.seal_ab()

        v1 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR, remark="首次合并"))

        assert v1.version_no == 1
        assert v1.member_count == 2
        # 当年净积分合计 595.2 - 277.8 = 317.4
        assert v1.net_credit == 317.4
        # 仅抵销内部交易100分；外部交易50分、结转30分不得抵销
        assert v1.eliminated_amount == 100.0
        assert v1.eliminated_internal_bought == 100.0
        assert v1.eliminated_internal_sold == 100.0
        assert v1.external_bought_credit == 50.0
        assert v1.external_sold_credit == 0.0
        assert v1.carryover_in == 30.0
        # 集团最终净积分 = 成员合计 525.2 + (-127.8) = 397.4
        assert v1.final_net_credit == 397.4
        assert v1.credit_surplus == 397.4
        assert v1.credit_gap == 0.0
        assert v1.is_compliant is True

        # 抵销项目只属于本版本，且只包含内部交易
        assert len(v1.eliminations) == 1
        elim = v1.eliminations[0]
        assert elim.transaction_id == s.txn_internal.id
        assert elim.from_enterprise_id == s.ent_a.id
        assert elim.to_enterprise_id == s.ent_b.id
        assert elim.eliminated_amount == 100.0
        assert elim.captured_by_from is True and elim.captured_by_to is True

        # 迟交成员D列入差异说明
        summary = json.loads(v1.change_summary)
        assert summary["previous_version"] is None
        assert any(m["enterprise_id"] == s.ent_d.id for m in summary["missing_members"])

        # 抵销后双方原始交易记录完整保留、金额不改写
        original_internal = crud.get_credit_transactions(db, enterprise_id=s.ent_a.id)
        assert any(t.id == s.txn_internal.id and t.credit_amount == 100.0 for t in original_internal)
        original_external = db.get(type(s.txn_external), s.txn_external.id)
        assert original_external is not None and original_external.credit_amount == 50.0

    def test_reconciliation_passes(self, db):
        s = GroupScenario(db)
        s.seal_ab()
        v1 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR))

        report = crud_group.get_reconciliation(db, s.group.id, v1.id)
        assert report["all_passed"] is True
        assert report["non_compliant_members"] == 1
        assert report["group_level"]["final_net_credit"] == 397.4
        assert report["member_sums"]["final_net_credit"] == 397.4
        check_names = [c["name"] for c in report["checks"]]
        assert any("结转" in n for n in check_names)
        assert any("原始交易记录" in n for n in check_names)

    def test_late_submission_forms_new_version_with_diff(self, db):
        s = GroupScenario(db)
        s.seal_ab()
        v1 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR))

        # D 迟交补报
        crud_group.seal_member_declaration(db, s.group.id, schemas.MemberDeclarationCreate(
            enterprise_id=s.ent_d.id, year=YEAR, remark="D迟交封账"))
        v2 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR, reason="late_submission"))

        assert v2.version_no == 2
        assert v2.previous_version_id == v1.id
        assert v2.member_count == 3
        # 集团最终净积分 397.4 + 163.05 = 560.45
        assert v2.final_net_credit == 560.45

        summary = json.loads(v2.change_summary)
        assert summary["reason"] == "late_submission"
        assert [m["enterprise_id"] for m in summary["members_added"]] == [s.ent_d.id]
        assert summary["members_removed"] == []
        assert summary["amount_changes"]["final_net_credit"]["previous"] == 397.4
        assert summary["amount_changes"]["final_net_credit"]["current"] == 560.45
        assert summary["amount_changes"]["final_net_credit"]["change"] == 163.05
        assert "新增成员" in summary["summary_text"]

    def test_correction_forms_new_version_and_keeps_adopted_conclusion(self, db):
        s = GroupScenario(db)
        s.seal_ab()
        v1 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR))
        crud_group.adopt_consolidation(db, s.group.id, v1.id)

        # 成员更正申报：新增内部转让 A→B 20分后双方重新封账
        txn_extra = crud.create_credit_transaction(db, schemas.CreditTransactionCreate(
            from_enterprise_id=s.ent_a.id, to_enterprise_id=s.ent_b.id,
            credit_amount=20.0, unit_price=3000.0, remark="补充内部转让"))
        crud_group.seal_member_declaration(db, s.group.id, schemas.MemberDeclarationCreate(
            enterprise_id=s.ent_a.id, year=YEAR, remark="A更正V2"))
        crud_group.seal_member_declaration(db, s.group.id, schemas.MemberDeclarationCreate(
            enterprise_id=s.ent_b.id, year=YEAR, remark="B更正V2"))

        v2 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR, reason="correction"))

        # 内部转让在集团层面自平衡：抵销增加20，集团最终净积分不变
        assert v2.eliminated_amount == 120.0
        assert v2.external_bought_credit == 50.0
        assert v2.final_net_credit == 397.4
        assert {e.transaction_id for e in v2.eliminations} == {s.txn_internal.id, txn_extra.id}

        summary = json.loads(v2.change_summary)
        assert summary["reason"] == "correction"
        changed = {m["enterprise_id"]: m for m in summary["members_version_changed"]}
        assert changed[s.ent_a.id]["from_declaration_version"] == 1
        assert changed[s.ent_a.id]["to_declaration_version"] == 2
        assert changed[s.ent_b.id]["to_declaration_version"] == 2
        assert summary["amount_changes"]["eliminated_amount"]["change"] == 20.0
        assert summary["amount_changes"]["final_net_credit"]["change"] == 0.0

        # 已采用的V1监管结论不被改写
        db.refresh(v1)
        assert v1.status == ConsolidationStatus.ADOPTED
        assert v1.eliminated_amount == 100.0
        assert v1.final_net_credit == 397.4
        assert len(v1.eliminations) == 1

        # 采用V2后，V1转为历史（内容仍不改写），V2成为当前监管结论
        crud_group.adopt_consolidation(db, s.group.id, v2.id)
        db.refresh(v1)
        db.refresh(v2)
        assert v1.status == ConsolidationStatus.SUPERSEDED
        assert v1.eliminated_amount == 100.0
        assert v2.status == ConsolidationStatus.ADOPTED
        assert v2.adopted_at is not None

        with pytest.raises(ValueError, match="已被采用"):
            crud_group.adopt_consolidation(db, s.group.id, v2.id)

    def test_member_exit_forms_new_version_with_removed_member(self, db):
        s = GroupScenario(db)
        s.seal_ab()
        crud_group.seal_member_declaration(db, s.group.id, schemas.MemberDeclarationCreate(
            enterprise_id=s.ent_d.id, year=YEAR))
        v1 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR))
        assert v1.member_count == 3

        # D 退出集团（生效区间截止于上年），形成新合并版本
        crud_group.update_membership(
            db, s.group.id, s.mem_d.id,
            schemas.GroupMembershipUpdate(effective_to_year=YEAR - 1, remark="退出集团"))
        v2 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR, reason="member_exit"))

        assert v2.member_count == 2
        assert v2.final_net_credit == 397.4
        summary = json.loads(v2.change_summary)
        assert summary["reason"] == "member_exit"
        assert [m["enterprise_id"] for m in summary["members_removed"]] == [s.ent_d.id]
        assert summary["amount_changes"]["final_net_credit"]["change"] == -163.05
        assert "移出成员" in summary["summary_text"]

        # 退出后不能再被显式选入合并范围
        with pytest.raises(ValueError, match="不是集团生效成员"):
            crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
                year=YEAR, member_enterprise_ids=[s.ent_a.id, s.ent_d.id]))

    def test_scope_and_declaration_validation(self, db):
        s = GroupScenario(db)
        s.seal_ab()
        # 显式选择未封账成员 → 拒绝
        with pytest.raises(ValueError, match="尚未提交"):
            crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
                year=YEAR, member_enterprise_ids=[s.ent_a.id, s.ent_d.id]))
        # 没有任何封账版本的年度 → 拒绝
        with pytest.raises(ValueError, match="无法生成合并版本"):
            crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
                year=YEAR + 1))
        # 指定其他年度的封账版本 → 拒绝
        decl_a = crud_group.get_latest_declaration(db, s.group.id, s.ent_a.id, YEAR)
        with pytest.raises(ValueError, match="不能用于"):
            crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
                year=YEAR + 1, member_enterprise_ids=[s.ent_a.id],
                declaration_ids=[decl_a.id]))

    def test_explicit_scope_and_pinned_declaration_version(self, db):
        s = GroupScenario(db)
        decl_a_v1, decl_b_v1 = s.seal_ab()
        # A 更正封账产生V2
        crud.create_credit_transaction(db, schemas.CreditTransactionCreate(
            from_enterprise_id=s.ent_a.id, to_enterprise_id=s.ent_b.id,
            credit_amount=20.0, unit_price=3000.0))
        crud_group.seal_member_declaration(db, s.group.id, schemas.MemberDeclarationCreate(
            enterprise_id=s.ent_a.id, year=YEAR, remark="A更正V2"))

        # 集团选择钉住A的V1版本进行合并
        v1 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR, member_enterprise_ids=[s.ent_a.id, s.ent_b.id],
            declaration_ids=[decl_a_v1.id]))
        member_map = {m.enterprise_id: m for m in v1.members}
        assert member_map[s.ent_a.id].declaration_version_no == 1
        assert member_map[s.ent_b.id].declaration_version_no == 1
        # 钉住V1时A只卖出100 → 抵销100
        assert v1.eliminated_amount == 100.0

        # 默认取最新版本（A的V2）→ 抵销120
        v2 = crud_group.generate_consolidation(db, s.group.id, schemas.GroupConsolidationGenerate(
            year=YEAR, member_enterprise_ids=[s.ent_a.id, s.ent_b.id]))
        assert v2.eliminated_amount == 120.0


class TestGroupApiSmoke:
    """集团申报接口冒烟测试"""

    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient
        from app.main import app

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()

    def test_full_flow_via_api(self, db, client):
        s = GroupScenario(db)
        prefix = "/api/v1/groups"

        resp = client.get(f"{prefix}/{s.group.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "测试汽车集团"

        resp = client.get(f"{prefix}/{s.group.id}/members", params={"year": YEAR})
        assert resp.status_code == 200
        assert len(resp.json()) == 3

        resp = client.post(f"{prefix}/{s.group.id}/declarations",
                           json={"enterprise_id": s.ent_a.id, "year": YEAR})
        assert resp.status_code == 200
        assert resp.json()["final_net_credit"] == 525.2
        resp = client.post(f"{prefix}/{s.group.id}/declarations",
                           json={"enterprise_id": s.ent_b.id, "year": YEAR})
        assert resp.status_code == 200

        resp = client.post(f"{prefix}/{s.group.id}/consolidations", json={"year": YEAR})
        assert resp.status_code == 200
        consolidation = resp.json()
        assert consolidation["final_net_credit"] == 397.4
        assert consolidation["eliminated_amount"] == 100.0
        assert len(consolidation["eliminations"]) == 1

        cid = consolidation["id"]
        resp = client.get(f"{prefix}/{s.group.id}/consolidations/{cid}/reconciliation")
        assert resp.status_code == 200
        assert resp.json()["all_passed"] is True

        resp = client.post(f"{prefix}/{s.group.id}/consolidations/{cid}/adopt")
        assert resp.status_code == 200
        assert resp.json()["status"] == "adopted"

        # 重复采用 → 400
        resp = client.post(f"{prefix}/{s.group.id}/consolidations/{cid}/adopt")
        assert resp.status_code == 400

        # 集团外企业封账 → 400
        resp = client.post(f"{prefix}/{s.group.id}/declarations",
                           json={"enterprise_id": s.ent_c.id, "year": YEAR})
        assert resp.status_code == 400
