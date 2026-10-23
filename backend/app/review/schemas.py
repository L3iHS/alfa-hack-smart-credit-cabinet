import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

from app.applications.schemas import Money, Months, SubmissionInput
from app.processing.schemas import DeclineReason, ApplicationStatus, InformationRequestOutput, OfferOutput
from app.products.schemas import DocumentType

Version = Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]
Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
RequestedField = Literal['purpose', 'description', 'amount_kopecks', 'term_months', 'period_start', 'period_end',
                         'revenue_kopecks', 'operating_expenses_kopecks', 'existing_debt_payments_kopecks',
                         'tender_number', 'beneficiary_name', 'project_description']


class CommandInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: Version


class InformationRequestInput(CommandInput):
    message: Message
    requested_fields: list[RequestedField] = Field(default_factory=list, max_length=12)
    requested_document_types: list[DocumentType] = Field(default_factory=list, max_length=5)

    @model_validator(mode='after')
    def require_requested_items(self):
        if not self.requested_fields and not self.requested_document_types:
            raise ValueError('Укажите запрошенные поля или документы')
        if len(set(self.requested_fields)) != len(self.requested_fields) or len(set(self.requested_document_types)) != len(self.requested_document_types):
            raise ValueError('Запрошенные сведения не должны повторяться')
        return self


class InformationResponseInput(SubmissionInput):
    request_id: uuid.UUID
    message: Message


class CreateOfferInput(CommandInput):
    risk_acknowledged: bool = False
    amount_kopecks: Money
    term_months: Months
    reason: Message


class DecisionInput(CommandInput):
    risk_acknowledged: bool = False
    outcome: Literal['approved', 'rejected']
    reason: Message


class OfferActionInput(CommandInput):
    offer_version: Version


class DeclineOfferInput(OfferActionInput):
    decline_reason: DeclineReason | None = None


class CommandOutput(BaseModel):
    application_id: uuid.UUID
    version: int
    status: ApplicationStatus
    revision_id: uuid.UUID


class InformationRequestCommandOutput(CommandOutput):
    information_request: InformationRequestOutput


class OfferCommandOutput(CommandOutput):
    offer: OfferOutput


class DecisionCommandOutput(CommandOutput):
    decision_id: uuid.UUID
