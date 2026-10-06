import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, Boolean, Text, Date, UniqueConstraint
from sqlalchemy.orm import relationship

from .database import Base


class CreditRecordStatus(str, enum.Enum):
    CALCULATED = "calculated"
    PUBLICIZED = "publicized"
    CONFIRMED = "confirmed"


class MembershipStatus(str, enum.Enum):
    ACTIVE = "active"
    EXITED = "exited"


class MemberFilingStatus(str, enum.Enum):
    SEALED = "sealed"
    SUPERSEDED = "superseded"


class GroupFilingVersionStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    LOCKED = "locked"
    AMENDED = "amended"


ENTRY_CREDIT_TRANSFER = "credit_transfer"
ENTRY_MODEL_TRANSFER = "model_transfer"

MEMBER_CHANGE_INITIAL = "initial"
MEMBER_CHANGE_ADDED = "added"
MEMBER_CHANGE_REMOVED = "removed"
MEMBER_CHANGE_UNCHANGED = "unchanged"
MEMBER_CHANGE_CORRECTED = "corrected"


class OrderType(str, enum.Enum):
    SELL = "sell"
    BUY = "buy"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"


class CarryoverStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Enterprise(Base):
    __tablename__ = "enterprises"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    short_name = Column(String(50), unique=True, index=True)
    credit_code = Column(String(50), unique=True, index=True)
    address = Column(String(200))
    contact_person = Column(String(50))
    contact_phone = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle_models = relationship("VehicleModel", back_populates="enterprise")
    credit_transactions_from = relationship(
        "CreditTransaction",
        foreign_keys="CreditTransaction.from_enterprise_id",
        back_populates="from_enterprise"
    )
    credit_transactions_to = relationship(
        "CreditTransaction",
        foreign_keys="CreditTransaction.to_enterprise_id",
        back_populates="to_enterprise"
    )
    credit_orders = relationship(
        "CreditOrder",
        foreign_keys="CreditOrder.enterprise_id",
        back_populates="enterprise"
    )
    credit_carryovers_from = relationship(
        "CreditCarryover",
        foreign_keys="CreditCarryover.enterprise_id",
        back_populates="enterprise"
    )
    group_memberships = relationship(
        "GroupMembership",
        foreign_keys="GroupMembership.enterprise_id",
        back_populates="enterprise"
    )


class VehicleModel(Base):
    __tablename__ = "vehicle_models"

    id = Column(Integer, primary_key=True, index=True)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    model_name = Column(String(100), nullable=False, index=True)
    model_code = Column(String(50), unique=True, nullable=False, index=True)
    curb_weight = Column(Float, nullable=False, comment="整备质量(kg)")
    power_consumption = Column(Float, nullable=False, comment="百公里电耗(kWh/100km)")
    range = Column(Float, nullable=False, comment="续航里程(km)")
    annual_output = Column(Integer, nullable=False, comment="年产量(辆)")
    production_year = Column(Integer, nullable=False, comment="生产年份")
    is_suspected_weight_manipulation = Column(Boolean, default=False, comment="是否疑似堆重量放宽限值")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    enterprise = relationship("Enterprise", back_populates="vehicle_models")
    credit_records = relationship("CreditRecord", back_populates="vehicle_model")


class CreditRecord(Base):
    __tablename__ = "credit_records"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_model_id = Column(Integer, ForeignKey("vehicle_models.id"), nullable=False)
    year = Column(Integer, nullable=False, comment="核算年份")
    power_consumption_limit = Column(Float, nullable=False, comment="电耗限值(kWh/100km)")
    actual_power_consumption = Column(Float, nullable=False, comment="实际电耗(kWh/100km)")
    unit_credit = Column(Float, nullable=False, comment="单车积分(分/辆)")
    total_credit = Column(Float, nullable=False, comment="总积分(分)")
    annual_output = Column(Integer, nullable=False, comment="年产量(辆)")
    status = Column(Enum(CreditRecordStatus), default=CreditRecordStatus.CALCULATED, nullable=False)
    calculated_at = Column(DateTime, default=datetime.utcnow)
    publicized_at = Column(DateTime)
    confirmed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle_model = relationship("VehicleModel", back_populates="credit_records")


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_no = Column(String(50), unique=True, nullable=False, index=True)
    from_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    to_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    sell_order_id = Column(Integer, ForeignKey("credit_orders.id"), comment="卖单ID")
    buy_order_id = Column(Integer, ForeignKey("credit_orders.id"), comment="买单ID")
    credit_amount = Column(Float, nullable=False, comment="交易积分数量")
    unit_price = Column(Float, comment="交易单价(元/分)")
    total_amount = Column(Float, comment="交易总额(元)")
    transaction_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="completed", comment="交易状态")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    from_enterprise = relationship(
        "Enterprise",
        foreign_keys=[from_enterprise_id],
        back_populates="credit_transactions_from"
    )
    to_enterprise = relationship(
        "Enterprise",
        foreign_keys=[to_enterprise_id],
        back_populates="credit_transactions_to"
    )
    sell_order = relationship(
        "CreditOrder",
        foreign_keys=[sell_order_id],
        back_populates="sell_transactions"
    )
    buy_order = relationship(
        "CreditOrder",
        foreign_keys=[buy_order_id],
        back_populates="buy_transactions"
    )


