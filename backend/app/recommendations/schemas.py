"""Контракты предварительного подбора, который не является кредитным решением."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.products.financial import FinancialGate
from app.products.schemas import ApplicationField, DocumentType, PaymentTerms, ProductCode

PurposeCode = Literal['working_capital', 'cash_gap', 'equipment', 'investment',
                      'real_estate', 'tender_guarantee']
InputField = Literal['revenue_total_kopecks', 'expenses_total_kopecks',
                     'existing_debt_payments_kopecks', 'period_months', 'amount_kopecks']
Money = Annotated[StrictInt, Field(ge=0, le=9_007_199_254_740_991)]
PositiveMoney = Annotated[StrictInt, Field(gt=0, le=9_007_199_254_740_991)]


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    purpose: PurposeCode
    amount_kopecks: PositiveMoney
    term_months: Annotated[StrictInt, Field(ge=1, le=120)]
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
        return self


class PurposeOption(BaseModel):
    code: PurposeCode
    label: str


class OptionsOutput(BaseModel):
    purposes: list[PurposeOption]
    config_version: str


class RecommendationAction(BaseModel):
    kind: Literal['request_field', 'apply_recommendation', 'change_amount']
    label: str
    field: InputField | None = None
    product_code: ProductCode | None = None
    recommendation_id: str | None = None


class RecommendationItem(BaseModel):
    recommendation_id: str
    product_code: ProductCode
    product_name: str
    rank: int
    purpose_match: bool
    recommended_amount_kopecks: int
    term_months: int
    payment_terms: PaymentTerms
    financial_gate: FinancialGate
    client_reasons: list[str]
    reason_codes: list[str]
    required_application_fields: list[ApplicationField]
    required_document_types: list[DocumentType]


class RecommendationResponse(BaseModel):
    status: Literal['ok', 'adjusted', 'request_data', 'no_match']
    message: str
    items: list[RecommendationItem]
    missing_fields: list[InputField]
    actions: list[RecommendationAction]
    config_version: str
    catalog_version: str
    trace_id: str
    staff_trace: list[dict] | None = None
