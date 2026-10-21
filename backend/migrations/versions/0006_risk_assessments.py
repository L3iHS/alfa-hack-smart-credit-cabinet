"""Оценки риска конкретных условий и ручные исключения."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006_risk_assessments'
down_revision = '0005_information_response'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('risk_assessments',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('application_revisions.id'), nullable=False),
        sa.Column('processing_run_id', sa.Uuid(), sa.ForeignKey('processing_runs.id'), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('prediction_scope', sa.String(30), nullable=False),
        sa.Column('context_fingerprint', sa.String(64), nullable=False),
        sa.Column('terms_fingerprint', sa.String(64), nullable=False),
        sa.Column('terms', postgresql.JSONB(), nullable=False),
        sa.Column('offer_version', sa.Integer(), nullable=True),
        sa.Column('scorer_version', sa.String(40), nullable=True),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('reason_code', sa.String(60), nullable=True),
        sa.Column('probability', sa.Float(), nullable=True),
        sa.Column('inputs', postgresql.JSONB(), nullable=True),
        sa.Column('missing_mask', postgresql.JSONB(), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('succeeded','failed','not_applicable')", name='valid_risk_status'),
        sa.CheckConstraint("(status='succeeded' AND probability IS NOT NULL AND probability>=0 AND probability<=1) OR (status<>'succeeded' AND probability IS NULL)", name='valid_risk_probability'))
    for name in ('revision_id','processing_run_id','context_fingerprint'):
        op.create_index('ix_risk_assessments_'+name,'risk_assessments',[name])
    op.create_table('risk_overrides',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('assessment_id',sa.Uuid(),sa.ForeignKey('risk_assessments.id'),nullable=False),
        sa.Column('actor_id',sa.Uuid(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('reason',sa.String(4000),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_risk_overrides_assessment_id','risk_overrides',['assessment_id'])
    for table in ('decisions','offers'):
        op.add_column(table,sa.Column('risk_assessment_id',sa.Uuid(),nullable=True))
        op.create_foreign_key('fk_'+table+'_risk_assessment',table,'risk_assessments',['risk_assessment_id'],['id'])
    op.execute("""CREATE FUNCTION preserve_risk_success() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.status='succeeded' THEN RAISE EXCEPTION 'Successful risk assessment is immutable'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER immutable_risk_success BEFORE UPDATE ON risk_assessments FOR EACH ROW EXECUTE FUNCTION preserve_risk_success()")


def downgrade():
    op.execute('DROP TRIGGER immutable_risk_success ON risk_assessments')
    op.execute('DROP FUNCTION preserve_risk_success()')
    for table in ('decisions','offers'):
        op.drop_constraint('fk_'+table+'_risk_assessment',table,type_='foreignkey')
        op.drop_column(table,'risk_assessment_id')
    op.drop_table('risk_overrides')
    op.drop_table('risk_assessments')
