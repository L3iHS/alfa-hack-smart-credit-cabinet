import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from sqlalchemy import select, text

from app.applications.models import Application
from app.applications.submission_models import ProcessingRun
from app.core.db import SessionLocal
from test_application_drafts import BASE, authenticate, create
from test_documents import attach
from test_submission import submit


def prepared(client, profile='a', *, legacy=True):
    from app.demo.profiles import application_fields
    headers = authenticate(client, f'demo-{profile}@example.test')
    draft = create(client, headers, **application_fields(profile))
    draft, _ = attach(client, headers, draft)
    if profile in 'ace':
        draft, _ = attach(client, headers, draft, 'equipment_invoice')
    response = submit(client, headers, draft)
    assert response.status_code == 202, response.text
    if legacy:
        # Эти сценарии фиксируют принятую историческую политику до появления ML.
        with SessionLocal() as historical:
            historical.execute(text("UPDATE processing_runs SET policy_version='demo-policy-0.2', catalog_version='demo-v1', scorer_version=NULL WHERE id=:id"), {'id': response.json()['processing_run_id']})
            historical.execute(text("UPDATE application_revisions SET snapshot=snapshot-'catalog_version' WHERE id=:id"), {'id': response.json()['revision_id']})
            historical.commit()
    return headers, draft['id'], response.json()


def process():
    from app.processing.service import process_next
    return process_next()


@pytest.mark.parametrize('profile,outcome', [('a','approved'),('b','counteroffer'),('c','needs_info'),('d','manual_review'),('e','rejected')])
def test_five_persisted_profiles(client, db, profile, outcome):
    headers, application_id, submission = prepared(client, profile)
    assert process()
    detail = client.get(f'{BASE}/{application_id}').json()
    assert detail['status'] == outcome, detail
    assert detail['processing_status'] == 'succeeded'
    assert detail['public_reasons']
    assert client.get(f'{BASE}/{application_id}/assessment').status_code == 403
    assert 'runs' not in detail
    if profile == 'b':
        assert detail['offers'][0]['amount_kopecks'] == 234200000
        assert detail['offers'][0]['monthly_payment_kopecks'] == 12382411
    if profile == 'c':
        assert detail['information_requests'][0]['requested_fields'] == ['revenue_kopecks']
    authenticate(client, 'staff@example.test')
    assessment = client.get(f'{BASE}/{application_id}/assessment').json()
    assert assessment['risk_assessment'] is None
    assert len(assessment['runs'][0]['checks']) == 3
    assert assessment['runs'][0]['decision']['outcome'] == outcome
    if profile == 'a':
        assert assessment['runs'][0]['calculation']['monthly_payment_kopecks'] == 10574220
    history = client.get(f'{BASE}/{application_id}/history').json()['items']
    assert history[-1]['actor_type'] == 'system'
    assert history[-1]['processing_run_id'] == submission['processing_run_id']
    assert not process()
    assert client.get(f'{BASE}/{application_id}').json()['version'] == detail['version']


def test_failure_retry_reuses_checks_and_hides_details(client, db, monkeypatch):
    from app.processing import providers
    original = providers.check
    calls = []
    def faulty(kind, snapshot, version):
        calls.append(kind)
        if kind == 'bki':
            raise RuntimeError('private upstream failure')
        return original(kind, snapshot, version)
    monkeypatch.setattr(providers, 'check', faulty)
    headers, application_id, submission = prepared(client)
    process()
    detail = client.get(f'{BASE}/{application_id}').json()
    assert detail['processing_status'] == 'failed'
    assert detail['status'] == 'processing' and detail['public_reasons'] == []
    assert 'private' not in str(detail)
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0
    staff = authenticate(client, 'staff@example.test')
    assessment = client.get(f'{BASE}/{application_id}/assessment').json()
    assert len(assessment['runs'][0]['checks']) == 2
    key = str(uuid.uuid4())
    path = f'{BASE}/{application_id}/processing-retries'
    body = {'expected_version': detail['version']}
    retry = client.post(path, json=body, headers={**staff, 'Idempotency-Key': key})
    assert retry.status_code == 202, retry.text
    assert client.post(path, json=body, headers={**staff, 'Idempotency-Key': key}).json() == retry.json()
    assert client.post(path, json=body, headers={**staff, 'Idempotency-Key': str(uuid.uuid4())}).status_code == 409
    monkeypatch.setattr(providers, 'check', original)
    assert process()
    assert client.get(f'{BASE}/{application_id}').json()['status'] == 'approved'
    assert db.execute(text('SELECT count(*) FROM check_results')).scalar_one() == 3
    assert calls == ['registry', 'tax', 'bki']


