import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def now():
    return datetime.now(timezone.utc)


class CheckResult(Base):
    __tablename__ = 'check_results'
    __table_args__ = (UniqueConstraint('run_id', 'kind', name='unique_run_check_kind'),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('processing_runs.id'), index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('application_revisions.id'))
    kind: Mapped[str] = mapped_column(String(30))
    source_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default='succeeded')
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Calculation(Base):
    __tablename__ = 'calculations'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('processing_runs.id'), unique=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('application_revisions.id'))
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Decision(Base):
    __tablename__ = 'decisions'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('applications.id'), index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('application_revisions.id'))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('processing_runs.id'), unique=True)
    risk_assessment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('risk_assessments.id'))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    application_version: Mapped[int]
    outcome: Mapped[str] = mapped_column(String(30))
    public_reason_codes: Mapped[list] = mapped_column(JSONB)
    public_reasons: Mapped[list] = mapped_column(JSONB)
    internal_reason: Mapped[str] = mapped_column(String(4000))
    policy_version: Mapped[str] = mapped_column(String(40))
    payment_terms: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InformationRequest(Base):
    __tablename__ = 'information_requests'
    __table_args__ = (CheckConstraint("status IN ('open','answered')", name='valid_information_request_status'),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('applications.id'), index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('application_revisions.id'))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('processing_runs.id'), unique=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    application_version: Mapped[int]
    status: Mapped[str] = mapped_column(String(30), default='open')
    message: Mapped[str] = mapped_column(String(4000))
    requested_fields: Mapped[list] = mapped_column(JSONB)
    requested_document_types: Mapped[list] = mapped_column(JSONB)
    response_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('application_revisions.id'))
    response_message: Mapped[str | None] = mapped_column(String(4000))
    responded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Offer(Base):
    __tablename__ = 'offers'
    __table_args__ = (
        CheckConstraint("status IN ('active','accepted','declined','superseded')", name='valid_offer_status'),
        CheckConstraint("decline_reason IS NULL OR (status = 'declined' AND decline_reason IN "
                        "('insufficient_amount','high_payment','unsuitable_term','no_longer_needed','other'))",
                        name='valid_offer_decline_reason'),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('applications.id'), index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('application_revisions.id'))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('processing_runs.id'), unique=True)
    risk_assessment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('risk_assessments.id'))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    version: Mapped[int] = mapped_column(default=1, server_default='1')
    application_version: Mapped[int]
    status: Mapped[str] = mapped_column(String(30), default='active')
    product_code: Mapped[str] = mapped_column(String(40))
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    term_months: Mapped[int]
    monthly_payment_kopecks: Mapped[int] = mapped_column(BigInteger)
    total_payment_kopecks: Mapped[int] = mapped_column(BigInteger)
    payment_terms: Mapped[dict | None] = mapped_column(JSONB)
    annual_rate_bps: Mapped[int]
    reason: Mapped[str] = mapped_column(String(4000))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decline_reason: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
