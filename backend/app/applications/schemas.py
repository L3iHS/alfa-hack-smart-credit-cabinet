import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.products.schemas import ProductCode
from app.processing.schemas import ApplicationStatus, ProcessingStatus, Action, InformationRequestOutput, OfferOutput

Money = Annotated[StrictInt, Field(ge=0, le=9_007_199_254_740_991)]
Months = Annotated[StrictInt, Field(ge=1, le=120)]


class DraftFields(BaseModel):
    model_config = ConfigDict(extra='forbid', from_attributes=True)

    product_code: ProductCode
    purpose: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=10000)
    tender_number: str | None = Field(default=None, max_length=40)
    beneficiary_name: str | None = Field(default=None, max_length=200)
    project_description: str | None = Field(default=None, max_length=2000)
    amount_kopecks: Money | None = None
    term_months: Months | None = None
    period_start: date | None = None
    period_end: date | None = None
    revenue_kopecks: Money | None = None
    operating_expenses_kopecks: Money | None = None
    existing_debt_payments_kopecks: Money | None = None

    @field_validator('tender_number', 'beneficiary_name', 'project_description', mode='before')
    @classmethod
    def normalize_product_fields(cls, value):
        return value.strip() or None if isinstance(value, str) else value


class DraftCreate(DraftFields):
    pass


class DraftPatch(DraftFields):
    # None обозначает только отсутствие поля; явный null отклоняет валидатор.
    product_code: ProductCode | SkipJsonSchema[None] = None
    expected_version: Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]

    @model_validator(mode='after')
    def product_cannot_be_cleared(self):
        if 'product_code' in self.model_fields_set and self.product_code is None:
            raise ValueError('Выберите продукт')
        return self


class ApplicationOutput(DraftFields):
    id: uuid.UUID
    display_number: str
    version: int
    status: ApplicationStatus
    updated_at: datetime
    catalog_version: str
    public_reasons: list[str] = Field(default_factory=list)
    processing_status: ProcessingStatus | None = None
    information_requests: list[InformationRequestOutput] = Field(default_factory=list)
    offers: list[OfferOutput] = Field(default_factory=list)
    available_actions: list[Action] = Field(default_factory=list)


class EventOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_type: Literal['user', 'system']
    actor_id: uuid.UUID | None
    revision_id: uuid.UUID | None
    processing_run_id: uuid.UUID | None
    event_type: str
    created_at: datetime
    application_version: int


class ApplicationPage(BaseModel):
    items: list[ApplicationOutput]
    total: int
    limit: int
    offset: int


class EventPage(BaseModel):
    items: list[EventOutput]
    total: int
    limit: int
    offset: int


class SubmissionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_version: Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]
    data_confirmed: StrictBool
    bki_consent: StrictBool
    consent_version: str = Field(min_length=1, max_length=40)


class SubmissionOutput(BaseModel):
    application_id: uuid.UUID
    version: int
    status: Literal['submitted']
    revision_id: uuid.UUID
    processing_run_id: uuid.UUID
