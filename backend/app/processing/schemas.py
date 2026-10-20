import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.products.schemas import ProductCode, DocumentType

ApplicationStatus = Literal['draft', 'submitted', 'processing', 'needs_info', 'manual_review', 'counteroffer', 'approved', 'rejected']
ProcessingStatus = Literal['pending', 'running', 'succeeded', 'failed', 'interrupted']
Action = Literal['edit_draft', 'upload_document', 'submit', 'respond_information', 'accept_offer', 'decline_offer', 'request_information', 'make_offer', 'approve', 'reject', 'retry_processing']
Outcome = Literal['needs_info', 'manual_review', 'counteroffer', 'approved', 'rejected']


class InformationRequestOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    revision_id: uuid.UUID
    application_version: int
    status: Literal['open', 'answered']
    message: str
    requested_fields: list[str]
    requested_document_types: list[DocumentType]
    created_at: datetime
    response_message: str | None = None
    responded_by: uuid.UUID | None = None
    responded_at: datetime | None = None
    response_revision_id: uuid.UUID | None = None


class OfferTerms(BaseModel):
    product_code: ProductCode
    amount_kopecks: int
    term_months: int
    monthly_payment_kopecks: int
    total_payment_kopecks: int
    annual_rate_bps: int


class OfferOutput(OfferTerms):
    version: int
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    revision_id: uuid.UUID
    application_version: int
    status: Literal['active', 'accepted', 'declined', 'superseded']
    reason: str
    created_at: datetime


class CalculationOutput(BaseModel):
    months: int
    monthly_revenue_kopecks: str
    monthly_operating_expenses_kopecks: str
    monthly_debt_kopecks: str
    available_flow_kopecks: str
    monthly_payment_kopecks: int
    coverage_ratio: str | None
    policy_version: str


class RegistryData(BaseModel):
    registered_at: str
    liquidated: bool


class TaxData(BaseModel):
    expected_monthly_revenue_kopecks: int | None


class BkiData(BaseModel):
    overdue_days: int


class CheckOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: Literal['registry', 'tax', 'bki']
    source_version: str
    status: Literal['succeeded']
    data: RegistryData | TaxData | BkiData
    created_at: datetime


class DecisionOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    outcome: Outcome
    public_reason_codes: list[str]
    public_reasons: list[str]
    internal_reason: str
    created_at: datetime


class RunOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    revision_id: uuid.UUID
    status: ProcessingStatus
    catalog_version: str
    policy_version: str
    source_version: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    checks: list[CheckOutput] = Field(default_factory=list)
    calculation: CalculationOutput | None = None
    decision: DecisionOutput | None = None


class AssessmentOutput(BaseModel):
    application_id: uuid.UUID
    revision_id: uuid.UUID | None
    runs: list[RunOutput]
    risk_assessment: None = None


class RetryInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]


class RetryOutput(BaseModel):
    application_id: uuid.UUID
    version: int
    status: ApplicationStatus
    revision_id: uuid.UUID
    processing_run_id: uuid.UUID


class PolicyResult(BaseModel):
    outcome: Outcome
    reason_code: str
    reason: str
    calculation: CalculationOutput | None = None
    offer: OfferTerms | None = None
    requested_fields: list[str] = Field(default_factory=list)
