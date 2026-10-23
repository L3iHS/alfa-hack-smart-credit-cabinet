from typing import Literal

from pydantic import BaseModel, ConfigDict

ProductCode = Literal['working_capital', 'equipment', 'overdraft', 'credit_line', 'investment', 'tender_guarantee']
DocumentType = Literal['financial_statement', 'equipment_invoice', 'bank_statement', 'business_plan', 'tender_document']
PaymentKind = Literal['annuity', 'revolving', 'guarantee']
ApplicationField = Literal['tender_number', 'beneficiary_name', 'project_description']


class ProductOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ProductCode
    name: str
    purpose_description: str
    min_amount_kopecks: int
    max_amount_kopecks: int
    min_term_months: int
    max_term_months: int
    annual_rate_bps: int | None
    required_document_types: tuple[DocumentType, ...]
    payment_kind: PaymentKind = 'annuity'
    upfront_fee_bps: int = 0
    annual_commission_bps: int = 0
    required_application_fields: tuple[ApplicationField, ...] = ()


class PaymentTerms(BaseModel):
    model_config = ConfigDict(frozen=True)

    payment_kind: PaymentKind
    amount_kopecks: int
    term_months: int
    annual_rate_bps: int | None
    annual_commission_bps: int
    monthly_payment_kopecks: int | None
    upfront_fee_kopecks: int
    principal_due_at_end_kopecks: int
    last_payment_kopecks: int
    total_payment_kopecks: int
    total_cost_kopecks: int
    assessment_monthly_burden_kopecks: int | None
    contingent_liability_kopecks: int
    assumptions: tuple[str, ...]


class CatalogOutput(BaseModel):
    catalog_version: str
    items: list[ProductOutput]
