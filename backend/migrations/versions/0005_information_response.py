"""Сохранение ответа клиента на запрос уточнений."""
from alembic import op
import sqlalchemy as sa

revision = '0005_information_response'
down_revision = '0004_processing'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('information_requests', sa.Column('response_message', sa.String(4000), nullable=True))
    op.add_column('information_requests', sa.Column('responded_by', sa.Uuid(), nullable=True))
    op.add_column('information_requests', sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_information_response_user', 'information_requests', 'users', ['responded_by'], ['id'])


def downgrade():
    op.drop_constraint('fk_information_response_user', 'information_requests', type_='foreignkey')
    op.drop_column('information_requests', 'responded_at')
    op.drop_column('information_requests', 'responded_by')
    op.drop_column('information_requests', 'response_message')
