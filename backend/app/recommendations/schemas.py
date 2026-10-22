"""Контракты API подбора кредитных продуктов."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

PurposeCode = Literal[
    'working_capital', 'cash_gap', 'equipment', 'investment', 'real_estate',
    'tender_guarantee',
]
Urgency = Literal['high', 'normal']
CollateralType = Literal['real_estate', 'equipment', 'vehicle', 'none']

Money = Annotated[StrictInt, Field(ge=0, le=9_007_199_254_740_991)]
PositiveMoney = Annotated[StrictInt, Field(gt=0, le=9_007_199_254_740_991)]


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    purpose: PurposeCode
    amount_kopecks: PositiveMoney
    term_months: Annotated[StrictInt, Field(ge=1, le=120)]
    urgency: Urgency = 'normal'
    has_collateral: StrictBool | None = None
    collateral_type: CollateralType | None = None
    supplier_invoice_attached: StrictBool | None = None
    down_payment_pct: Annotated[StrictInt, Field(ge=0, le=100)] | None = None
    business_plan_attached: StrictBool | None = None
    tender_number: str | None = Field(default=None, max_length=40)
    revenue_total_kopecks: Money | None = None
    expenses_total_kopecks: Money | None = None
    existing_debt_payments_kopecks: Money | None = None
    period_start: date | None = None
    period_end: date | None = None
    period_months: Annotated[StrictInt, Field(ge=1, le=12)] | None = None

    @model_validator(mode='after')
    def validate_period(self):
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError('Период должен содержать обе даты')
        if self.period_start is not None and self.period_months is not None:
            raise ValueError('Нельзя одновременно указывать даты и period_months')
        if self.revenue_total_kopecks is None and (
                self.expenses_total_kopecks is not None
                or self.existing_debt_payments_kopecks is not None):
            raise ValueError('Расходы и долговые платежи требуют выручки')
        if self.collateral_type is not None and self.has_collateral is False \
                and self.collateral_type != 'none':
            raise ValueError('Тип залога противоречит has_collateral=false')
        if self.collateral_type == 'none' and self.has_collateral is True:
            raise ValueError('Тип залога противоречит has_collateral=true')
        return self


class PurposeOption(BaseModel):
    code: PurposeCode
    label: str


class OptionItem(BaseModel):
    code: str
    label: str


class OptionsOutput(BaseModel):
    purposes: list[PurposeOption]
    collateral_types: list[OptionItem]
    urgency_levels: list[OptionItem]
    config_version: str


class RecommendationAction(BaseModel):
    kind: Literal['change_purpose', 'change_amount', 'change_term', 'change_collateral',
                  'attach_document', 'offer_choice', 'open_cabinet']
    code: str
    label: str
    product_id: str | None = None


class RecommendationItem(BaseModel):
    offer_id: str
    product_id: str
    product_name: str
    product_type: str
    cabinet_product_code: str | None = None
    is_available_in_cabinet: bool
    rank: int
    score: int = Field(ge=0, le=100)
    purpose_match: bool
    approved_amount_kopecks: int
    term_months: int
    term_days: int | None = None
    base_rate_pct: float | None = None
    commission_year_pct: float | None = None
    effective_annual_cost_pct: float
    monthly_payment_kopecks: int | None = None
    total_cost_kopecks: int | None = None
    approval_likelihood: int = Field(ge=0, le=100)
    approval_time_hours: int
    client_reasons: list[str]
    missing_data: list[str]
    next_action: str | None = None


class RecommendationResponse(BaseModel):
    status: Literal['ok', 'counter_offer', 'request_data', 'alternative_product', 'no_match']
    message: str
    items: list[RecommendationItem]
    alternatives: list[RecommendationItem]
    actions: list[RecommendationAction]
    config_version: str
    trace_id: str
    staff_trace: list[dict] | None = None
