"""Неизменяемые оценки и основания ручных исключений."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RiskAssessment(Base):
    __tablename__ = 'risk_assessments'
    __table_args__ = (
        CheckConstraint("status IN ('succeeded','failed','not_applicable')", name='valid_risk_status'),
        CheckConstraint("(status='succeeded' AND probability IS NOT NULL AND probability>=0 AND probability<=1) OR (status<>'succeeded' AND probability IS NULL)", name='valid_risk_probability'),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('application_revisions.id'), index=True)
    processing_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('processing_runs.id'), index=True)
    attempt: Mapped[int]
    prediction_scope: Mapped[str] = mapped_column(String(30))
    context_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    terms_fingerprint: Mapped[str] = mapped_column(String(64))
    terms: Mapped[dict] = mapped_column(JSONB)
    offer_version: Mapped[int | None]
    scorer_version: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))
    reason_code: Mapped[str | None] = mapped_column(String(60))
    probability: Mapped[float | None] = mapped_column(Float)
    inputs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    missing_mask: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RiskOverride(Base):
    __tablename__ = 'risk_overrides'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('risk_assessments.id'), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    reason: Mapped[str] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
