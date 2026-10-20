import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict


class CompanyOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    inn: str
    name: str
    industry: str
    registered_at: date
