import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def now():
    return datetime.now(timezone.utc)


class AnalyticsJourney(Base):
    __tablename__ = 'analytics_journeys'
    __table_args__ = (
        CheckConstraint("product_code IN ('working_capital','equipment','overdraft','credit_line','investment','tender_guarantee')",
                        name='valid_analytics_journey_product'),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    product_code: Mapped[str] = mapped_column(String(40))
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('applications.id'), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class AnalyticsEvent(Base):
    __tablename__ = 'analytics_events'
    __table_args__ = (
        CheckConstraint("kind IN ('form_opened','form_step_viewed','draft_linked','offer_viewed')", name='valid_analytics_event_kind'),
        CheckConstraint("(kind = 'offer_viewed' AND offer_id IS NOT NULL AND offer_version IS NOT NULL AND offer_version > 0 AND journey_id IS NULL) OR "
                        "(kind <> 'offer_viewed' AND journey_id IS NOT NULL AND offer_id IS NULL AND offer_version IS NULL)",
                        name='valid_analytics_event_subject'),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    journey_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('analytics_journeys.id'), index=True)
    offer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('offers.id'), index=True)
    offer_version: Mapped[int | None]
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
