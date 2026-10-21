import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from test_application_drafts import BASE, authenticate, create, patch
from test_documents import attach, upload

COMPLETE = {
    'purpose': 'Закупка сырья', 'amount_kopecks': 100_000_000, 'term_months': 12,
    'period_start': '2025-01-01', 'period_end': '2025-03-31',
    'revenue_kopecks': 240_000_000, 'operating_expenses_kopecks': 150_000_000,
    'existing_debt_payments_kopecks': 0,
}


def submit(client, headers, draft, key=None, **changes):
    body = {'expected_version': draft['version'], 'data_confirmed': True, 'bki_consent': True, 'consent_version': 'demo-consent-v1', **changes}
    return client.post(f"{BASE}/{draft['id']}/submit", json=body, headers={**headers, 'Idempotency-Key': key or str(uuid.uuid4())})


def ready(client, headers, product='working_capital'):
    draft = create(client, headers, **COMPLETE)
    if product != 'working_capital':
        draft = patch(client, headers, draft, product_code=product).json()
    draft, document = attach(client, headers, draft)
    if product == 'equipment':
        draft, _ = attach(client, headers, draft, 'equipment_invoice')
    return draft, document


@pytest.mark.parametrize('product', ['working_capital', 'equipment'])
def test_submission_snapshot_and_staff_access(client, db, product):
    headers = authenticate(client)
    draft, document = ready(client, headers, product)
    response = submit(client, headers, draft)
    assert response.status_code == 202, response.text
    result = response.json()
    assert result['application_id'] == draft['id']
    assert result['version'] == draft['version'] + 1 and result['status'] == 'submitted'
    application = client.get(f"{BASE}/{draft['id']}").json()
    assert application['status'] == 'submitted' and application['available_actions'] == []
    assert patch(client, headers, application, purpose='Подмена').status_code == 409
    assert upload(client, headers, application).status_code == 409
    assert client.delete(f"{BASE}/{draft['id']}/documents/{document['id']}", params={'expected_version': result['version']}, headers=headers).status_code == 409
    revision = db.execute(text('SELECT snapshot FROM application_revisions WHERE id=:id'), {'id': result['revision_id']}).scalar_one()
    assert revision['application']['purpose'] == COMPLETE['purpose']
    assert revision['company']['inn'] == '990000000001'
    assert revision['documents'][0]['id'] == document['id']
    assert revision['confirmations']['consent_version'] == 'demo-consent-v1'
    assert revision['confirmations']['bki_consent'] is True
    assert revision['confirmations']['confirmed_at']
    run = db.execute(text('SELECT status, catalog_version, policy_version, scorer_version FROM processing_runs WHERE id=:id'), {'id': result['processing_run_id']}).one()
    assert tuple(run) == ('pending', 'demo-v1', 'demo-policy-0.3', 'logistic-risk-v1')
    history = client.get(f"{BASE}/{draft['id']}/history").json()['items']
    assert history[-1]['event_type'] == 'application_submitted'
    authenticate(client, 'client2@example.test')
    assert client.get(f"{BASE}/{draft['id']}").status_code == 404
    staff_headers = authenticate(client, 'staff@example.test')
    assert client.get(f'{BASE}?status=submitted').json()['items'][0]['id'] == draft['id']
    assert client.get(f'{BASE}?status=draft').json()['items'] == []
    assert client.get(f"{BASE}/{draft['id']}/documents/{document['id']}").status_code == 200
    assert submit(client, staff_headers, application).status_code == 403
    assert patch(client, staff_headers, application, purpose='Подмена').status_code == 403


@pytest.mark.parametrize('field,value', [
    ('purpose', None), ('purpose', '   '), ('amount_kopecks', None),
    ('term_months', None), ('period_start', None), ('period_end', None),
    ('revenue_kopecks', None), ('operating_expenses_kopecks', None),
    ('existing_debt_payments_kopecks', None),
])
def test_incomplete_submission_stays_draft(client, db, field, value):
    headers = authenticate(client)
    draft = create(client, headers, **{**COMPLETE, field: value})
    draft, _ = attach(client, headers, draft)
    response = submit(client, headers, draft)
    assert response.status_code == 422, response.text
    assert field in response.json()['field_errors']
    assert client.get(f"{BASE}/{draft['id']}").json()['status'] == 'draft'
    assert db.execute(text('SELECT count(*) FROM application_revisions')).scalar_one() == 0
    assert db.execute(text('SELECT count(*) FROM processing_runs')).scalar_one() == 0


def test_required_files_follow_product(client):
    headers = authenticate(client)
    draft = create(client, headers, **COMPLETE)
    assert 'documents' in submit(client, headers, draft).json()['field_errors']
    draft, _ = attach(client, headers, draft)
    draft = patch(client, headers, draft, product_code='equipment').json()
    response = submit(client, headers, draft)
    assert response.status_code == 422 and 'documents' in response.json()['field_errors']
    draft, _ = attach(client, headers, draft, 'equipment_invoice')
    assert submit(client, headers, draft).status_code == 202


