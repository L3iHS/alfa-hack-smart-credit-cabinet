import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ApplicationRevision(Base):
    __tablename__ = 'application_revisions'
    __table_args__ = (
        UniqueConstraint('application_id', 'application_version', name='unique_application_revision_version'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('applications.id'), index=True)
    application_version: Mapped[int]
    submitted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict] = mapped_column(JSONB)


class ProcessingRun(Base):
    __tablename__ = 'processing_runs'
    __table_args__ = (
        CheckConstraint("status IN ('pending','running','succeeded','failed','interrupted')", name='valid_processing_status'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('applications.id'), index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('application_revisions.id'), unique=True)
    status: Mapped[str] = mapped_column(String(30), default='pending')
    catalog_version: Mapped[str] = mapped_column(String(30))
    policy_version: Mapped[str] = mapped_column(String(40))
    source_version: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(60))
    attempt: Mapped[int] = mapped_column(default=0, server_default='0')
    scorer_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class IdempotencyRecord(Base):
    __tablename__ = 'idempotency_records'

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), primary_key=True)
    operation: Mapped[str] = mapped_column(String(40), primary_key=True)
    key: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
