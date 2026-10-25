import uuid
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.orm import Session

from conftest import application_url


def test_upgrade_preserves_old_offer_and_stores_full_new_terms(db, monkeypatch):
    from app.applications.models import Application
    from app.applications.submission_models import ApplicationRevision
    from app.auth.models import User
    from app.core.config import settings
    from app.processing.models import Offer
    from app.seed import seed

    name = f'product_terms_{uuid.uuid4().hex}'
    admin = create_engine(application_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = application_url.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    try:
        with monkeypatch.context() as context:
            context.setattr(settings, 'database_url', url)
            command.upgrade(config, '0006_risk_assessments')
            with Session(engine) as session:
                seed(session)
                user = session.scalar(select(User).where(User.email == 'client1@example.test'))
                application_id, revision_id, offer_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                stamp = datetime.now(timezone.utc)
                # Отражаем старую схему без defaults и sequence из текущей ORM-модели.
                legacy_applications = Table('applications', MetaData(), autoload_with=session.connection())
                session.execute(legacy_applications.insert().values(
                    id=application_id, company_id=user.company_id, author_id=user.id,
                    version=1, status='draft', created_at=stamp, updated_at=stamp,
                    catalog_version='demo-v1', product_code='equipment'))
                session.execute(ApplicationRevision.__table__.insert().values(
                    id=revision_id, application_id=application_id, application_version=1,
                    submitted_by=user.id, created_at=stamp, snapshot={}))
                session.execute(Offer.__table__.insert().values(
                    id=offer_id, application_id=application_id, revision_id=revision_id,
                    application_version=1, product_code='equipment', amount_kopecks=200_000_000,
                    term_months=24, monthly_payment_kopecks=10_574_220,
                    total_payment_kopecks=253_781_280, annual_rate_bps=2400, reason='Старое предложение'))
                session.commit()
                before = session.execute(text('SELECT to_jsonb(o) FROM offers o WHERE id=:id'), {'id': offer_id}).scalar_one()
            command.upgrade(config, 'head')
            command.check(config)
            with Session(engine) as session:
                after = session.execute(text('SELECT to_jsonb(o) FROM offers o WHERE id=:id'), {'id': offer_id}).scalar_one()
                assert after == before | {'payment_terms': None, 'responded_at': None, 'decline_reason': None}
                application = session.get(Application, application_id)
                assert (application.tender_number, application.beneficiary_name, application.project_description) == (None, None, None)
                application.tender_number = 'Т-100'
                application.beneficiary_name = 'Демонстрационный заказчик'
                application.project_description = 'Развитие производства'
                from app.products.calculations import calculate_terms
                from app.products.catalog import get_product
                terms = calculate_terms(get_product('tender_guarantee', 'demo-v2'), 100_000_000, 12)
                offer = session.get(Offer, offer_id)
                offer.payment_terms = terms.model_dump(mode='json')
                session.commit()
                session.expire_all()
                assert session.get(Offer, offer_id).payment_terms == terms.model_dump(mode='json')
                assert session.get(Application, application_id).tender_number == 'Т-100'
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
