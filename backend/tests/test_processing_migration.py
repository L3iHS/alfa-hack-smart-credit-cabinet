import uuid
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from conftest import application_url


def test_upgrade_keeps_legacy_submission_and_retries_it(db, monkeypatch):
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
                application = Application(company_id=company.id,author_id=user.id,version=2,status='submitted',catalog_version='demo-v1',
                                          **application_fields('a'))
                legacy.add(application)
                legacy.flush()
                stamp = datetime.now(timezone.utc)
                snapshot = {'application': application_fields('a'), 'company': {'id':str(company.id),'inn':company.inn,
                            'name':company.name,'industry':company.industry,'registered_at':company.registered_at.isoformat()},
                            'documents':[],'confirmations':{'consent_version':'demo-consent-v1','data_confirmed':True,'bki_consent':True}}
                revision = ApplicationRevision(application_id=application.id,application_version=2,submitted_by=user.id,created_at=stamp,snapshot=snapshot)
                legacy.add(revision)
                legacy.flush()
                run_id,event_id = uuid.uuid4(),uuid.uuid4()
                legacy.execute(text("INSERT INTO processing_runs(id,application_id,revision_id,status,catalog_version,policy_version,source_version,created_at) VALUES(:id,:app,:rev,'pending','demo-v1','demo-policy-v1','demo-profiles-v1',:stamp)"),
                               dict(id=run_id,app=application.id,rev=revision.id,stamp=stamp))
                legacy.execute(text("INSERT INTO application_events(id,application_id,actor_id,event_type,created_at,application_version) VALUES(:id,:app,:actor,'application_submitted',:stamp,2)"),
                               dict(id=event_id,app=application.id,actor=user.id,stamp=stamp))
                legacy.commit()
                application_id,revision_id,user_id = application.id,revision.id,user.id
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
                assert run.status=='succeeded' and run.policy_version=='demo-policy-v1' and run.source_version=='demo-profiles-v1'
                assert legacy.get(ApplicationRevision,revision_id).snapshot == snapshot
                assert legacy.get(User,user_id).password_hash == password
                event = legacy.execute(text('SELECT actor_type, actor_id, event_type FROM application_events WHERE id=:id'),{'id':event_id}).one()
                assert event == ('user',user_id,'application_submitted')
                assert legacy.get(Application,application_id).status=='approved'
    finally:
        legacy_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
