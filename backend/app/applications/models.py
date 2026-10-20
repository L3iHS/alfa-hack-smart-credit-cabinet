import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Application(Base):
    __tablename__ = 'applications'
    __table_args__ = (
        CheckConstraint('version > 0', name='positive_application_version'),
        CheckConstraint('amount_kopecks >= 0', name='nonnegative_application_amount'),
        CheckConstraint('term_months > 0', name='positive_application_term'),
        CheckConstraint('revenue_kopecks >= 0', name='nonnegative_application_revenue'),
        CheckConstraint('operating_expenses_kopecks >= 0', name='nonnegative_application_expenses'),
        CheckConstraint('existing_debt_payments_kopecks >= 0', name='nonnegative_application_debt'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('companies.id'), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(30), default='draft')
    catalog_version: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    product_code: Mapped[str] = mapped_column(String(40))
    purpose: Mapped[str | None] = mapped_column(String(2000))
    description: Mapped[str | None] = mapped_column(String(10000))
    amount_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    term_months: Mapped[int | None]
    period_start: Mapped[date | None]
    period_end: Mapped[date | None]
    revenue_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    operating_expenses_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    existing_debt_payments_kopecks: Mapped[int | None] = mapped_column(BigInteger)


class ApplicationEvent(Base):
    __tablename__ = 'application_events'
    __table_args__ = (
        UniqueConstraint('application_id', 'application_version', name='unique_application_event_version'),
        CheckConstraint('application_version > 0', name='positive_event_version'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('applications.id', ondelete='CASCADE'), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    event_type: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    application_version: Mapped[int]
