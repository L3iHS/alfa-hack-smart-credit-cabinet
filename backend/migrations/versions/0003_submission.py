"""Документы, неизменяемые отправки и ожидающие запуски обработки."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003_submission'
down_revision = '0002_application_drafts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'documents',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('author_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('document_type', sa.String(40), nullable=False),
        sa.Column('filename', sa.String(200), nullable=False),
        sa.Column('storage_key', sa.String(36), nullable=False, unique=True),
        sa.Column('content_type', sa.String(50), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_documents_application_id', 'documents', ['application_id'])
    op.create_table(
        'application_revisions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('application_version', sa.Integer(), nullable=False),
        sa.Column('submitted_by', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint('application_id', 'application_version', name='unique_application_revision_version'),
    )
    op.create_index('ix_application_revisions_application_id', 'application_revisions', ['application_id'])
    op.create_table(
        'processing_runs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('application_revisions.id'), nullable=False, unique=True),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('catalog_version', sa.String(30), nullable=False),
        sa.Column('policy_version', sa.String(40), nullable=False),
        sa.Column('source_version', sa.String(40), nullable=False),
        sa.Column('scorer_version', sa.String(40)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','running','succeeded','failed','interrupted')", name='valid_processing_status'),
    )
    op.create_index('ix_processing_runs_application_id', 'processing_runs', ['application_id'])
    op.create_table(
        'idempotency_records',
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('operation', sa.String(40), primary_key=True),
        sa.Column('key', sa.Uuid(), primary_key=True),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('response', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table('idempotency_records')
    op.drop_table('processing_runs')
    op.drop_table('application_revisions')
    op.drop_table('documents')
