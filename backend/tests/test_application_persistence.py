import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text, update

from app.applications.models import Application
from app.applications.schemas import DraftCreate
from app.applications.service import create_draft
from app.applications.submission_models import ProcessingRun
from app.assistant.models import ApplicationSummary
from app.assistant.provider import AssistantUnavailable
from app.auth.models import User
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.main import app
from app.processing.models import CheckResult
from app.risk.models import RiskAssessment
from test_application_drafts import authenticate, create, patch
from test_assistant_chat import fake
from test_assistant_summary import ready, summary


def saved(client, application, **params):
    return client.get(f"/api/v1/applications/{application['id']}/summary",
        params={'expected_version': application['version'], **params})


def test_display_number_persists_in_create_detail_list_and_changes(client):
    headers = authenticate(client)
    first, second = create(client, headers), create(client, headers)
    number = int(first['display_number'].removeprefix('КЗ-'))
    assert first['display_number'] == f'КЗ-{number:06d}'
    assert int(second['display_number'].removeprefix('КЗ-')) == number + 1
    assert patch(client, headers, first, purpose='Новое назначение').json()['display_number'] == first['display_number']
    assert client.get(f"/api/v1/applications/{first['id']}").json()['display_number'] == first['display_number']
    assert {item['display_number'] for item in client.get('/api/v1/applications').json()['items']} == {
        first['display_number'], second['display_number']}


def test_parallel_creation_uses_unique_database_numbers(db):
    owner = db.scalar(select(User).where(User.email == 'client1@example.test')).id
    barrier = Barrier(8)
    def work(index):
        with SessionLocal() as other:
            user = other.get(User, owner)
            barrier.wait(timeout=15)
            row = create_draft(other, user, DraftCreate(product_code='working_capital'))
            return row.number
    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(work, range(8)))
    assert len(set(numbers)) == 8
    assert max(numbers) - min(numbers) == 7


