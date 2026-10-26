"""Снимок кредитного решения и отдельное демонстрационное оформление."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0010_deals'
down_revision = '0009_application_summaries'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('decisions', sa.Column('payment_terms', postgresql.JSONB(), nullable=True))
    op.create_table('deals',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id'), nullable=False, unique=True),
        sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('application_revisions.id'), nullable=False),
        sa.Column('decision_id', sa.Uuid(), sa.ForeignKey('decisions.id'), nullable=False),
        sa.Column('offer_id', sa.Uuid(), sa.ForeignKey('offers.id'), nullable=True),
        sa.Column('company_id', sa.Uuid(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('company_snapshot', postgresql.JSONB(), nullable=False),
        sa.Column('reference', sa.String(80), nullable=False, unique=True),
        sa.Column('product_code', sa.String(40), nullable=False),
        sa.Column('product_name', sa.String(200), nullable=False),
        sa.Column('completion_kind', sa.String(20), nullable=False),
        sa.Column('amount_kopecks', sa.BigInteger(), nullable=False),
        sa.Column('term_months', sa.Integer(), nullable=False),
        sa.Column('payment_terms', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_reason', sa.String(1000), nullable=True),
        sa.CheckConstraint("status IN ('prepared','confirmed','completed','cancelled')", name='valid_deal_status'),
        sa.CheckConstraint("completion_kind IN ('credit','limit','guarantee')", name='valid_deal_completion_kind'),
        sa.CheckConstraint('amount_kopecks > 0 AND term_months > 0', name='positive_deal_terms'),
        sa.CheckConstraint("(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) > 0) "
                           "OR (status != 'cancelled' AND cancelled_at IS NULL AND cancel_reason IS NULL)", name='valid_deal_cancellation'),
        sa.CheckConstraint("(status = 'completed' AND completed_at IS NOT NULL AND confirmed_at IS NOT NULL) "
                           "OR (status != 'completed' AND completed_at IS NULL)", name='valid_deal_completion'),
        sa.CheckConstraint("status != 'confirmed' OR confirmed_at IS NOT NULL", name='valid_deal_confirmation'))


def downgrade():
    op.drop_table('deals')
    op.drop_column('decisions', 'payment_terms')