def test_startup_recovery_and_retry_permissions(client, db):
    from app.processing.service import recover_interrupted
    headers, application_id, submission = prepared(client)
    assert recover_interrupted() == 1
    current = client.get(f'{BASE}/{application_id}').json()
    assert current['processing_status'] == 'interrupted'
    path = f'{BASE}/{application_id}/processing-retries'
    assert client.post(path, json={'expected_version': current['version']}, headers={**headers,'Idempotency-Key':str(uuid.uuid4())}).status_code == 403
    authenticate(client, 'client2@example.test')
    assert client.get(f'{BASE}/{application_id}').status_code == 404
    assert client.get(f'{BASE}/{application_id}/assessment').status_code == 403
    staff = authenticate(client, 'staff@example.test')
    assert client.post(path, json={'expected_version': current['version']}, headers={**staff,'Idempotency-Key':str(uuid.uuid4())}).status_code == 202
    assert process()


def test_worker_claims_only_once(client, db):
    prepared(client)
    barrier = Barrier(2)
    def run():
        barrier.wait(timeout=10)
        return process()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: run(), range(2)))
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM processing_runs WHERE status='succeeded'")).scalar_one() == 1


def test_stale_revision_cannot_finish(client, db, monkeypatch):
    from app.processing import providers
    from app.applications.submission_models import ApplicationRevision
    headers, application_id, submission = prepared(client)
    original = providers.check
    changed = False
    def supersede(kind, snapshot, version):
        nonlocal changed
        if not changed:
            with SessionLocal() as own:
                current = own.get(Application, uuid.UUID(application_id))
                old = own.get(ApplicationRevision, uuid.UUID(submission['revision_id']))
                current.version += 1
                own.add(ApplicationRevision(application_id=current.id, application_version=current.version,
                                            submitted_by=current.author_id, created_at=datetime.now(timezone.utc), snapshot=old.snapshot))
                own.commit()
            changed = True
        return original(kind, snapshot, version)
    monkeypatch.setattr(providers, 'check', supersede)
    assert process()
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0
    assert db.get(ProcessingRun, uuid.UUID(submission['processing_run_id'])).status == 'interrupted'


def test_unknown_source_version_fails_closed(client, db):
    _, application_id, submission = prepared(client)
    db.execute(text("UPDATE processing_runs SET source_version='not-supported' WHERE id=:id"), {'id':submission['processing_run_id']})
    db.commit()
    process()
    assert client.get(f'{BASE}/{application_id}').json()['processing_status'] == 'failed'
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0


def test_seed_preserves_existing_passwords_and_data(db):
    from app.seed import seed
    old = db.execute(text('SELECT email, password_hash FROM users ORDER BY email')).all()
    db.execute(text("UPDATE companies SET name='Сохранённое имя' WHERE inn='990000000001'"))
    db.commit()
    seed(db)
    assert db.execute(text('SELECT email, password_hash FROM users ORDER BY email')).all() == old
    assert db.execute(text("SELECT name FROM companies WHERE inn='990000000001'")).scalar_one() == 'Сохранённое имя'


def test_known_legacy_versions_retain_identifiers(client, db):
    from app.processing.service import recover_interrupted
    _, application_id, submission = prepared(client)
    db.execute(text("UPDATE processing_runs SET policy_version='demo-policy-v1' WHERE id=:id"), {'id':submission['processing_run_id']})
    original = db.execute(text('SELECT snapshot FROM application_revisions WHERE id=:id'), {'id':submission['revision_id']}).scalar_one()
    db.commit()
    assert recover_interrupted() == 1
    current = client.get(f'{BASE}/{application_id}').json()
    headers = authenticate(client, 'staff@example.test')
    response = client.post(f'{BASE}/{application_id}/processing-retries', json={'expected_version':current['version']},
                           headers={**headers,'Idempotency-Key':str(uuid.uuid4())})
    assert response.status_code == 202, response.text
    assert process()
    result = client.get(f'{BASE}/{application_id}/assessment').json()['runs'][0]
    assert result['status'] == 'succeeded'
    assert result['policy_version'] == result['calculation']['policy_version'] == 'demo-policy-v1'
    assert result['source_version'] == 'demo-profiles-v1'
    assert db.execute(text('SELECT snapshot FROM application_revisions WHERE id=:id'), {'id':submission['revision_id']}).scalar_one() == original