class CreditOrder(Base):
    __tablename__ = "credit_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(50), unique=True, nullable=False, index=True)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    year = Column(Integer, nullable=False, comment="核算年度")
    order_type = Column(Enum(OrderType), nullable=False, comment="订单类型：sell/buy")
    unit_price = Column(Float, nullable=False, comment="报价单价(元/分)")
    total_amount = Column(Float, nullable=False, comment="挂单总积分数量")
    filled_amount = Column(Float, default=0.0, comment="已成交积分数量")
    remaining_amount = Column(Float, nullable=False, comment="剩余积分数量")
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False, comment="订单状态")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, comment="过期时间")

    enterprise = relationship("Enterprise", back_populates="credit_orders")
    sell_transactions = relationship(
        "CreditTransaction",
        foreign_keys="CreditTransaction.sell_order_id",
        back_populates="sell_order"
    )
    buy_transactions = relationship(
        "CreditTransaction",
        foreign_keys="CreditTransaction.buy_order_id",
        back_populates="buy_order"
    )


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False, comment="年度")
    trade_date = Column(DateTime, default=datetime.utcnow, comment="交易日期")
    unit_price = Column(Float, nullable=False, comment="成交单价(元/分)")
    credit_amount = Column(Float, nullable=False, comment="成交积分数量")
    total_amount = Column(Float, nullable=False, comment="成交总额(元)")
    from_enterprise_id = Column(Integer, ForeignKey("enterprises.id"))
    to_enterprise_id = Column(Integer, ForeignKey("enterprises.id"))
    transaction_id = Column(Integer, ForeignKey("credit_transactions.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class CreditCarryover(Base):
    __tablename__ = "credit_carryovers"

    id = Column(Integer, primary_key=True, index=True)
    carryover_no = Column(String(50), unique=True, nullable=False, index=True)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    from_year = Column(Integer, nullable=False, comment="结转来源年度")
    to_year = Column(Integer, nullable=False, comment="结转目标年度")
    original_amount = Column(Float, nullable=False, comment="原始正积分结余")
    carryover_ratio = Column(Float, nullable=False, comment="结转比例")
    carryover_amount = Column(Float, nullable=False, comment="实际结转积分数量")
    used_amount = Column(Float, default=0.0, comment="已使用结转积分数量")
    remaining_amount = Column(Float, nullable=False, comment="剩余结转积分数量")
    status = Column(Enum(CarryoverStatus), default=CarryoverStatus.APPROVED, nullable=False, comment="结转状态")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)

    enterprise = relationship("Enterprise", back_populates="credit_carryovers_from")


class AnnualCreditSummary(Base):
    __tablename__ = "annual_credit_summaries"

    id = Column(Integer, primary_key=True, index=True)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    year = Column(Integer, nullable=False, comment="年度")
    total_positive_credit = Column(Float, default=0.0, comment="当年正积分")
    total_negative_credit = Column(Float, default=0.0, comment="当年负积分")
    net_credit = Column(Float, default=0.0, comment="当年净积分")
    carryover_in = Column(Float, default=0.0, comment="上年结转积分")
    carryover_out = Column(Float, default=0.0, comment="结转下年积分")
    bought_credit = Column(Float, default=0.0, comment="买入积分")
    sold_credit = Column(Float, default=0.0, comment="卖出积分")
    final_net_credit = Column(Float, default=0.0, comment="最终净积分")
    credit_gap = Column(Float, default=0.0, comment="最终积分缺口")
    credit_surplus = Column(Float, default=0.0, comment="最终积分钟余")
    is_compliant = Column(Boolean, default=True, comment="是否达标")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class InternalModelTransfer(Base):
    """
    集团内部车型转让登记（原始业务数据，不属于任何合并版本）。
    记录两个成员企业同一年度就同一车型重复申报、需要在合并时抵销的重叠积分。
    仅当双方都在某合并版本范围内、且对应记录都在各自封账快照中时，才在该版本生成抵销。
    """
    __tablename__ = "internal_model_transfers"

    id = Column(Integer, primary_key=True, index=True)
    transfer_no = Column(String(50), unique=True, nullable=False, index=True)
    year = Column(Integer, nullable=False, comment="转让所属年度")
    seller_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False, comment="让出方(原属企业)")
    buyer_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False, comment="受让方")
    model_name = Column(String(100), nullable=False, comment="转让车型名称")
    seller_record_id = Column(Integer, ForeignKey("credit_records.id"), nullable=True, comment="让出方原始积分记录")
    buyer_record_id = Column(Integer, ForeignKey("credit_records.id"), nullable=True, comment="受让方原始积分记录")
    duplicated_credit = Column(Float, nullable=False, comment="双方重复申报、需抵销的重叠积分(正数)")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    seller_enterprise = relationship("Enterprise", foreign_keys=[seller_enterprise_id])
    buyer_enterprise = relationship("Enterprise", foreign_keys=[buyer_enterprise_id])
    seller_record = relationship("CreditRecord", foreign_keys=[seller_record_id])
    buyer_record = relationship("CreditRecord", foreign_keys=[buyer_record_id])


