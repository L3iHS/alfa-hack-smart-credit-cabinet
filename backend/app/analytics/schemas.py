import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.processing.schemas import DeclineReason
from app.products.schemas import PaymentTerms, ProductCode


class Observation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: uuid.UUID


class FormOpened(Observation):
    kind: Literal['form_opened']
    journey_id: uuid.UUID
    product_code: ProductCode


class FormStepViewed(Observation):
    kind: Literal['form_step_viewed']
    journey_id: uuid.UUID
    step: Literal['terms', 'finances', 'documents', 'review']


class DraftLinked(Observation):
    kind: Literal['draft_linked']
    journey_id: uuid.UUID
    application_id: uuid.UUID


class OfferViewed(Observation):
    kind: Literal['offer_viewed']
    offer_id: uuid.UUID
    offer_version: Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]


EventInput = Annotated[FormOpened | FormStepViewed | DraftLinked | OfferViewed, Field(discriminator='kind')]


class EventOutput(BaseModel):
    event_id: uuid.UUID
    recorded: Literal[True] = True


# Отчётные схемы отделены от наблюдений: поля и знаменатели доступны в OpenAPI.
OfferOutcome = Literal['accepted', 'declined', 'superseded', 'no_response', 'awaiting_response', 'not_viewed']
FormStep = Literal['terms', 'finances', 'documents', 'review', 'not_observed']
ConditionChange = Literal['amount_only', 'term_only', 'amount_and_term', 'unchanged']
Count = Annotated[int, Field(ge=0)]
Share = Annotated[float, Field(ge=0, le=1)]


class ReportModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ReportMetadata(ReportModel):
    date_from: date
    date_to: date
    timezone: Literal['Europe/Moscow'] = 'Europe/Moscow'
    generated_at: datetime
    outcomes_as_of: datetime
    product_code: ProductCode | None
    no_response_hours: Literal[72] = 72


class FunnelStage(ReportModel):
    key: Literal['opened', 'draft_saved', 'submitted', 'issued', 'viewed', 'responded', 'accepted']
    count: Count
    base_from_first: Count
    base_from_previous: Count
    share_from_first: Share | None
    share_from_previous: Share | None


class ObservationCount(ReportModel):
    count: Count
    base: Count
    share: Share | None


class LastStepCount(ObservationCount):
    step: FormStep


class OfferOutcomeCount(ObservationCount):
    outcome: OfferOutcome


class DeclineReasonCount(ObservationCount):
    reason: DeclineReason | None


class ConditionChangeCount(ReportModel):
    change: ConditionChange
    count: Count
    accepted: Count
    acceptance_share: Share | None


class ResponseCoverage(ReportModel):
    responses_without_prior_view: Count
    response_without_registered_view: Count
    response_viewed_after_response: Count
    response_time_unknown: Count


class AnalyticsSummary(ReportModel):
    metadata: ReportMetadata
    form_funnel: list[FunnelStage]
    offer_funnel: list[FunnelStage]
    last_steps: list[LastStepCount]
    offer_outcomes: list[OfferOutcomeCount]
    declined_after_view: ObservationCount
    response_coverage: ResponseCoverage
    decline_reasons: list[DeclineReasonCount]
    condition_changes: list[ConditionChangeCount]


class CounterofferRow(ReportModel):
    id: uuid.UUID
    application_id: uuid.UUID
    revision_id: uuid.UUID
    company_name: str
    product_code: ProductCode
    created_at: datetime
    original_amount_kopecks: int
    original_term_months: int
    original_monthly_payment_kopecks: int | None
    amount_kopecks: int
    term_months: int
    payment_terms: PaymentTerms
    amount_delta_kopecks: int
    amount_delta_rubles: str
    amount_delta_percent: float | None
    term_delta_months: int
    first_viewed_at: datetime | None
    responded_at: datetime | None
    outcome: OfferOutcome
    decline_reason: DeclineReason | None


class CounterofferPage(ReportModel):
    metadata: ReportMetadata
    items: list[CounterofferRow]
    total: Count
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
