import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, Boolean, Text
from sqlalchemy.orm import relationship

from .database import Base


class CreditRecordStatus(str, enum.Enum):
    CALCULATED = "calculated"
    PUBLICIZED = "publicized"
    CONFIRMED = "confirmed"


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


class DeclarationStatus(str, enum.Enum):
    SEALED = "sealed"
    SUPERSEDED = "superseded"


class ConsolidationStatus(str, enum.Enum):
    GENERATED = "generated"
    ADOPTED = "adopted"
    SUPERSEDED = "superseded"


class ConsolidationReason(str, enum.Enum):
    INITIAL = "initial"
    LATE_SUBMISSION = "late_submission"
    MEMBER_EXIT = "member_exit"
    CORRECTION = "correction"
    SCOPE_CHANGE = "scope_change"
    OTHER = "other"


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


class EnterpriseGroup(Base):
    __tablename__ = "enterprise_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True, comment="集团名称")
    group_code = Column(String(50), unique=True, index=True, comment="集团编码")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    memberships = relationship("GroupMembership", back_populates="group")
    declarations = relationship("MemberDeclaration", back_populates="group")
    consolidations = relationship("GroupConsolidation", back_populates="group")


class GroupMembership(Base):
    __tablename__ = "group_memberships"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("enterprise_groups.id"), nullable=False)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    effective_from_year = Column(Integer, nullable=False, comment="成员生效起始年度")
    effective_to_year = Column(Integer, comment="成员生效截止年度(空表示仍在集团内)")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    group = relationship("EnterpriseGroup", back_populates="memberships")
    enterprise = relationship("Enterprise")


class MemberDeclaration(Base):
    """成员企业封账申报版本：提交即封账，更正产生新版本，旧版本置为 superseded 不改写"""
    __tablename__ = "member_declarations"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("enterprise_groups.id"), nullable=False)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    year = Column(Integer, nullable=False, comment="申报年度")
    version_no = Column(Integer, nullable=False, comment="成员申报版本号(按集团+企业+年度递增)")
    status = Column(Enum(DeclarationStatus), default=DeclarationStatus.SEALED, nullable=False)
    total_positive_credit = Column(Float, default=0.0, comment="封账时当年正积分")
    total_negative_credit = Column(Float, default=0.0, comment="封账时当年负积分")
    net_credit = Column(Float, default=0.0, comment="封账时当年净积分")
    carryover_in = Column(Float, default=0.0, comment="封账时上年结转积分")
    carryover_out = Column(Float, default=0.0, comment="封账时结转下年积分")
    bought_credit = Column(Float, default=0.0, comment="封账时买入积分合计")
    sold_credit = Column(Float, default=0.0, comment="封账时卖出积分合计")
    internal_bought_credit = Column(Float, default=0.0, comment="其中集团内部买入")
    internal_sold_credit = Column(Float, default=0.0, comment="其中集团内部卖出")
    external_bought_credit = Column(Float, default=0.0, comment="其中集团外部买入")
    external_sold_credit = Column(Float, default=0.0, comment="其中集团外部卖出")
    final_net_credit = Column(Float, default=0.0, comment="封账时最终净积分")
    credit_gap = Column(Float, default=0.0, comment="封账时积分缺口")
    credit_surplus = Column(Float, default=0.0, comment="封账时积分钟余")
    is_compliant = Column(Boolean, default=True, comment="封账时是否达标")
    remark = Column(String(500))
    sealed_at = Column(DateTime, default=datetime.utcnow, comment="封账时间")
    created_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("EnterpriseGroup", back_populates="declarations")
    enterprise = relationship("Enterprise")
    transactions = relationship("MemberDeclarationTransaction", back_populates="declaration")