class EnterpriseGroup(Base):
    """集团（合并申报主体）"""
    __tablename__ = "enterprise_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True, comment="集团名称")
    credit_code = Column(String(50), unique=True, index=True, comment="集团统一社会信用代码")
    contact_person = Column(String(50))
    contact_phone = Column(String(50))
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    memberships = relationship(
        "GroupMembership",
        foreign_keys="GroupMembership.group_id",
        back_populates="group",
        cascade="all, delete-orphan"
    )
    filings = relationship(
        "GroupFiling",
        foreign_keys="GroupFiling.group_id",
        back_populates="group"
    )


class GroupMembership(Base):
    """
    集团成员关系，带生效区间 [effective_from, effective_to)。
    effective_to 为空表示至今仍在集团内；退出时写入退出日期。
    """
    __tablename__ = "group_memberships"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("enterprise_groups.id"), nullable=False)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    effective_from = Column(Date, nullable=False, comment="成员生效日期(含)")
    effective_to = Column(Date, nullable=True, comment="成员退出日期(不含)，空表示至今")
    status = Column(Enum(MembershipStatus), default=MembershipStatus.ACTIVE, nullable=False)
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("group_id", "enterprise_id", name="uq_group_enterprise_membership"),
    )

    group = relationship(
        "EnterpriseGroup",
        foreign_keys=[group_id],
        back_populates="memberships"
    )
    enterprise = relationship(
        "Enterprise",
        foreign_keys=[enterprise_id],
        back_populates="group_memberships"
    )


class MemberFiling(Base):
    """
    成员企业已封账申报版本。封账即对当年度已确认数据做不可变快照，
    集团合并只能引用封账版本；成员更正时另出新封账版本，旧版本保留不被改写。
    """
    __tablename__ = "member_filings"

    id = Column(Integer, primary_key=True, index=True)
    filing_no = Column(String(50), unique=True, nullable=False, index=True)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    year = Column(Integer, nullable=False, comment="申报年度")
    version_no = Column(Integer, nullable=False, comment="企业年度封账版本号，从1递增")
    status = Column(
        Enum(MemberFilingStatus),
        default=MemberFilingStatus.SEALED,
        nullable=False,
        comment="sealed=当前封账版本；superseded=已被更正后的新版本替代"
    )
    superseded_by_filing_id = Column(
        Integer, ForeignKey("member_filings.id"), nullable=True,
        comment="更正后指向新封账版本"
    )
    total_positive_credit = Column(Float, default=0.0, comment="封账时正积分")
    total_negative_credit = Column(Float, default=0.0, comment="封账时负积分")
    net_credit = Column(Float, default=0.0, comment="封账时净积分(生产口径)")
    carryover_in = Column(Float, default=0.0, comment="封账时上年结转")
    carryover_out = Column(Float, default=0.0, comment="封账时结转下年")
    bought_credit = Column(Float, default=0.0, comment="封账时外部买入")
    sold_credit = Column(Float, default=0.0, comment="封账时对外部卖出")
    final_net_credit = Column(Float, default=0.0, comment="封账时最终净积分")
    credit_gap = Column(Float, default=0.0, comment="封账时积分缺口")
    credit_surplus = Column(Float, default=0.0, comment="封账时积分钟余")
    is_compliant = Column(Boolean, default=True, comment="封账时合规状态")
    record_snapshot = Column(Text, nullable=False, comment="已确认积分记录JSON快照")
    transaction_snapshot = Column(Text, nullable=False, comment="年度交易JSON快照")
    carryover_snapshot = Column(Text, nullable=False, comment="跨年度结转JSON快照")
    sealed_at = Column(DateTime, default=datetime.utcnow, comment="封账时间")
    remark = Column(String(500))

    __table_args__ = (
        UniqueConstraint("enterprise_id", "year", "version_no", name="uq_member_filing_version"),
    )

    enterprise = relationship("Enterprise", foreign_keys=[enterprise_id])
    superseded_by = relationship(
        "MemberFiling",
        remote_side=[id],
        foreign_keys=[superseded_by_filing_id]
    )


