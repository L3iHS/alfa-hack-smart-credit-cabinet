import uuid
from typing import Literal

from pydantic import BaseModel, Field


class RiskTerms(BaseModel):
    product_code: str
    amount_kopecks: int
    term_months: int
    annual_rate_bps: int


class RiskContributionOutput(BaseModel):
    feature_name: str
    label: str
    contribution: float


class RiskAssessmentOutput(BaseModel):
    assessment_id: uuid.UUID
    revision_id: uuid.UUID
    processing_run_id: uuid.UUID
    status: Literal['succeeded', 'failed', 'not_applicable']
    reason_code: str | None
    scorer_kind: str = 'model'
    scorer_version: str | None
    feature_schema_version: str | None = None
    target_event: str = 'loan_90dpd_12m'
    horizon_months: int = 12
    data_kind: str = 'synthetic'
    prediction_scope: Literal['requested_terms','offered_terms']
    offer_version: int | None
    terms_fingerprint: str
    terms: RiskTerms
    probability: float | None
    risk_band: Literal['low','elevated','high'] | None = None
    explanation_method: str | None = None
    explanation_scale: str | None = None
    base_value: float | None = None
    raw_prediction: float | None = None
    contributions: list[RiskContributionOutput] = Field(default_factory=list)
    top_increasing_factors: list[RiskContributionOutput] = Field(default_factory=list)
    top_decreasing_factors: list[RiskContributionOutput] = Field(default_factory=list)