@pytest.mark.parametrize('column', ['policy_version', 'catalog_version'])
def test_unknown_policy_or_catalog_fails_closed(client, db, column):
    _, application_id, submission = prepared(client)
    db.execute(text(f"UPDATE processing_runs SET {column}='unknown' WHERE id=:id"), {'id':submission['processing_run_id']})
    db.commit()
    process()
    assert client.get(f'{BASE}/{application_id}').json()['processing_status'] == 'failed'
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0


def test_running_recovery_preserves_successful_checks(client, db, monkeypatch):
    from app.processing import providers
    from app.processing.service import recover_interrupted
    original = providers.check
    def interrupted(kind, snapshot, version):
        if kind == 'bki':
            assert recover_interrupted() == 1
        return original(kind,snapshot,version)
    monkeypatch.setattr(providers, 'check', interrupted)
    _, application_id, _ = prepared(client)
    process()
    assert client.get(f'{BASE}/{application_id}').json()['processing_status'] == 'interrupted'
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0
    assert db.execute(text('SELECT count(*) FROM check_results')).scalar_one() == 2


def test_concurrent_retries_create_one_attempt(client, db, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.processing import providers
    original = providers.check
    monkeypatch.setattr(providers, 'check', lambda *args: (_ for _ in ()).throw(RuntimeError('Сбой источника')))
    _, application_id, _ = prepared(client)
    process()
    current = client.get(f'{BASE}/{application_id}').json()
    barrier = Barrier(2)
    def retry(_):
        with TestClient(app) as own:
            headers = authenticate(own, 'staff@example.test')
            barrier.wait(timeout=10)
            return own.post(f'{BASE}/{application_id}/processing-retries',json={'expected_version':current['version']},
                            headers={**headers,'Idempotency-Key':str(uuid.uuid4())})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(retry, range(2)))
    assert sorted(item.status_code for item in responses) == [202,409]
    monkeypatch.setattr(providers, 'check', original)
    process()
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 1
    assert db.execute(text('SELECT attempt FROM processing_runs')).scalar_one() == 2


def test_lifespan_worker_runs_outside_http(client, db, monkeypatch):
    import time
    from threading import Event
    from fastapi.testclient import TestClient
    from app.core.config import settings
    from app.main import app
    from app.processing import providers
    entered, release = Event(), Event()
    original = providers.check
    def slow(kind, snapshot, version):
        if kind == 'bki':
            entered.set()
            assert release.wait(10)
        return original(kind,snapshot,version)
    monkeypatch.setattr(settings, 'processing_worker_enabled', True)
    monkeypatch.setattr(providers, 'check', slow)
    with TestClient(app) as own:
        _, application_id, _ = prepared(own)
        try:
            assert entered.wait(10)
            assert own.get('/api/v1/health').status_code == 200
            assert own.get(f'{BASE}/{application_id}').json()['processing_status'] == 'running'
        finally:
            release.set()
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            if own.get(f'{BASE}/{application_id}').json()['status'] == 'approved':
                break
            time.sleep(0.02)
        assert own.get(f'{BASE}/{application_id}').json()['status'] == 'approved'


def test_file_size_message_uses_mb(client):
    from test_documents import upload
    from test_submission import ready
    headers = authenticate(client)
    draft, _ = ready(client, headers)
    response = upload(client, headers, draft, content=b'x'*(10*1024*1024+1),filename='large.pdf',mime='application/pdf')
    assert response.status_code == 413
    assert '10 МБ' in response.json()['message']


@pytest.mark.parametrize('field,value', [('demo_profile','e'),('liquidated',False),('overdue_days',0)])
def test_client_cannot_override_synthetic_sources(client, db, field, value):
    headers = authenticate(client, 'demo-e@example.test')
    response = client.post(BASE, json={'product_code':'equipment',field:value},headers=headers)
    assert response.status_code == 422
    assert db.execute(text('SELECT count(*) FROM applications')).scalar_one() == 0
