import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ApplicationSummary(Base):
    __tablename__ = 'application_summaries'

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('applications.id', ondelete='CASCADE'), primary_key=True)
    application_version: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response: Mapped[dict] = mapped_column(JSONB)
