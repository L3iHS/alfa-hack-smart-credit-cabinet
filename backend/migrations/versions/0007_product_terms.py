"""Дополнительные сведения продукта и сохранённые полные условия предложения."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007_product_terms'
down_revision = '0006_risk_assessments'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('applications', sa.Column('tender_number', sa.String(40), nullable=True))
    op.add_column('applications', sa.Column('beneficiary_name', sa.String(200), nullable=True))
    op.add_column('applications', sa.Column('project_description', sa.String(2000), nullable=True))
    op.add_column('offers', sa.Column('payment_terms', postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column('offers', 'payment_terms')
    op.drop_column('applications', 'project_description')
    op.drop_column('applications', 'beneficiary_name')
    op.drop_column('applications', 'tender_number')