def test_migration_backfills_by_creation_and_uuid_and_restarts_sequence(db, monkeypatch):
    name = f'test_numbers_{uuid.uuid4().hex}'
    admin = create_engine(engine.url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    url = engine.url.set(database=name)
    target = create_engine(url)
    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    monkeypatch.setattr(settings, 'database_url', url.render_as_string(hide_password=False))
    try:
        command.upgrade(config, '0008_product_analytics')
        with target.begin() as connection:
            connection.execute(text("INSERT INTO companies (id, inn, name, industry, registered_at) VALUES "
                "('00000000-0000-0000-0000-000000000001', '1234567890', 'Компания', 'retail', '2020-01-01')"))
            connection.execute(text("INSERT INTO users (id,email,password_hash,display_name,role,company_id) VALUES "
                "('00000000-0000-0000-0000-000000000002','migration@test','hash','Клиент','client','00000000-0000-0000-0000-000000000001')"))
            for suffix, created in [(3, '2024-01-02'), (5, '2024-01-01'), (4, '2024-01-01')]:
                connection.execute(text("INSERT INTO applications (id, company_id, author_id, version, status, catalog_version, created_at, updated_at, product_code) "
                    "VALUES (:id, '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002',1,'draft','demo-v2',:created,:created,'working_capital')"),
                    {'id': uuid.UUID(int=suffix), 'created': created})
        command.upgrade(config, 'head')
        with target.begin() as connection:
            rows = connection.execute(text('SELECT id, number FROM applications ORDER BY number')).all()
            assert [(row.id.int, row.number) for row in rows] == [(4, 1), (5, 2), (3, 3)]
            assert connection.scalar(text("SELECT nextval('application_number_seq')")) == 4
        command.downgrade(config, '0008_product_analytics')
        with target.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('application_number_seq')")) is None
        command.upgrade(config, 'head')
    finally:
        target.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_empty_get_never_generates_and_post_reuses_durable_cache(client, db, fake):
    headers, current, _ = ready(client)
    assert saved(client, current).json() is None
    assert not fake.calls
    first = summary(client, headers, current)
    assert first.status_code == 200, first.text
    assert summary(client, headers, current).json() == first.json()
    assert saved(client, current).json() == first.json()
    assert len(fake.calls) == 1
    with TestClient(app) as fresh:
        authenticate(fresh, 'staff@example.test')
        assert saved(fresh, current).json() == first.json()
    assert db.scalar(select(ApplicationSummary)).response == first.json()
    assert summary(client, headers, current, refresh=True).status_code == 200
    assert len(fake.calls) == 2


@pytest.mark.parametrize('change', ['check', 'run', 'risk_inputs', 'model', 'provider', 'prompt', 'version'])
def test_actual_sources_and_configuration_invalidate_cache(client, db, fake, monkeypatch, change):
    headers, current, _ = ready(client)
    identifier = uuid.UUID(current['id'])
    run = db.scalar(select(ProcessingRun).where(ProcessingRun.application_id == identifier))
    if change == 'risk_inputs':
        # Успешная оценка неизменяема на уровне БД. Проверяем изменяемую неуспешную попытку.
        original = db.scalar(select(RiskAssessment).where(RiskAssessment.processing_run_id == run.id))
        values = {column.name: getattr(original, column.name) for column in original.__table__.columns}
        values.update(id=uuid.uuid4(), status='failed', probability=None, payload={}, reason_code='model_unavailable')
        db.add(RiskAssessment(**values))
        db.commit()
    assert summary(client, headers, current).status_code == 200
    if change == 'check':
        db.execute(update(CheckResult).where(CheckResult.run_id == run.id, CheckResult.kind == 'bki').values(data={'overdue_days': 7}))
    elif change == 'run':
        db.execute(update(ProcessingRun).where(ProcessingRun.id == run.id).values(attempt=run.attempt + 1))
    elif change == 'risk_inputs':
        db.execute(update(RiskAssessment).where(RiskAssessment.processing_run_id == run.id,
            RiskAssessment.status == 'failed').values(inputs={'changed': True}))
    elif change == 'model':
        fake.model = 'changed-model'
    elif change == 'provider':
        monkeypatch.setattr(settings, 'llm_base_url', 'http://changed-provider.test')
    elif change == 'prompt':
        monkeypatch.setattr('app.assistant.summary.SYSTEM', 'Изменённая инструкция')
    else:
        db.execute(update(Application).where(Application.id == identifier).values(version=current['version'] + 1))
    db.commit()
    if change == 'version':
        assert saved(client, current).status_code == 409
        current['version'] += 1
    assert saved(client, current).json() is None
    assert len(fake.calls) == 1
    assert summary(client, headers, current).status_code == 200
    assert len(fake.calls) == 2


def test_get_and_cached_post_preserve_permissions_and_closed_input(client, fake):
    headers, current, _ = ready(client)
    assert summary(client, headers, current).status_code == 200
    assert saved(client, current, expected_version=0).status_code == 422
    assert summary(client, headers, current, refresh='yes').status_code == 422
    authenticate(client, 'client2@example.test')
    assert saved(client, current).status_code == 403
    assert summary(client, authenticate(client), current).status_code == 403
    with TestClient(app) as anonymous:
        assert saved(anonymous, current).status_code == 401
    assert len(fake.calls) == 1


@pytest.mark.parametrize('kind', ['invalid', 'unavailable'])
def test_refresh_failure_never_stores_error_or_returns_it_as_cached_answer(client, db, fake, kind):
    headers, current, _ = ready(client)
    first = summary(client, headers, current).json()
    if kind == 'invalid':
        fake.result = {'answer': 'Недостоверный ответ', 'source_ids': ['foreign']}
    else:
        def fail():
            raise AssistantUnavailable()
        fake.during = fail
    assert summary(client, headers, current, refresh=True).status_code == 503
    assert saved(client, current).json() == first
    assert db.scalar(select(ApplicationSummary)).response == first


def test_same_version_processing_change_during_network_is_rejected(client, fake):
    headers, current, _ = ready(client)
    def during():
        with SessionLocal() as other:
            run = other.scalar(select(ProcessingRun).where(ProcessingRun.application_id == uuid.UUID(current['id'])))
            other.execute(update(CheckResult).where(CheckResult.run_id == run.id, CheckResult.kind == 'bki').values(data={'overdue_days': 5}))
            other.commit()
    fake.during = during
    assert summary(client, headers, current).status_code == 409
    assert saved(client, current).json() is None


def test_concurrent_refresh_does_not_overwrite_newer_request(client, fake):
    _, current, _ = ready(client)
    first_entered, release_first = Event(), Event()
    lock = Lock()
    calls = 0
    def generate(*, system, user, schema):
        nonlocal calls
        with lock:
            calls += 1
            index = calls
        if index == 1:
            first_entered.set()
            assert release_first.wait(20)
        return {'answer': f'Сводка {index}', 'source_ids': [json.loads(user)['sources'][0]['id']]}
    fake.generate_json = generate
    # Разные staff-сессии: проверяем именно гонку сохранения, а не сериализацию auth_sessions.
    first, second = TestClient(app), TestClient(app)
    h1, h2 = authenticate(first, 'staff@example.test'), authenticate(second, 'staff@example.test')
    with ThreadPoolExecutor(max_workers=2) as pool:
        older = pool.submit(summary, first, h1, current, refresh=True)
        try:
            assert first_entered.wait(10)
            newer = pool.submit(summary, second, h2, current, refresh=True).result(20)
            assert newer.status_code == 200, newer.text
        finally:
            release_first.set()
        old = older.result(20)
    assert old.status_code == 200, old.text
    assert old.json()['answer'] == newer.json()['answer'] == 'Сводка 2'
    assert saved(first, current).json()['answer'] == 'Сводка 2'
    first.close()
    second.close()
