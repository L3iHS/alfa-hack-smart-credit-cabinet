import uuid

import pytest
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.orm import sessionmaker

from conftest import application_url


@pytest.mark.parametrize('profile', ['a','b'])
@pytest.mark.parametrize('policy_version', ['demo-policy-v1','demo-policy-0.2'])
def test_upgrade_keeps_legacy_submission_and_retries_it(db, monkeypatch, policy_version, profile):
    from app.applications.models import Application
    from app.applications.submission_models import ApplicationRevision, ProcessingRun
    from app.auth.models import User
    from app.companies.models import Company
    from app.core.config import settings
    from app.demo.profiles import application_fields
    from app.processing import service
    from app.processing.schemas import RetryInput
    from app.seed import seed

    name = f'legacy_credit_{uuid.uuid4().hex}'
    admin = create_engine(application_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    legacy_url = application_url.set(database=name).render_as_string(hide_password=False)
    legacy_engine = create_engine(legacy_url)
    config = Config(str(Path(__file__).parents[1]/'alembic.ini'))
    try:
        with monkeypatch.context() as context:
            context.setattr(settings,'database_url',legacy_url)
            command.upgrade(config,'0003_submission')
            factory = sessionmaker(bind=legacy_engine, expire_on_commit=False)
            with factory() as legacy:
                seed(legacy)
                user = legacy.scalar(select(User).where(User.email=='client1@example.test'))
                company = legacy.get(Company,user.company_id)
                password = user.password_hash
                # На старой схеме вставляем только существовавшие тогда колонки.
                application_id = uuid.uuid4()
                stamp = datetime.now(timezone.utc)
                legacy_applications = Table('applications', MetaData(), autoload_with=legacy.connection())
                legacy.execute(legacy_applications.insert().values(
                    id=application_id, company_id=company.id, author_id=user.id, version=2,
                    created_at=stamp, updated_at=stamp,
                    status='submitted', catalog_version='demo-v1', **application_fields(profile)))
                snapshot = {'application': application_fields(profile), 'company': {'id':str(company.id),'inn':company.inn,
                            'name':company.name,'industry':company.industry,'registered_at':company.registered_at.isoformat()},
                            'documents':[],'confirmations':{'consent_version':'demo-consent-v1','data_confirmed':True,'bki_consent':True}}
                revision = ApplicationRevision(application_id=application_id,application_version=2,submitted_by=user.id,created_at=stamp,snapshot=snapshot)
                legacy.add(revision)
                legacy.flush()
                run_id,event_id = uuid.uuid4(),uuid.uuid4()
                legacy.execute(text("INSERT INTO processing_runs(id,application_id,revision_id,status,catalog_version,policy_version,source_version,created_at) VALUES(:id,:app,:rev,'pending','demo-v1',:policy_version,'demo-profiles-v1',:stamp)"),
                               dict(id=run_id,app=application_id,rev=revision.id,stamp=stamp,policy_version=policy_version))
                legacy.execute(text("INSERT INTO application_events(id,application_id,actor_id,event_type,created_at,application_version) VALUES(:id,:app,:actor,'application_submitted',:stamp,2)"),
                               dict(id=event_id,app=application_id,actor=user.id,stamp=stamp))
                legacy.commit()
                revision_id,user_id = revision.id,user.id
            command.upgrade(config,'head')
            command.check(config)
            context.setattr(service,'SessionLocal',factory)
            assert service.recover_interrupted() == 1
            with factory() as legacy:
                application = legacy.get(Application,application_id)
                staff = legacy.scalar(select(User).where(User.role=='staff'))
                service.retry_processing(legacy,staff,application_id,RetryInput(expected_version=application.version),uuid.uuid4())
            assert service.process_next()
            with factory() as legacy:
                run = legacy.get(ProcessingRun,run_id)
                assert run.status=='succeeded' and run.policy_version==policy_version and run.scorer_version is None and run.source_version=='demo-profiles-v1'
                assert legacy.get(ApplicationRevision,revision_id).snapshot == snapshot
                assert legacy.get(User,user_id).password_hash == password
                event = legacy.execute(text('SELECT actor_type, actor_id, event_type FROM application_events WHERE id=:id'),{'id':event_id}).one()
                assert event == ('user',user_id,'application_submitted')
                assert legacy.get(Application,application_id).status==('approved' if profile=='a' else 'counteroffer')
                saved = {table:legacy.execute(text(f'SELECT to_jsonb(t) FROM {table} t ORDER BY id')).scalars().all()
                         for table in ('application_revisions','check_results','decisions','offers','application_events')}
            command.downgrade(config,'0005_information_response')
            command.upgrade(config,'head')
            command.check(config)
            with factory() as legacy:
                for table, rows in saved.items():
                    if table in ('offers', 'decisions'):
                        # Downgrade до 0005 удаляет новые снимки; прежние суммы и связи сохраняются.
                        rows = [{**row, 'payment_terms': None} for row in rows]
                    assert legacy.execute(text(f'SELECT to_jsonb(t) FROM {table} t ORDER BY id')).scalars().all()==rows
                if profile == 'b':
                    from app.processing.models import Offer
                    from app.processing.schemas import OfferOutput
                    output = OfferOutput.model_validate(legacy.scalar(select(Offer)))
                    assert output.payment_terms.monthly_payment_kopecks == 12_382_411
                    assert output.payment_terms.total_payment_kopecks == 297_177_864
                assert legacy.execute(text('SELECT count(*) FROM risk_assessments')).scalar_one()==0

    finally:
        legacy_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_empty_risk_migration_round_trip(db,monkeypatch):
    from app.core.config import settings
    name=f'risk_empty_{uuid.uuid4().hex}'
    admin=create_engine(application_url,isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url=application_url.set(database=name).render_as_string(hide_password=False)
    config=Config(str(Path(__file__).parents[1]/'alembic.ini'))
    try:
        with monkeypatch.context() as context:
            context.setattr(settings,'database_url',url)
            command.upgrade(config,'head')
            command.check(config)
            command.downgrade(config,'0005_information_response')
            command.upgrade(config,'head')
            command.check(config)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
