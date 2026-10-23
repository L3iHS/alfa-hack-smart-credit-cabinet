import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.products.schemas import ProductCode


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
