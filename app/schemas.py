from typing import List, Optional
from datetime import datetime, date
from pydantic import BaseModel, Field

from .models import (
    CreditRecordStatus, OrderType, OrderStatus, CarryoverStatus,
    MembershipStatus, MemberFilingStatus, GroupFilingVersionStatus
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


# ============================ 集团合并申报 ============================

class EnterpriseGroupBase(BaseModel):
    name: str = Field(..., max_length=100, description="集团名称")
    credit_code: Optional[str] = Field(None, max_length=50, description="集团统一社会信用代码")
    contact_person: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=50)
    remark: Optional[str] = Field(None, max_length=500)


class EnterpriseGroupCreate(EnterpriseGroupBase):
    pass


class EnterpriseGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    credit_code: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=50)
    remark: Optional[str] = Field(None, max_length=500)


class EnterpriseGroup(EnterpriseGroupBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InternalModelTransferCreate(BaseModel):
    year: int
    seller_enterprise_id: int = Field(..., description="让出方(原属企业)ID")
    buyer_enterprise_id: int = Field(..., description="受让方ID")
    model_name: str = Field(..., max_length=100, description="转让车型名称")
    seller_record_id: Optional[int] = Field(None, description="让出方原始积分记录ID")
    buyer_record_id: Optional[int] = Field(None, description="受让方原始积分记录ID")
    duplicated_credit: float = Field(..., gt=0, description="双方重复申报、需抵销的重叠积分(正数)")
    remark: Optional[str] = Field(None, max_length=500)


class InternalModelTransfer(BaseModel):
    id: int
    transfer_no: str
    year: int
    seller_enterprise_id: int
    buyer_enterprise_id: int
    model_name: str
    seller_record_id: Optional[int] = None
    buyer_record_id: Optional[int] = None
    duplicated_credit: float
    remark: Optional[str] = None
    created_at: datetime
    seller_enterprise_name: Optional[str] = None
    buyer_enterprise_name: Optional[str] = None

    class Config:
        from_attributes = True


class GroupMembershipCreate(BaseModel):
    enterprise_id: int = Field(..., description="成员企业ID")
    effective_from: date = Field(..., description="成员生效日期(含)")
    effective_to: Optional[date] = Field(None, description="退出日期(不含)，留空表示至今")
    remark: Optional[str] = Field(None, max_length=500)


class GroupMembershipExit(BaseModel):
    effective_to: date = Field(..., description="成员退出日期(不含)")
    remark: Optional[str] = Field(None, max_length=500)


class GroupMembership(BaseModel):
    id: int
    group_id: int
    enterprise_id: int
    effective_from: date
    effective_to: Optional[date] = None
    status: MembershipStatus
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    enterprise_name: Optional[str] = None

    class Config:
        from_attributes = True


class MemberFilingSealRequest(BaseModel):
    enterprise_id: int
    year: int
    remark: Optional[str] = Field(None, max_length=500)


class MemberFiling(BaseModel):
    id: int
    filing_no: str
    enterprise_id: int
    year: int
    version_no: int
    status: MemberFilingStatus
    superseded_by_filing_id: Optional[int] = None
    total_positive_credit: float
    total_negative_credit: float
    net_credit: float
    carryover_in: float
    carryover_out: float
    bought_credit: float
    sold_credit: float
    final_net_credit: float
    credit_gap: float
    credit_surplus: float
    is_compliant: bool
    sealed_at: datetime
    remark: Optional[str] = None
    enterprise_name: Optional[str] = None

    class Config:
        from_attributes = True


class GroupConsolidationMemberRequest(BaseModel):
    enterprise_id: int = Field(..., description="纳入合并的成员企业ID")
    member_filing_id: Optional[int] = Field(
        None, description="指定封账版本；不传则使用该企业当年最新封账版本"
    )


class GroupConsolidationCreateRequest(BaseModel):
    group_id: int
    year: int
    members: List[GroupConsolidationMemberRequest] = Field(
        ..., min_length=1, description="合并范围（成员及其封账版本）"
    )
    change_reason: Optional[str] = Field(None, max_length=500, description="新版本形成原因")
    lock_after_create: bool = Field(False, description="生成后是否立即冻结监管结论")


class EliminationItem(BaseModel):
    id: int
    elimination_no: str
    entry_type: str
    year: int
    seller_enterprise_id: int
    buyer_enterprise_id: int
    seller_enterprise_name: Optional[str] = None
    buyer_enterprise_name: Optional[str] = None
    source_transaction_id: Optional[int] = None
    seller_record_id: Optional[int] = None
    buyer_record_id: Optional[int] = None
    gross_amount: float
    elimination_amount: float
    remark: Optional[str] = None

    class Config:
        from_attributes = True


class GroupVersionMemberItem(BaseModel):
    enterprise_id: int
    enterprise_name: Optional[str] = None
    member_filing_id: int
    member_filing_version_no: int
    change_type: str
    prior_filing_id: Optional[int] = None
    included: bool
    net_credit: float
    credit_gap: float
    credit_surplus: float
    is_compliant: bool

    class Config:
        from_attributes = True


class GroupFilingVersion(BaseModel):
    model_config = {"protected_namespaces": (), "from_attributes": True}

    id: int
    group_filing_id: int
    version_no: int
    status: GroupFilingVersionStatus
    change_reason: Optional[str] = None
    member_count: int
    members_aggregate_positive: float
    members_aggregate_negative: float
    members_aggregate_net: float
    members_aggregate_gap: float
    members_aggregate_surplus: float
    members_carryover_in: float
    members_carryover_out: float
    members_bought: float
    members_sold: float
    internal_gross: float
    elimination_total: float
    consolidated_positive: float
    consolidated_negative: float
    consolidated_net: float
    consolidated_carryover_in: float
    consolidated_carryover_out: float
    external_bought: float
    external_sold: float
    consolidated_final_net: float
    consolidated_gap: float
    consolidated_surplus: float
    is_compliant: bool
    member_diff_json: Optional[str] = None
    amount_diff_json: Optional[str] = None
    regulatory_conclusion: Optional[str] = None
    created_at: datetime


class GroupFilingVersionDetail(GroupFilingVersion):
    members: List[GroupVersionMemberItem] = []
    eliminations: List[EliminationItem] = []
    reconciliation: Optional[dict] = None


class GroupConsolidationReconciliation(BaseModel):
    model_config = {"protected_namespaces": (), "from_attributes": True}

    year: int
    member_count: int
    members_aggregate_net: float
    elimination_total: float
    consolidated_net: float
    members_aggregate_gap: float
    members_aggregate_surplus: float
    consolidated_gap: float
    consolidated_surplus: float
    members_carryover_in: float
    members_carryover_out: float
    consolidated_carryover_in: float
    consolidated_carryover_out: float
    external_bought: float
    external_sold: float
    members_bought: float
    members_sold: float
    net_balanced: bool = Field(..., description="成员净积分合计-内部抵销=合并净积分")
    carryover_balanced: bool = Field(..., description="跨年度结转未被抵销")
    external_balanced: bool = Field(..., description="对外买卖未被误抵销")
    surplus_gap_balanced: bool = Field(..., description="结余/缺口勾稽")
    all_balanced: bool
    member_details: List[dict] = []
    check_details: List[str] = []
