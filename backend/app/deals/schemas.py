import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints, model_validator

from app.products.schemas import PaymentTerms, ProductCode

DealAction = Literal['confirm_deal', 'complete_deal', 'cancel_deal']


class DealOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: Literal['prepared', 'confirmed', 'completed', 'cancelled']
    reference: str
    product_code: ProductCode
    product_name: str
    completion_kind: Literal['credit', 'limit', 'guarantee']
    amount_kopecks: int
    term_months: int
    payment_terms: PaymentTerms
    created_at: datetime
    confirmed_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    available_actions: list[DealAction] = Field(default_factory=list)


class DealCommandInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]


class ConfirmDealInput(DealCommandInput):
    terms_confirmed: StrictBool

    @model_validator(mode='after')
    def require_confirmation(self):
        if not self.terms_confirmed:
            raise ValueError('Подтвердите ознакомление и согласие с условиями')
        return self


class CancelDealInput(DealCommandInput):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
