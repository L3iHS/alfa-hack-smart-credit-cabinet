import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.products.schemas import ProductCode

Money = Annotated[StrictInt, Field(ge=0, le=9_007_199_254_740_991)]
Months = Annotated[StrictInt, Field(ge=1, le=36)]


class DraftFields(BaseModel):
    model_config = ConfigDict(extra='forbid', from_attributes=True)

    product_code: ProductCode
    purpose: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=10000)
    amount_kopecks: Money | None = None
    term_months: Months | None = None
    period_start: date | None = None
    period_end: date | None = None
    revenue_kopecks: Money | None = None
    operating_expenses_kopecks: Money | None = None
    existing_debt_payments_kopecks: Money | None = None


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
    version: int
    status: Literal['draft']
    updated_at: datetime
    catalog_version: str
    public_reasons: list[str] = Field(default_factory=list)
    available_actions: list[Literal['edit_draft']] = Field(default_factory=lambda: ['edit_draft'])


class EventOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: Literal['draft_created', 'draft_updated']
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