class GroupFiling(Base):
    """集团申报（同一集团同一年度可多次合并，通过 GroupFilingVersion 形成版本链）"""
    __tablename__ = "group_filings"

    id = Column(Integer, primary_key=True, index=True)
    filing_no = Column(String(50), unique=True, nullable=False, index=True, comment="集团申报编号")
    group_id = Column(Integer, ForeignKey("enterprise_groups.id"), nullable=False)
    year = Column(Integer, nullable=False, comment="申报年度")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    group = relationship("EnterpriseGroup", foreign_keys=[group_id], back_populates="filings")
    versions = relationship(
        "GroupFilingVersion",
        foreign_keys="GroupFilingVersion.group_filing_id",
        back_populates="group_filing",
        cascade="all, delete-orphan"
    )


class GroupFilingVersion(Base):
    """
    集团合并版本。每次生成都是不可变记录：
    - 迟交成员纳入、成员退出、成员更正申报 → 形成新版本，不覆盖旧版本；
    - 已被采用(locked)的版本及其监管结论冻结，只允许在其基础上 amends 新版本。
    """
    __tablename__ = "group_filing_versions"

    id = Column(Integer, primary_key=True, index=True)
    group_filing_id = Column(Integer, ForeignKey("group_filings.id"), nullable=False)
    version_no = Column(Integer, nullable=False, comment="合并版本号，从1递增")
    status = Column(
        Enum(GroupFilingVersionStatus),
        default=GroupFilingVersionStatus.SUBMITTED,
        nullable=False,
        comment="submitted=已生成；locked=监管已采用并冻结；amended=已有后续更正版本"
    )
    change_reason = Column(String(500), comment="新版本形成原因：迟交/退出/更正")
    member_count = Column(Integer, default=0)
    members_aggregate_positive = Column(Float, default=0.0, comment="成员正积分合计(抵销前)")
    members_aggregate_negative = Column(Float, default=0.0, comment="成员负积分合计(抵销前)")
    members_aggregate_net = Column(Float, default=0.0, comment="成员净积分合计(抵销前)")
    members_aggregate_gap = Column(Float, default=0.0, comment="成员缺口合计(抵销前)")
    members_aggregate_surplus = Column(Float, default=0.0, comment="成员结余合计(抵销前)")
    members_carryover_in = Column(Float, default=0.0)
    members_carryover_out = Column(Float, default=0.0)
    members_bought = Column(Float, default=0.0, comment="成员对集团外买入合计")
    members_sold = Column(Float, default=0.0, comment="成员对集团外卖出合计")
    internal_gross = Column(Float, default=0.0, comment="内部交易总额(双向口径)")
    elimination_total = Column(Float, default=0.0, comment="抵销积分金额合计")
    consolidated_positive = Column(Float, default=0.0, comment="合并后正积分")
    consolidated_negative = Column(Float, default=0.0, comment="合并后负积分")
    consolidated_net = Column(Float, default=0.0, comment="合并后净积分")
    consolidated_carryover_in = Column(Float, default=0.0)
    consolidated_carryover_out = Column(Float, default=0.0)
    external_bought = Column(Float, default=0.0, comment="集团对外买入")
    external_sold = Column(Float, default=0.0, comment="集团对外卖出")
    consolidated_final_net = Column(Float, default=0.0, comment="合并后最终净积分")
    consolidated_gap = Column(Float, default=0.0, comment="合并后缺口")
    consolidated_surplus = Column(Float, default=0.0, comment="合并后结余")
    is_compliant = Column(Boolean, default=True, comment="集团合并合规状态")
    member_diff_json = Column(Text, comment="与前一版成员范围差异JSON")
    amount_diff_json = Column(Text, comment="与前一版金额差异JSON")
    regulatory_conclusion = Column(Text, comment="监管结论快照(冻结后不再改写)")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("group_filing_id", "version_no", name="uq_group_filing_version"),
    )

    group_filing = relationship("GroupFiling", foreign_keys=[group_filing_id], back_populates="versions")
    member_selections = relationship(
        "GroupVersionMember",
        foreign_keys="GroupVersionMember.version_id",
        back_populates="version",
        cascade="all, delete-orphan"
    )
    eliminations = relationship(
        "ConsolidationElimination",
        foreign_keys="ConsolidationElimination.version_id",
        back_populates="version",
        cascade="all, delete-orphan"
    )


