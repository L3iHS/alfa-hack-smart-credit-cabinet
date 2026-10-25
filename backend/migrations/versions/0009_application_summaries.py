"""Постоянные номера заявок и сохранённые сводки."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009_application_summaries'
down_revision = '0008_product_analytics'
branch_labels = None
depends_on = None


def upgrade():
    # DDL удерживает блокировку до завершения заполнения, включая переключение sequence.
    op.execute('CREATE SEQUENCE application_number_seq AS bigint')
    op.add_column('applications', sa.Column('number', sa.BigInteger(), nullable=True))
    op.execute('''WITH numbered AS (
        SELECT id, row_number() OVER (ORDER BY created_at, id) AS number FROM applications
    ) UPDATE applications SET number = numbered.number FROM numbered WHERE applications.id = numbered.id''')
    op.execute("SELECT setval('application_number_seq', COALESCE(MAX(number), 1), COUNT(*) > 0) FROM applications")
    op.alter_column('applications', 'number', nullable=False,
                    server_default=sa.text("nextval('application_number_seq')"))
    op.execute('ALTER SEQUENCE application_number_seq OWNED BY applications.number')
    op.create_unique_constraint('unique_application_number', 'applications', ['number'])
    op.create_check_constraint('positive_application_number', 'applications', 'number > 0')
    op.create_table('application_summaries',
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('application_version', sa.Integer(), primary_key=True),
        sa.Column('fingerprint', sa.String(64), primary_key=True),
        sa.Column('request_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('response', postgresql.JSONB(), nullable=False))


def downgrade():
    op.drop_table('application_summaries')
    op.drop_column('applications', 'number')
    # OWNED BY удаляет sequence вместе с колонкой.
