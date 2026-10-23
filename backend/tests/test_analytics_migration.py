import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from conftest import application_url


def test_upgrade_preserves_historical_answers_without_inventing_timestamps(db, monkeypatch):
    from app.core.config import settings
    from app.seed import seed
    from sqlalchemy.orm import Session

    name = f'analytics_legacy_{uuid.uuid4().hex}'
    admin = create_engine(application_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = application_url.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    try:
        with monkeypatch.context() as context:
            context.setattr(settings, 'database_url', url)
            command.upgrade(config, '0007_product_terms')
            with Session(engine) as session:
                seed(session)
                user = session.execute(text("SELECT id, company_id FROM users WHERE email='client1@example.test'")).one()
                for status in ('active', 'accepted', 'declined', 'superseded'):
                    application, revision, offer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                    session.execute(text("INSERT INTO applications(id,company_id,author_id,version,status,catalog_version,product_code,created_at,updated_at) VALUES(:id,:company,:user,2,'counteroffer','demo-v2','equipment',now(),now())"),
                                    {'id': application, 'company': user.company_id, 'user': user.id})
                    session.execute(text("INSERT INTO application_revisions(id,application_id,application_version,submitted_by,created_at,snapshot) VALUES(:id,:app,2,:user,now(),'{}')"),
                                    {'id': revision, 'app': application, 'user': user.id})
                    session.execute(text("INSERT INTO offers(id,application_id,revision_id,version,application_version,status,product_code,amount_kopecks,term_months,monthly_payment_kopecks,total_payment_kopecks,annual_rate_bps,reason,created_at) VALUES(:id,:app,:rev,1,2,:status,'equipment',10000000,12,1000000,12000000,2400,'Исторические условия',now())"),
                                    {'id': offer, 'app': application, 'rev': revision, 'status': status})
                session.commit()
                before = session.execute(text('SELECT to_jsonb(o) FROM offers o ORDER BY id')).scalars().all()
            command.upgrade(config, 'head')
            command.check(config)
            with engine.connect() as connection:
                after = connection.execute(text('SELECT to_jsonb(o) FROM offers o ORDER BY id')).scalars().all()
                assert after == [row | {'responded_at': None, 'decline_reason': None} for row in before]
                assert connection.execute(text('SELECT count(*) FROM analytics_journeys')).scalar_one() == 0
                assert connection.execute(text('SELECT count(*) FROM analytics_events')).scalar_one() == 0
            command.downgrade(config, '0007_product_terms')
            with engine.connect() as connection:
                assert connection.execute(text('SELECT to_jsonb(o) FROM offers o ORDER BY id')).scalars().all() == before
            command.upgrade(config, 'head')
            command.check(config)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
