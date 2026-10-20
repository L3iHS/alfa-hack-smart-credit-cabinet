"""Автоматические проверки, расчёты и результаты рассмотрения."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0004_processing'
down_revision = '0003_submission'
branch_labels = None
depends_on = None

def upgrade():
    # Изменения схемы обработки заявок
    op.create_table('calculations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('revision_id', sa.Uuid(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['revision_id'], ['application_revisions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['processing_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id')
    )
    op.create_table('check_results',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('revision_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('source_version', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['revision_id'], ['application_revisions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['processing_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'kind', name='unique_run_check_kind')
    )
    op.create_index(op.f('ix_check_results_run_id'), 'check_results', ['run_id'], unique=False)
    op.create_table('decisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('revision_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('application_version', sa.Integer(), nullable=False),
    sa.Column('outcome', sa.String(length=30), nullable=False),
    sa.Column('public_reason_codes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('public_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('internal_reason', sa.String(length=4000), nullable=False),
    sa.Column('policy_version', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['revision_id'], ['application_revisions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['processing_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id')
    )
    op.create_index(op.f('ix_decisions_application_id'), 'decisions', ['application_id'], unique=False)
    op.create_table('information_requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('revision_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('application_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('message', sa.String(length=4000), nullable=False),
    sa.Column('requested_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('requested_document_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('response_revision_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('open','answered')", name='valid_information_request_status'),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['response_revision_id'], ['application_revisions.id'], ),
    sa.ForeignKeyConstraint(['revision_id'], ['application_revisions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['processing_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id')
    )
    op.create_index(op.f('ix_information_requests_application_id'), 'information_requests', ['application_id'], unique=False)
    op.create_table('offers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('revision_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('application_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('product_code', sa.String(length=40), nullable=False),
    sa.Column('amount_kopecks', sa.BigInteger(), nullable=False),
    sa.Column('term_months', sa.Integer(), nullable=False),
    sa.Column('monthly_payment_kopecks', sa.BigInteger(), nullable=False),
    sa.Column('total_payment_kopecks', sa.BigInteger(), nullable=False),
    sa.Column('annual_rate_bps', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=4000), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('active','accepted','declined','superseded')", name='valid_offer_status'),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['revision_id'], ['application_revisions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['processing_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id')
    )
    op.create_index(op.f('ix_offers_application_id'), 'offers', ['application_id'], unique=False)
    op.add_column('application_events', sa.Column('actor_type', sa.String(length=10), server_default='user', nullable=False))
    op.add_column('application_events', sa.Column('revision_id', sa.Uuid(), nullable=True))
    op.add_column('application_events', sa.Column('processing_run_id', sa.Uuid(), nullable=True))
    op.alter_column('application_events', 'actor_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.create_foreign_key('fk_event_revision', 'application_events', 'application_revisions', ['revision_id'], ['id'])
    op.create_foreign_key('fk_event_processing_run', 'application_events', 'processing_runs', ['processing_run_id'], ['id'])
    op.add_column('processing_runs', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('processing_runs', sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('processing_runs', sa.Column('error_code', sa.String(length=60), nullable=True))
    op.add_column('processing_runs', sa.Column('attempt', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM application_events WHERE actor_id IS NULL)')):
        raise RuntimeError('Откат невозможен без потери системной истории обработки')
    # Изменения схемы обработки заявок
    op.drop_column('processing_runs', 'attempt')
    op.drop_column('processing_runs', 'error_code')
    op.drop_column('processing_runs', 'finished_at')
    op.drop_column('processing_runs', 'started_at')
    op.drop_constraint('fk_event_processing_run', 'application_events', type_='foreignkey')
    op.drop_constraint('fk_event_revision', 'application_events', type_='foreignkey')
    op.alter_column('application_events', 'actor_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('application_events', 'processing_run_id')
    op.drop_column('application_events', 'revision_id')
    op.drop_column('application_events', 'actor_type')
    op.drop_index(op.f('ix_offers_application_id'), table_name='offers')
    op.drop_table('offers')
    op.drop_index(op.f('ix_information_requests_application_id'), table_name='information_requests')
    op.drop_table('information_requests')
    op.drop_index(op.f('ix_decisions_application_id'), table_name='decisions')
    op.drop_table('decisions')
    op.drop_index(op.f('ix_check_results_run_id'), table_name='check_results')
    op.drop_table('check_results')
    op.drop_table('calculations')
