import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

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


class ExtractedFields(AssistantSchema):
    # Все ключи обязательны для строгого транспорта; неизвестный факт обозначается null.
    product_code: str | None = Field(max_length=100)
    amount_kopecks: Money | None
    term_months: StrictInt | None
    purpose: str | None = Field(min_length=1, max_length=2000)


FieldName = Literal['product_code', 'amount_kopecks', 'term_months', 'purpose']
Quote = Annotated[str, Field(min_length=1, max_length=240)]
Question = Annotated[str, Field(min_length=1, max_length=500)]


class ExtractedEvidence(AssistantSchema):
    product_code: Quote | None
    amount_kopecks: Quote | None
    term_months: Quote | None
    purpose: Quote | None


class ExtractedIntake(AssistantSchema):
    suggested_fields: ExtractedFields
    evidence: ExtractedEvidence
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


class ChatInput(AssistantSchema):
    question: str = Field(min_length=1, max_length=2000)
    application_id: uuid.UUID | None = Field(default=None, strict=False)
    expected_version: Annotated[StrictInt, Field(ge=1, le=2_147_483_647)] | None = None

    @field_validator('question')
    @classmethod
    def question_is_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Введите вопрос')
        return value

    @model_validator(mode='after')
    def application_requires_version(self):
        if (self.application_id is None) != (self.expected_version is None):
            raise ValueError('Укажите заявку вместе с её версией')
        return self


class GeneratedAnswer(AssistantSchema):
    answer: str = Field(min_length=1, max_length=6000)
    source_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(min_length=1, max_length=50)

    @field_validator('answer')
    @classmethod
    def answer_is_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Ответ пуст')
        return value
