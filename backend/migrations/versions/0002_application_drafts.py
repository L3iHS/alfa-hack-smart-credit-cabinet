"""Черновики заявок и события их изменения."""
from alembic import op
import sqlalchemy as sa

revision = '0002_application_drafts'
down_revision = '0001_identity'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'applications',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('company_id', sa.Uuid(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('author_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('catalog_version', sa.String(30), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('product_code', sa.String(40), nullable=False),
        sa.Column('purpose', sa.String(2000)),
        sa.Column('description', sa.String(10000)),
        sa.Column('amount_kopecks', sa.BigInteger()),
        sa.Column('term_months', sa.Integer()),
        sa.Column('period_start', sa.Date()),
        sa.Column('period_end', sa.Date()),
        sa.Column('revenue_kopecks', sa.BigInteger()),
        sa.Column('operating_expenses_kopecks', sa.BigInteger()),
        sa.Column('existing_debt_payments_kopecks', sa.BigInteger()),
        sa.CheckConstraint('version > 0', name='positive_application_version'),
        sa.CheckConstraint('amount_kopecks >= 0', name='nonnegative_application_amount'),
        sa.CheckConstraint('term_months > 0', name='positive_application_term'),
        sa.CheckConstraint('revenue_kopecks >= 0', name='nonnegative_application_revenue'),
        sa.CheckConstraint('operating_expenses_kopecks >= 0', name='nonnegative_application_expenses'),
        sa.CheckConstraint('existing_debt_payments_kopecks >= 0', name='nonnegative_application_debt'),
    )
    op.create_index('ix_applications_company_id', 'applications', ['company_id'])
    op.create_table(
        'application_events',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('application_version', sa.Integer(), nullable=False),
        sa.UniqueConstraint('application_id', 'application_version', name='unique_application_event_version'),
        sa.CheckConstraint('application_version > 0', name='positive_event_version'),
    )
    op.create_index('ix_application_events_application_id', 'application_events', ['application_id'])


def downgrade():
    op.drop_table('application_events')
    op.drop_table('applications')
