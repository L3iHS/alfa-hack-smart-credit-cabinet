import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class UserOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["client", "staff"]
    company_id: uuid.UUID | None
    display_name: str


class CsrfOutput(BaseModel):
    csrf_token: str


class LoginOutput(BaseModel):
    user: UserOutput
    csrf_token: str


class ErrorOutput(BaseModel):
    code: str
    message: str
    field_errors: dict[str, str] | None = None
