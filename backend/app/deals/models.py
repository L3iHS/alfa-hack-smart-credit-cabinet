import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Deal(Base):
    __tablename__ = 'deals'
    __table_args__ = (
        CheckConstraint("status IN ('prepared','confirmed','completed','cancelled')", name='valid_deal_status'),
        CheckConstraint("completion_kind IN ('credit','limit','guarantee')", name='valid_deal_completion_kind'),
        CheckConstraint('amount_kopecks > 0 AND term_months > 0', name='positive_deal_terms'),
        CheckConstraint("(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) > 0) "
                        "OR (status != 'cancelled' AND cancelled_at IS NULL AND cancel_reason IS NULL)",
                        name='valid_deal_cancellation'),
        CheckConstraint("(status = 'completed' AND completed_at IS NOT NULL AND confirmed_at IS NOT NULL) "
                        "OR (status != 'completed' AND completed_at IS NULL)", name='valid_deal_completion'),
        CheckConstraint("status != 'confirmed' OR confirmed_at IS NOT NULL", name='valid_deal_confirmation'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('applications.id'), unique=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('application_revisions.id'))
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('decisions.id'))
    offer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('offers.id'))
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('companies.id'))
    company_snapshot: Mapped[dict] = mapped_column(JSONB)
    reference: Mapped[str] = mapped_column(String(80), unique=True)
    product_code: Mapped[str] = mapped_column(String(40))
    product_name: Mapped[str] = mapped_column(String(200))
    completion_kind: Mapped[str] = mapped_column(String(20))
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    term_months: Mapped[int]
    payment_terms: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default='prepared')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(1000))
