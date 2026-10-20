from typing import Literal

from pydantic import BaseModel, ConfigDict

ProductCode = Literal['working_capital', 'equipment']
DocumentType = Literal['financial_statement', 'equipment_invoice']


class ProductOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ProductCode
    name: str
    purpose_description: str
    min_amount_kopecks: int
    max_amount_kopecks: int
    min_term_months: int
    max_term_months: int
    annual_rate_bps: int
    required_document_types: tuple[DocumentType, ...]


class CatalogOutput(BaseModel):
    catalog_version: str
    items: list[ProductOutput]
