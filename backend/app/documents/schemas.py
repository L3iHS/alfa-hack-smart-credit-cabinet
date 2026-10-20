import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.products.schemas import DocumentType


class DocumentOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: DocumentType
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentOutput]


class UploadedDocument(BaseModel):
    document: DocumentOutput
    application_version: int


class DeletedDocument(BaseModel):
    application_version: int