@pytest.mark.parametrize('changes', [
    {'data_confirmed': False}, {'bki_consent': False}, {'data_confirmed': 1},
    {'bki_consent': 'true'}, {'consent_version': 'old-version'},
    {'status': 'approved'}, {'expected_version': True},
])
def test_submission_rejects_invalid_confirmation(client, changes):
    headers = authenticate(client)
    draft, _ = ready(client, headers)
    assert submit(client, headers, draft, **changes).status_code == 422
    assert client.get(f"{BASE}/{draft['id']}").json()['status'] == 'draft'


def test_idempotency_and_stale_version(client, db):
    headers = authenticate(client)
    draft, _ = ready(client, headers)
    assert submit(client, headers, draft, expected_version=draft['version'] - 1).status_code == 409
    key = str(uuid.uuid4())
    first = submit(client, headers, draft, key)
    assert first.status_code == 202
    assert submit(client, headers, draft, key).json() == first.json()
    assert submit(client, headers, draft, key, expected_version=draft['version'] + 1).status_code == 409
    assert submit(client, headers, draft).status_code == 409
    other, _ = ready(client, headers)
    assert submit(client, headers, other, key).status_code == 409
    assert db.execute(text('SELECT count(*) FROM application_revisions')).scalar_one() == 1
    assert db.execute(text('SELECT count(*) FROM processing_runs')).scalar_one() == 1


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_submissions_create_one_snapshot(client, db, same_key):
    headers = authenticate(client)
    draft, _ = ready(client, headers)
    barrier = Barrier(2)
    keys = [str(uuid.uuid4()), str(uuid.uuid4())]
    if same_key:
        keys[1] = keys[0]

    def send(key):
        with TestClient(app) as own:
            own_headers = authenticate(own)
            barrier.wait(timeout=10)
            return submit(own, own_headers, draft, key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(send, keys))
    assert sorted(response.status_code for response in responses) == ([202, 202] if same_key else [202, 409])
    if same_key:
        assert responses[0].json() == responses[1].json()
    assert db.execute(text('SELECT count(*) FROM application_revisions')).scalar_one() == 1
    assert db.execute(text('SELECT count(*) FROM processing_runs')).scalar_one() == 1


def test_submission_policy_and_permissions(client):
    assert client.get('/api/v1/submission-policy').status_code == 401
    headers = authenticate(client)
    policy = client.get('/api/v1/submission-policy').json()
    assert policy['consent_version'] == 'demo-consent-v1'
    assert policy['max_file_size_bytes'] == 10 * 1024 * 1024
    assert policy['bki_consent_text'] and policy['data_confirmation_text']
    draft, _ = ready(client, headers)
    assert submit(client, {}, draft).status_code == 403
    assert submit(client, headers, draft, key='invalid').status_code == 422
    foreign = authenticate(client, 'client2@example.test')
    assert submit(client, foreign, draft).status_code == 404


@pytest.mark.parametrize('action', ['patch', 'delete', 'upload'])
def test_submit_races_with_draft_change(client, db, action):
    headers = authenticate(client)
    draft, document = ready(client, headers)
    barrier = Barrier(2)

    def request(submitting):
        with TestClient(app) as own:
            own_headers = authenticate(own)
            barrier.wait(timeout=10)
            if submitting:
                return submit(own, own_headers, draft)
            if action == 'patch':
                return patch(own, own_headers, draft, purpose='Изменённая цель')
            if action == 'upload':
                return upload(own, own_headers, draft)
            return own.delete(f"{BASE}/{draft['id']}/documents/{document['id']}",
                              params={'expected_version': draft['version']}, headers=own_headers)

    with ThreadPoolExecutor(max_workers=2) as executor:
        sending, changing = list(executor.map(request, [True, False]))
    assert (sending.status_code, changing.status_code) in ((202, 409), (409, 201 if action == 'upload' else 200))
    count = db.execute(text('SELECT count(*) FROM application_revisions')).scalar_one()
    assert count == (1 if sending.status_code == 202 else 0)
    if count:
        assert client.get(f"{BASE}/{draft['id']}/documents/{document['id']}").status_code == 200
        snapshot = db.execute(text('SELECT snapshot FROM application_revisions')).scalar_one()
        assert snapshot['application']['purpose'] == COMPLETE['purpose']
        assert len(snapshot['documents']) == 1


def test_unavailable_file_prevents_submission(client, db):
    from app.core.config import settings

    headers = authenticate(client)
    draft, document = ready(client, headers)
    (settings.document_storage_path / document['id']).unlink()
    assert submit(client, headers, draft).status_code == 503
    assert client.get(f"{BASE}/{draft['id']}").json()['status'] == 'draft'
    assert db.execute(text('SELECT count(*) FROM processing_runs')).scalar_one() == 0


def test_submission_rolls_back_snapshot_on_event_failure(client, db, monkeypatch):
    from app.applications import submission

    headers = authenticate(client)
    draft, _ = ready(client, headers)

    def fail_event(*args, **kwargs):
        raise RuntimeError('Искусственный сбой транзакции')

    monkeypatch.setattr(submission, 'add_event', fail_event)
    assert submit(client, headers, draft).status_code == 500
    assert client.get(f"{BASE}/{draft['id']}").json()['status'] == 'draft'
    for table in ('application_revisions', 'processing_runs', 'idempotency_records'):
        assert db.execute(text(f'SELECT count(*) FROM {table}')).scalar_one() == 0
