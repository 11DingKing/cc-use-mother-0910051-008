from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from .models import (
    CreditRecordStatus,
    OrderType,
    OrderStatus,
    CarryoverStatus,
    DeclarationStatus,
    ConsolidationStatus,
    ConsolidationReason,
)


class EnterpriseBase(BaseModel):
    name: str = Field(..., max_length=100, description="企业名称")
    short_name: Optional[str] = Field(None, max_length=50, description="企业简称")
    credit_code: Optional[str] = Field(None, max_length=50, description="统一社会信用代码")
    address: Optional[str] = Field(None, max_length=200, description="企业地址")
    contact_person: Optional[str] = Field(None, max_length=50, description="联系人")
    contact_phone: Optional[str] = Field(None, max_length=50, description="联系电话")


class EnterpriseCreate(EnterpriseBase):
    pass


class EnterpriseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    short_name: Optional[str] = Field(None, max_length=50)
    credit_code: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=200)
    contact_person: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=50)


class Enterprise(EnterpriseBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EnterpriseWithStats(Enterprise):
    model_config = {"protected_namespaces": (), "from_attributes": True}

    model_count: int = 0
    total_annual_output: int = 0
    total_credit: float = 0.0


class VehicleModelBase(BaseModel):
    model_config = {"protected_namespaces": ()}

    enterprise_id: int = Field(..., description="所属企业ID")
    model_name: str = Field(..., max_length=100, description="车型名称")
    model_code: str = Field(..., max_length=50, description="车型代码")
    curb_weight: float = Field(..., gt=0, description="整备质量(kg)")
    power_consumption: float = Field(..., gt=0, description="百公里电耗(kWh/100km)")
    range: float = Field(..., gt=0, description="续航里程(km)")
    annual_output: int = Field(..., ge=0, description="年产量(辆)")
    production_year: int = Field(..., description="生产年份")


class VehicleModelCreate(VehicleModelBase):
    pass


class VehicleModelUpdate(BaseModel):
    enterprise_id: Optional[int] = None
    model_name: Optional[str] = Field(None, max_length=100)
    model_code: Optional[str] = Field(None, max_length=50)
    curb_weight: Optional[float] = Field(None, gt=0)
    power_consumption: Optional[float] = Field(None, gt=0)
    range: Optional[float] = Field(None, gt=0)
    annual_output: Optional[int] = Field(None, ge=0)
    production_year: Optional[int] = None
    is_suspected_weight_manipulation: Optional[bool] = None


class VehicleModel(VehicleModelBase):
    id: int
    is_suspected_weight_manipulation: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VehicleModelWithEnterprise(VehicleModel):
    enterprise: Enterprise
    power_consumption_limit: Optional[float] = None
    unit_credit: Optional[float] = None

    class Config:
        from_attributes = True


class CreditRecordBase(BaseModel):
    vehicle_model_id: int
    year: int
    power_consumption_limit: float
    actual_power_consumption: float
    unit_credit: float
    total_credit: float
    annual_output: int


class CreditRecordCreate(CreditRecordBase):
    pass


class CreditRecord(CreditRecordBase):
    id: int
    status: CreditRecordStatus
    calculated_at: Optional[datetime] = None
    publicized_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreditRecordWithDetail(CreditRecord):
    vehicle_model: VehicleModel
    enterprise: Optional[Enterprise] = None

    class Config:
        from_attributes = True


class CreditRecordStatusUpdate(BaseModel):
    status: CreditRecordStatus


class CreditRecordUpdate(BaseModel):
    power_consumption_limit: Optional[float] = None
    actual_power_consumption: Optional[float] = None
    unit_credit: Optional[float] = None
    total_credit: Optional[float] = None
    annual_output: Optional[int] = None


class CreditTransactionBase(BaseModel):
    from_enterprise_id: int
    to_enterprise_id: int
    credit_amount: float
    unit_price: Optional[float] = None
    total_amount: Optional[float] = None
    remark: Optional[str] = None


class CreditTransactionCreate(CreditTransactionBase):
    pass


class CreditTransaction(CreditTransactionBase):
    id: int
    transaction_no: str
    transaction_date: datetime
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class CreditTransactionWithDetail(CreditTransaction):
    from_enterprise: Enterprise
    to_enterprise: Enterprise

    class Config:
        from_attributes = True


class CalculationResult(BaseModel):
    model_config = {"protected_namespaces": ()}

    vehicle_model_id: int
    model_name: str
    curb_weight: float
    power_consumption_limit: float
    actual_power_consumption: float
    unit_credit: float
    annual_output: int
    total_credit: float
    is_compliant: bool


class EnterpriseCreditSummaryResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    enterprise_id: int
    enterprise_name: str
    total_positive_credit: float
    total_negative_credit: float
    net_credit: float
    required_credit: float
    credit_gap: float
    credit_surplus: float
    compliance_rate: float
    average_power_consumption: float
    weighted_power_consumption: float
    model_count: int
    compliant_model_count: int


class MatchResultResponse(BaseModel):
    from_enterprise_id: int
    from_enterprise_name: str
    to_enterprise_id: int
    to_enterprise_name: str
    credit_amount: float
    unit_price: float
    total_amount: float


class MatchAndExecuteResponse(BaseModel):
    success: bool
    message: str
    transactions: List[CreditTransactionWithDetail] = []
    remaining_gap: float = 0.0
    remaining_surplus: float = 0.0


class WeightSuggestionResponse(BaseModel):
    current_weight: float
    current_limit: float
    is_suspicious: bool
    suggestions: List[dict]


class EnterpriseStatsResponse(BaseModel):
    enterprise_id: int
    enterprise_name: str
    model_count: int
    total_output: int
    average_power_consumption: float
    weighted_power_consumption: float
    average_power_consumption_limit: float
    compliance_rate: float
    total_positive_credit: float
    total_negative_credit: float
    net_credit: float


class SuspiciousModelResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    id: int
    model_name: str
    model_code: str
    enterprise_name: str
    curb_weight: float
    power_consumption: float
    range: float
    power_consumption_limit: float
    annual_output: int
    weight_analysis: dict


class CreditOrderBase(BaseModel):
    enterprise_id: int
    year: int
    order_type: OrderType
    unit_price: float = Field(..., gt=0, description="报价单价(元/分)")
    total_amount: float = Field(..., gt=0, description="挂单总积分数量")
    remark: Optional[str] = Field(None, max_length=500)
    expires_at: Optional[datetime] = None


class CreditOrderCreate(CreditOrderBase):
    pass


class CreditOrderUpdate(BaseModel):
    unit_price: Optional[float] = Field(None, gt=0)
    total_amount: Optional[float] = Field(None, gt=0)
    status: Optional[OrderStatus] = None
    remark: Optional[str] = None


class CreditOrder(CreditOrderBase):
    id: int
    order_no: str
    filled_amount: float
    remaining_amount: float
    status: OrderStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreditOrderWithDetail(CreditOrder):
    enterprise: Enterprise
    sell_transactions: List["CreditTransaction"] = []
    buy_transactions: List["CreditTransaction"] = []

    class Config:
        from_attributes = True


class CreditOrderMatchRequest(BaseModel):
    buy_order_id: int
    sell_order_id: int
    credit_amount: float


class MatchWithOrdersResponse(BaseModel):
    success: bool
    message: str
    transactions: List[CreditTransactionWithDetail] = []
    matched_orders: List[dict] = []
    remaining_gap: float = 0.0
    remaining_surplus: float = 0.0


class PriceHistoryBase(BaseModel):
    year: int
    trade_date: datetime
    unit_price: float
    credit_amount: float
    total_amount: float
    from_enterprise_id: Optional[int] = None
    to_enterprise_id: Optional[int] = None
    transaction_id: Optional[int] = None


class PriceHistoryCreate(PriceHistoryBase):
    pass


class PriceHistory(PriceHistoryBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class PriceTrendResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    year: int
    avg_price: float
    min_price: float
    max_price: float
    total_volume: float
    total_value: float
    trade_count: int
    price_by_date: List[dict] = []


class CreditCarryoverBase(BaseModel):
    enterprise_id: int
    from_year: int
    to_year: int
    original_amount: float
    carryover_ratio: float
    carryover_amount: float
    remark: Optional[str] = None


class CreditCarryoverCreate(CreditCarryoverBase):
    pass


class CreditCarryoverUpdate(BaseModel):
    status: Optional[CarryoverStatus] = None
    remark: Optional[str] = None


class CreditCarryover(CreditCarryoverBase):
    id: int
    carryover_no: str
    used_amount: float
    remaining_amount: float
    status: CarryoverStatus
    created_at: datetime
    approved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CreditCarryoverWithDetail(CreditCarryover):
    enterprise: Enterprise

    class Config:
        from_attributes = True


class AnnualCreditSummaryBase(BaseModel):
    enterprise_id: int
    year: int
    total_positive_credit: float = 0.0
    total_negative_credit: float = 0.0
    net_credit: float = 0.0
    carryover_in: float = 0.0
    carryover_out: float = 0.0
    bought_credit: float = 0.0
    sold_credit: float = 0.0
    final_net_credit: float = 0.0
    credit_gap: float = 0.0
    credit_surplus: float = 0.0
    is_compliant: bool = True


class AnnualCreditSummaryCreate(AnnualCreditSummaryBase):
    pass


class AnnualCreditSummary(AnnualCreditSummaryBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AnnualCreditSummaryWithDetail(AnnualCreditSummary):
    enterprise: Enterprise
    carryovers: List[CreditCarryover] = []
    transactions: List[CreditTransactionWithDetail] = []

    class Config:
        from_attributes = True


class EnterpriseMultiYearSummaryResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    enterprise_id: int
    enterprise_name: str
    years: List[int] = []
    annual_summaries: List[dict] = []
    total_carryover_in: float = 0.0
    total_carryover_out: float = 0.0
    total_bought: float = 0.0
    total_sold: float = 0.0


class CreditPredictionRequest(BaseModel):
    enterprise_id: Optional[int] = None
    target_year: int
    output_growth_rate: Optional[float] = Field(0.05, description="产量年增长率")
    pc_improvement_rate: Optional[float] = Field(0.02, description="电耗年改善率")


class ModelPrediction(BaseModel):
    model_config = {"protected_namespaces": ()}

    model_name: str
    model_code: str
    curb_weight: float
    current_power_consumption: float
    predicted_power_consumption: float
    power_consumption_limit: float
    predicted_output: int
    predicted_unit_credit: float
    predicted_total_credit: float


class CreditPredictionResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    enterprise_id: int
    enterprise_name: str
    target_year: int
    historical_years: List[int] = []
    historical_credits: List[dict] = []
    predicted_total_positive: float
    predicted_total_negative: float
    predicted_net_credit: float
    predicted_compliance_rate: float
    model_predictions: List[ModelPrediction] = []
    prediction_method: str
    assumptions: dict


class MarketOverviewResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    year: int
    total_sell_orders: int
    total_buy_orders: int
    total_sell_volume: float
    total_buy_volume: float
    avg_sell_price: float
    avg_buy_price: float
    min_sell_price: float
    max_sell_price: float
    min_buy_price: float
    max_buy_price: float
    pending_sell_volume: float
    pending_buy_volume: float
    matched_count: int
    matched_volume: float
    matched_value: float


class CarryoverSummaryResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    enterprise_id: int
    enterprise_name: str
    from_year: int
    to_year: int
    original_surplus: float
    carryover_ratio: float
    carryover_amount: float
    used_amount: float
    remaining_amount: float
    status: str


CreditOrderWithDetail.model_rebuild()


# ============ 集团统一申报 ============

class EnterpriseGroupBase(BaseModel):
    name: str = Field(..., max_length=100, description="集团名称")
    group_code: Optional[str] = Field(None, max_length=50, description="集团编码")
    remark: Optional[str] = Field(None, max_length=500)


class EnterpriseGroupCreate(EnterpriseGroupBase):
    pass


class EnterpriseGroup(EnterpriseGroupBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GroupMembershipBase(BaseModel):
    enterprise_id: int = Field(..., description="成员企业ID")
    effective_from_year: int = Field(..., description="成员生效起始年度")
    effective_to_year: Optional[int] = Field(None, description="成员生效截止年度(空表示仍在集团内)")
    remark: Optional[str] = Field(None, max_length=500)


class GroupMembershipCreate(GroupMembershipBase):
    pass


class GroupMembershipUpdate(BaseModel):
    effective_from_year: Optional[int] = None
    effective_to_year: Optional[int] = None
    remark: Optional[str] = Field(None, max_length=500)


class GroupMembership(GroupMembershipBase):
    id: int
    group_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GroupMembershipWithEnterprise(GroupMembership):
    enterprise: Optional[Enterprise] = None

    class Config:
        from_attributes = True


class EnterpriseGroupWithMembers(EnterpriseGroup):
    memberships: List[GroupMembershipWithEnterprise] = []

    class Config:
        from_attributes = True


class MemberDeclarationCreate(BaseModel):
    enterprise_id: int = Field(..., description="申报成员企业ID")
    year: int = Field(..., description="申报年度")
    remark: Optional[str] = Field(None, max_length=500, description="封账说明")


class MemberDeclarationTransaction(BaseModel):
    id: int
    transaction_id: int
    transaction_no: Optional[str] = None
    counterparty_enterprise_id: int
    direction: str
    credit_amount: float
    is_internal: bool
    transaction_year: int

    class Config:
        from_attributes = True


class MemberDeclaration(BaseModel):
    id: int
    group_id: int
    enterprise_id: int
    year: int
    version_no: int
    status: DeclarationStatus
    total_positive_credit: float
    total_negative_credit: float
    net_credit: float
    carryover_in: float
    carryover_out: float
    bought_credit: float
    sold_credit: float
    internal_bought_credit: float
    internal_sold_credit: float
    external_bought_credit: float
    external_sold_credit: float
    final_net_credit: float
    credit_gap: float
    credit_surplus: float
    is_compliant: bool
    remark: Optional[str] = None
    sealed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MemberDeclarationWithDetail(MemberDeclaration):
    enterprise: Optional[Enterprise] = None
    transactions: List[MemberDeclarationTransaction] = []

    class Config:
        from_attributes = True


class GroupConsolidationGenerate(BaseModel):
    year: int = Field(..., description="合并申报年度")
    member_enterprise_ids: Optional[List[int]] = Field(
        None, description="合并范围成员企业ID列表(空表示全部当年生效成员)"
    )
    declaration_ids: Optional[List[int]] = Field(
        None, description="指定纳入的成员封账版本ID(空表示取各成员最新封账版本)"
    )
    reason: Optional[ConsolidationReason] = Field(None, description="版本形成原因")
    remark: Optional[str] = Field(None, max_length=500)


class GroupConsolidationMember(BaseModel):
    id: int
    consolidation_id: int
    declaration_id: int
    enterprise_id: int
    declaration_version_no: int
    final_net_credit: float
    credit_gap: float
    credit_surplus: float
    is_compliant: bool

    class Config:
        from_attributes = True


class GroupElimination(BaseModel):
    id: int
    consolidation_id: int
    transaction_id: int
    transaction_no: Optional[str] = None
    from_enterprise_id: int
    to_enterprise_id: int
    credit_amount: float
    eliminated_amount: float
    captured_by_from: bool
    captured_by_to: bool
    remark: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class GroupConsolidation(BaseModel):
    id: int
    group_id: int
    year: int
    version_no: int
    status: ConsolidationStatus
    reason: Optional[str] = None
    previous_version_id: Optional[int] = None
    member_count: int
    total_positive_credit: float
    total_negative_credit: float
    net_credit: float
    carryover_in: float
    carryover_out: float
    eliminated_internal_bought: float
    eliminated_internal_sold: float
    eliminated_amount: float
    external_bought_credit: float
    external_sold_credit: float
    final_net_credit: float
    credit_gap: float
    credit_surplus: float
    is_compliant: bool
    change_summary: Optional[str] = None
    remark: Optional[str] = None
    created_at: datetime
    adopted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GroupConsolidationWithDetail(GroupConsolidation):
    members: List[GroupConsolidationMember] = []
    eliminations: List[GroupElimination] = []

    class Config:
        from_attributes = True