class GroupVersionMember(Base):
    """
    某合并版本选用的成员封账版本（合并范围）。
    只属于该版本：换版本重新选择，不影响历史版本的勾稽。
    """
    __tablename__ = "group_version_members"

    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey("group_filing_versions.id"), nullable=False)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    member_filing_id = Column(Integer, ForeignKey("member_filings.id"), nullable=False)
    change_type = Column(
        String(20), default=MEMBER_CHANGE_UNCHANGED, nullable=False,
        comment="相对前版：initial/added/removed/unchanged/corrected"
    )
    prior_filing_id = Column(
        Integer, ForeignKey("member_filings.id"), nullable=True,
        comment="corrected 时前版采用的封账版本"
    )
    included = Column(Boolean, default=True, comment="是否计入本版(退出成员置False并保留差异)")

    __table_args__ = (
        UniqueConstraint("version_id", "enterprise_id", name="uq_version_enterprise"),
    )

    version = relationship("GroupFilingVersion", foreign_keys=[version_id], back_populates="member_selections")
    enterprise = relationship("Enterprise", foreign_keys=[enterprise_id])
    member_filing = relationship("MemberFiling", foreign_keys=[member_filing_id])
    prior_filing = relationship("MemberFiling", foreign_keys=[prior_filing_id])


class ConsolidationElimination(Base):
    """
    合并抵销项目，仅属于生成它的那个合并版本。
    抵销双方原始记录仍保留在成员封账快照中，这里只做合并口径冲减。
    外部交易与跨年度结转不生成抵销。
    """
    __tablename__ = "consolidation_eliminations"

    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey("group_filing_versions.id"), nullable=False)
    elimination_no = Column(String(50), nullable=False, index=True)
    entry_type = Column(String(30), nullable=False, comment="抵销类型：credit_transfer/model_transfer")
    year = Column(Integer, nullable=False)
    seller_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False, comment="积分让出方")
    buyer_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False, comment="积分受让方")
    source_transaction_id = Column(
        Integer, ForeignKey("credit_transactions.id"), nullable=True,
        comment="对应的内部交易原始记录ID(车型转让无交易时为空)"
    )
    seller_record_id = Column(
        Integer, ForeignKey("credit_records.id"), nullable=True,
        comment="让出方原始积分记录ID(车型转让)"
    )
    buyer_record_id = Column(
        Integer, ForeignKey("credit_records.id"), nullable=True,
        comment="受让方原始积分记录ID(车型转让，如有)"
    )
    gross_amount = Column(Float, nullable=False, comment="内部交易原始金额(双向口径)")
    elimination_amount = Column(Float, nullable=False, comment="本版抵销金额")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    version = relationship(
        "GroupFilingVersion",
        foreign_keys=[version_id],
        back_populates="eliminations"
    )
    seller_enterprise = relationship("Enterprise", foreign_keys=[seller_enterprise_id])
    buyer_enterprise = relationship("Enterprise", foreign_keys=[buyer_enterprise_id])
    source_transaction = relationship("CreditTransaction", foreign_keys=[source_transaction_id])
    seller_record = relationship("CreditRecord", foreign_keys=[seller_record_id])
    buyer_record = relationship("CreditRecord", foreign_keys=[buyer_record_id])
