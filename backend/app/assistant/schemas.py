from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from app.applications.schemas import Money
from app.products.catalog import CATALOG_VERSION, get_catalog
from app.products.schemas import ProductCode


class AssistantSchema(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class IntakeInput(AssistantSchema):
    text: str = Field(min_length=1, max_length=6000)
    catalog_version: str = CATALOG_VERSION

    @field_validator('text')
    @classmethod
    def text_is_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Опишите потребность')
        return value

    @field_validator('catalog_version')
    @classmethod
    def catalog_exists(cls, value):
        get_catalog(value)
        return value


class SuggestedFields(AssistantSchema):
    product_code: ProductCode | None = None
    amount_kopecks: Money | None = None
    term_months: Annotated[StrictInt, Field(ge=1, le=120)] | None = None
    purpose: str | None = Field(default=None, min_length=1, max_length=2000)


class ExtractedFields(SuggestedFields):
    # Неизвестное название можно безопасно отбросить, не превращая его в код каталога.
    product_code: str | None = Field(default=None, max_length=100)
    term_months: StrictInt | None = None


FieldName = Literal['product_code', 'amount_kopecks', 'term_months', 'purpose']
Quote = Annotated[str, Field(min_length=1, max_length=240)]
Question = Annotated[str, Field(min_length=1, max_length=500)]


class ExtractedIntake(AssistantSchema):
    suggested_fields: ExtractedFields
    evidence: dict[FieldName, Quote]
    questions: list[Question] = Field(max_length=10)
    unsupported_need: StrictBool


class IntakeOutput(AssistantSchema):
    suggested_fields: SuggestedFields
    evidence: dict[FieldName, Quote]
    questions: list[Question] = Field(max_length=14)
    unsupported_need: StrictBool
    model: str
    catalog_version: str


class Source(AssistantSchema):
    id: str
    title: str
    text: str
    version: str


class AnswerOutput(AssistantSchema):
    status: Literal['answered', 'insufficient_context']
    answer: str = Field(min_length=1, max_length=6000)
    sources: list[Source]
    model: str | None
    knowledge_version: str
    application_version: int | None