class MemberDeclarationTransaction(Base):
    """封账版本纳入的交易快照：保留成员双方原始交易记录，供合并版本抵销核对"""
    __tablename__ = "member_declaration_transactions"

    id = Column(Integer, primary_key=True, index=True)
    declaration_id = Column(Integer, ForeignKey("member_declarations.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("credit_transactions.id"), nullable=False, comment="原始交易ID")
    transaction_no = Column(String(50), comment="原始交易编号")
    counterparty_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False, comment="交易对手企业ID")
    direction = Column(String(10), nullable=False, comment="方向：buy买入/sell卖出")
    credit_amount = Column(Float, nullable=False, comment="交易积分数量")
    is_internal = Column(Boolean, default=False, comment="封账时是否为集团内部交易")
    transaction_year = Column(Integer, nullable=False, comment="交易发生年度")
    created_at = Column(DateTime, default=datetime.utcnow)

    declaration = relationship("MemberDeclaration", back_populates="transactions")
    original_transaction = relationship("CreditTransaction")


class GroupConsolidation(Base):
    """集团合并申报版本：抵销项目仅属于本版本；已采用版本不可改写，更正只产生新版本"""
    __tablename__ = "group_consolidations"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("enterprise_groups.id"), nullable=False)
    year = Column(Integer, nullable=False, comment="合并申报年度")
    version_no = Column(Integer, nullable=False, comment="合并版本号(按集团+年度递增)")
    status = Column(Enum(ConsolidationStatus), default=ConsolidationStatus.GENERATED, nullable=False)
    reason = Column(String(30), default=ConsolidationReason.INITIAL.value, comment="版本形成原因")
    previous_version_id = Column(Integer, ForeignKey("group_consolidations.id"), comment="上一合并版本ID")
    member_count = Column(Integer, default=0, comment="纳入合并的成员数")
    total_positive_credit = Column(Float, default=0.0, comment="合并正积分合计")
    total_negative_credit = Column(Float, default=0.0, comment="合并负积分合计")
    net_credit = Column(Float, default=0.0, comment="合并当年净积分")
    carryover_in = Column(Float, default=0.0, comment="合并上年结转(不抵销)")
    carryover_out = Column(Float, default=0.0, comment="合并结转下年(不抵销)")
    eliminated_internal_bought = Column(Float, default=0.0, comment="抵销的内部买入合计")
    eliminated_internal_sold = Column(Float, default=0.0, comment="抵销的内部卖出合计")
    eliminated_amount = Column(Float, default=0.0, comment="抵销项目金额合计(按交易去重)")
    external_bought_credit = Column(Float, default=0.0, comment="抵销后集团外部买入")
    external_sold_credit = Column(Float, default=0.0, comment="抵销后集团外部卖出")
    final_net_credit = Column(Float, default=0.0, comment="合并最终净积分")
    credit_gap = Column(Float, default=0.0, comment="合并积分缺口")
    credit_surplus = Column(Float, default=0.0, comment="合并积分钟余")
    is_compliant = Column(Boolean, default=True, comment="合并后是否达标")
    change_summary = Column(Text, comment="与上一版本的成员及金额差异说明(JSON)")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    adopted_at = Column(DateTime, comment="监管采用时间")

    group = relationship("EnterpriseGroup", back_populates="consolidations")
    members = relationship("GroupConsolidationMember", back_populates="consolidation")
    eliminations = relationship("GroupElimination", back_populates="consolidation")


class GroupConsolidationMember(Base):
    """合并版本纳入的成员范围：指向成员封账版本的不可变快照"""
    __tablename__ = "group_consolidation_members"

    id = Column(Integer, primary_key=True, index=True)
    consolidation_id = Column(Integer, ForeignKey("group_consolidations.id"), nullable=False)
    declaration_id = Column(Integer, ForeignKey("member_declarations.id"), nullable=False)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    declaration_version_no = Column(Integer, nullable=False, comment="纳入的成员申报版本号")
    final_net_credit = Column(Float, default=0.0, comment="成员封账最终净积分")
    credit_gap = Column(Float, default=0.0, comment="成员封账缺口")
    credit_surplus = Column(Float, default=0.0, comment="成员封账钟余")
    is_compliant = Column(Boolean, default=True, comment="成员封账是否达标")
    created_at = Column(DateTime, default=datetime.utcnow)

    consolidation = relationship("GroupConsolidation", back_populates="members")
    declaration = relationship("MemberDeclaration")
    enterprise = relationship("Enterprise")


class GroupElimination(Base):
    """集团内部交易抵销项目：仅属于生成它的合并版本，原始交易双方记录保留不改写"""
    __tablename__ = "group_eliminations"

    id = Column(Integer, primary_key=True, index=True)
    consolidation_id = Column(Integer, ForeignKey("group_consolidations.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("credit_transactions.id"), nullable=False, comment="被抵销的原始内部交易ID")
    transaction_no = Column(String(50), comment="被抵销的原始交易编号")
    from_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False, comment="转出成员企业ID")
    to_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False, comment="转入成员企业ID")
    credit_amount = Column(Float, nullable=False, comment="原始交易积分数量")
    eliminated_amount = Column(Float, nullable=False, comment="抵销积分数量")
    captured_by_from = Column(Boolean, default=True, comment="转出方封账版本是否已含该交易")
    captured_by_to = Column(Boolean, default=True, comment="转入方封账版本是否已含该交易")
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    consolidation = relationship("GroupConsolidation", back_populates="eliminations")
    original_transaction = relationship("CreditTransaction")
