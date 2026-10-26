import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from conftest import application_url


def test_upgrade_preserves_decisions_and_downgrade_round_trip(db, monkeypatch):
    from app.core.config import settings
    from app.seed import seed

    name = f'deals_migration_{uuid.uuid4().hex}'
    admin = create_engine(application_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = application_url.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    try:
        with monkeypatch.context() as context:
            context.setattr(settings, 'database_url', url)
            command.upgrade(config, '0009_application_summaries')
            with Session(engine) as session:
                seed(session)
                user = session.execute(text("SELECT id, company_id FROM users WHERE email='client1@example.test'")).one()
                application, revision, decision = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                session.execute(text("INSERT INTO applications(id,company_id,author_id,version,status,catalog_version,product_code,created_at,updated_at) VALUES(:id,:company,:user,3,'approved','demo-v1','equipment',now(),now())"),
                                {'id': application, 'company': user.company_id, 'user': user.id})
                session.execute(text("INSERT INTO application_revisions(id,application_id,application_version,submitted_by,created_at,snapshot) VALUES(:id,:app,2,:user,now(),'{}')"),
                                {'id': revision, 'app': application, 'user': user.id})
                session.execute(text("INSERT INTO decisions(id,application_id,revision_id,application_version,outcome,public_reason_codes,public_reasons,internal_reason,policy_version,created_at) VALUES(:id,:app,:rev,3,'approved','[]','[]','Историческое решение','demo-policy-0.2',now())"),
                                {'id': decision, 'app': application, 'rev': revision})
                session.commit()
                before = session.execute(text('SELECT to_jsonb(d) FROM decisions d')).scalar_one()
            command.upgrade(config, 'head')
            command.check(config)
            with engine.connect() as connection:
                after = connection.execute(text('SELECT to_jsonb(d) FROM decisions d')).scalar_one()
                assert after == before | {'payment_terms': None}
                assert connection.execute(text('SELECT count(*) FROM deals')).scalar_one() == 0
            command.downgrade(config, '0009_application_summaries')
            with engine.connect() as connection:
                assert connection.execute(text('SELECT to_jsonb(d) FROM decisions d')).scalar_one() == before
            command.upgrade(config, 'head')
            command.check(config)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
