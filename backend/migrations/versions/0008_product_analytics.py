"""Наблюдения пути клиента и атомарные сведения об ответе на предложение."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008_product_analytics'
down_revision = '0007_product_terms'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('offers', sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('offers', sa.Column('decline_reason', sa.String(30), nullable=True))
    op.create_check_constraint('valid_offer_decline_reason', 'offers',
                               "decline_reason IS NULL OR (status = 'declined' AND decline_reason IN "
                               "('insufficient_amount','high_payment','unsuitable_term','no_longer_needed','other'))")
    op.create_table('analytics_journeys',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('product_code', sa.String(40), nullable=False),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id'), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("product_code IN ('working_capital','equipment','overdraft','credit_line','investment','tender_guarantee')",
                           name='valid_analytics_journey_product'))
    op.create_index('ix_analytics_journeys_user_id', 'analytics_journeys', ['user_id'])
    op.create_index('ix_analytics_journeys_created_at', 'analytics_journeys', ['created_at'])
    op.create_table('analytics_events',
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('event_id', sa.Uuid(), primary_key=True),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('journey_id', sa.Uuid(), sa.ForeignKey('analytics_journeys.id'), nullable=True),
        sa.Column('offer_id', sa.Uuid(), sa.ForeignKey('offers.id'), nullable=True),
        sa.Column('offer_version', sa.Integer(), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('form_opened','form_step_viewed','draft_linked','offer_viewed')", name='valid_analytics_event_kind'),
        sa.CheckConstraint("(kind = 'offer_viewed' AND offer_id IS NOT NULL AND offer_version IS NOT NULL AND offer_version > 0 AND journey_id IS NULL) OR "
                           "(kind <> 'offer_viewed' AND journey_id IS NOT NULL AND offer_id IS NULL AND offer_version IS NULL)",
                           name='valid_analytics_event_subject'))
    for column in ('journey_id', 'offer_id', 'created_at'):
        op.create_index(f'ix_analytics_events_{column}', 'analytics_events', [column])


def downgrade():
    op.drop_table('analytics_events')
    op.drop_table('analytics_journeys')
    op.drop_constraint('valid_offer_decline_reason', 'offers', type_='check')
    op.drop_column('offers', 'decline_reason')
    op.drop_column('offers', 'responded_at')
