import uuid
from copy import deepcopy

import pytest
from sqlalchemy import text

from test_application_drafts import BASE, authenticate, patch
from test_documents import attach
from test_processing import prepared, process


def current(client, identifier):
    return client.get(f'{BASE}/{identifier}').json()


def command(client, headers, path, body, key=None):
    return client.post(path, json=body, headers={**headers, 'Idempotency-Key': key or str(uuid.uuid4())})


def response_body(detail, **changes):
    return {'expected_version': detail['version'], 'request_id': detail['information_requests'][-1]['id'],
            'message': 'Сведения проверены и дополнены', 'data_confirmed': True, 'bki_consent': True,
            'consent_version': 'demo-consent-v1', **changes}


def test_information_response_creates_new_snapshot_only_on_explicit_send(client, db):
    headers, identifier, submission = prepared(client, 'c')
    process()
    detail = current(client, identifier)
    old = deepcopy(db.execute(text('SELECT snapshot FROM application_revisions')).scalar_one())
    changed = patch(client, headers, detail, revenue_kopecks=240000000)
    assert changed.status_code == 200, changed.text
    detail = changed.json()
    assert detail['status'] == 'needs_info'
    detail, document = attach(client, headers, detail)
    assert current(client, identifier)['status'] == 'needs_info'
    assert db.execute(text('SELECT count(*) FROM processing_runs')).scalar_one() == 1
    path = f'{BASE}/{identifier}/information-responses'
    key = str(uuid.uuid4())
    body = response_body(detail)
    result = command(client, headers, path, body, key)
    assert result.status_code == 202, result.text
    assert command(client, headers, path, body, key).json() == result.json()
    assert command(client, headers, path, body).status_code == 409
    assert result.json()['revision_id'] != submission['revision_id']
    rows = db.execute(text('SELECT snapshot FROM application_revisions ORDER BY application_version')).scalars().all()
    assert rows[0] == old and len(rows) == 2
    assert rows[1]['application']['revenue_kopecks'] == 240000000
    assert len(rows[1]['documents']) == len(old['documents']) + 1
    assert rows[1]['confirmations']['bki_consent_text'] == old['confirmations']['bki_consent_text']
    assert db.execute(text('SELECT response_revision_id FROM information_requests')).scalar_one() == uuid.UUID(result.json()['revision_id'])
    process()
    assert current(client, identifier)['status'] == 'approved'


def test_manual_request_and_response_keep_old_documents(client, db):
    _, identifier, _ = prepared(client, 'd')
    process()
    staff = authenticate(client, 'staff@example.test')
    detail = current(client, identifier)
    body = {'expected_version': detail['version'], 'message': 'Уточните финансовые сведения',
            'requested_fields': ['revenue_kopecks'], 'requested_document_types': ['financial_statement']}
    key = str(uuid.uuid4())
    path = f'{BASE}/{identifier}/information-requests'
    result = command(client, staff, path, body, key)
    assert result.status_code == 201, result.text
    assert command(client, staff, path, body, key).json() == result.json()
    assert current(client, identifier)['status'] == 'needs_info'
    headers = authenticate(client, 'demo-d@example.test')
    detail = current(client, identifier)
    document = client.get(f'{BASE}/{identifier}/documents').json()['items'][0]
    assert client.delete(f"{BASE}/{identifier}/documents/{document['id']}", params={'expected_version': detail['version']}, headers=headers).status_code == 409
    assert command(client, headers, f'{BASE}/{identifier}/information-responses', response_body(detail)).status_code == 422
    detail, _ = attach(client, headers, detail)
    result = command(client, headers, f'{BASE}/{identifier}/information-responses', response_body(detail))
    assert result.status_code == 202, result.text
    assert client.get(f"{BASE}/{identifier}/documents/{document['id']}").status_code == 200


@pytest.mark.parametrize('outcome', ['approved', 'rejected'])
def test_staff_decision_has_author_reason_and_idempotency(client, db, outcome):
    _, identifier, submission = prepared(client, 'd')
    process()
    headers = authenticate(client, 'staff@example.test')
    detail = current(client, identifier)
    body = {'expected_version': detail['version'], 'outcome': outcome, 'reason': 'Основание решения сотрудника'}
    key = str(uuid.uuid4())
    path = f'{BASE}/{identifier}/decisions'
    result = command(client, headers, path, body, key)
    assert result.status_code == 201, result.text
    assert command(client, headers, path, body, key).json() == result.json()
    assert command(client, headers, path, body).status_code == 409
    assert current(client, identifier)['status'] == outcome
    row = db.execute(text('SELECT actor_id, revision_id, internal_reason FROM decisions WHERE actor_id IS NOT NULL')).one()
    assert row.actor_id and str(row.revision_id) == submission['revision_id'] and row.internal_reason == body['reason']


@pytest.mark.parametrize('action,status', [('accept', 'approved'), ('decline', 'manual_review')])
def test_offer_command_versions_and_repeats(client, db, action, status):
    headers, identifier, _ = prepared(client, 'b')
    process()
    detail = current(client, identifier)
    offer = detail['offers'][-1]
    path = f"/api/v1/offers/{offer['id']}/{action}"
    body = {'expected_version': detail['version'], 'offer_version': offer['version']}
    assert command(client, headers, path, {**body, 'offer_version': 0}).status_code in (409, 422)
    key = str(uuid.uuid4())
    result = command(client, headers, path, body, key)
    assert result.status_code == 200, result.text
    assert command(client, headers, path, body, key).json() == result.json()
    assert command(client, headers, path, body).status_code == 409
    detail = current(client, identifier)
    assert detail['status'] == status
    assert detail['offers'][-1]['version'] == offer['version'] + 1
    assert detail['offers'][-1]['status'] == ('accepted' if action == 'accept' else 'declined')


def test_staff_offer_checks_terms_and_keeps_comparison(client, db):
    _, identifier, _ = prepared(client, 'd')
    process()
    staff = authenticate(client, 'staff@example.test')
    detail = current(client, identifier)
    body = {'expected_version': detail['version'], 'amount_kopecks': 40000000, 'term_months': 12, 'reason': 'Подобраны условия по финансовым сведениям'}
    key = str(uuid.uuid4())
    path = f'{BASE}/{identifier}/offers'
    result = command(client, staff, path, body, key)
    assert result.status_code == 201, result.text
    assert command(client, staff, path, body, key).json() == result.json()
    detail = current(client, identifier)
    assert detail['status'] == 'counteroffer' and detail['amount_kopecks'] == 50000000
    offer = detail['offers'][-1]
    assert offer['amount_kopecks'] == 40000000
    assert offer['total_payment_kopecks'] == offer['monthly_payment_kopecks'] * 12


def test_offer_key_cannot_be_reused_for_another_offer(client, db):
    headers, identifier, _ = prepared(client, 'b')
    process()
    detail = current(client, identifier)
    first = detail['offers'][-1]
    key = str(uuid.uuid4())
    body = {'expected_version': detail['version'], 'offer_version': first['version']}
    result = command(client, headers, f"/api/v1/offers/{first['id']}/decline", body, key)
    assert result.status_code == 200, result.text
    staff = authenticate(client, 'staff@example.test')
    detail = current(client, identifier)
    made = command(client, staff, f'{BASE}/{identifier}/offers', {'expected_version': detail['version'],
                   'amount_kopecks': first['amount_kopecks'], 'term_months': first['term_months'], 'reason': 'Повторное предложение'})
    assert made.status_code == 201, made.text
    headers = authenticate(client, 'demo-b@example.test')
    detail = current(client, identifier)
    second = detail['offers'][-1]
    retry = command(client, headers, f"/api/v1/offers/{second['id']}/decline",
                    {'expected_version': detail['version'], 'offer_version': second['version']}, key)
    assert retry.status_code == 409 and retry.json()['code'] == 'idempotency_conflict'
    assert command(client, headers, f"/api/v1/offers/{first['id']}/accept",
                   {'expected_version': detail['version'], 'offer_version': first['version']}).status_code == 409


def test_response_history_links_new_revision_and_run(client, db):
    headers, identifier, _ = prepared(client, 'c')
    process()
    detail = current(client, identifier)
    sent = command(client, headers, f'{BASE}/{identifier}/information-responses', response_body(detail))
    assert sent.status_code == 202, sent.text
    event = client.get(f'{BASE}/{identifier}/history').json()['items'][-1]
    assert event['event_type'] == 'information_responded'
    assert event['revision_id'] == sent.json()['revision_id']
    assert event['processing_run_id'] == sent.json()['processing_run_id']


def test_unexpected_processing_error_logs_run_stage_without_input(client, db, monkeypatch, caplog):
    import logging
    from app.processing import providers
    original = providers.check
    def fail(kind, snapshot, version):
        if kind == 'bki':
            raise RuntimeError('private financial input')
        return original(kind, snapshot, version)
    monkeypatch.setattr(providers, 'check', fail)
    _, identifier, submission = prepared(client)
    with caplog.at_level(logging.ERROR, logger='app.processing.service'):
        process()
    records = [item for item in caplog.records if item.name == 'app.processing.service']
    assert len(records) == 1
    assert records[0].run_id == submission['processing_run_id']
    assert records[0].stage == 'check_bki'
    assert records[0].exception_type == 'RuntimeError'
    assert 'private financial input' not in caplog.text
    assert current(client, identifier)['processing_status'] == 'failed'


@pytest.mark.parametrize('command_name', ['decisions', 'offers'])
@pytest.mark.parametrize('failure', ['coverage', 'liquidated', 'overdue', 'missing_check', 'failed_run', 'missing_document', 'missing_field', 'mismatched_revenue'])
def test_manual_guard_refuses_unsafe_approval_or_offer(client, db, command_name, failure):
    _, identifier, _ = prepared(client, 'd')
    process()
    if failure == 'coverage':
        db.execute(text("UPDATE application_revisions SET snapshot=jsonb_set(snapshot, '{application,revenue_kopecks}', '90000000')"))
    elif failure == 'liquidated':
        db.execute(text("UPDATE check_results SET data=jsonb_set(data, '{liquidated}', 'true') WHERE kind='registry'"))
    elif failure == 'overdue':
        db.execute(text("UPDATE check_results SET data=jsonb_set(data, '{overdue_days}', '90') WHERE kind='bki'"))
    elif failure == 'missing_check':
        db.execute(text("DELETE FROM check_results WHERE kind='tax'"))
    elif failure == 'failed_run':
        db.execute(text("UPDATE processing_runs SET status='failed'"))
    elif failure == 'missing_document':
        db.execute(text("UPDATE application_revisions SET snapshot=jsonb_set(snapshot, '{documents}', '[]')"))
    elif failure == 'missing_field':
        db.execute(text("UPDATE application_revisions SET snapshot=jsonb_set(snapshot, '{application,purpose}', 'null')"))
    elif failure == 'mismatched_revenue':
        db.execute(text("UPDATE check_results SET data=jsonb_set(data, '{expected_monthly_revenue_kopecks}', '1') WHERE kind='tax'"))
    db.commit()
    headers = authenticate(client, 'staff@example.test')
    detail = current(client, identifier)
    body = {'expected_version': detail['version'], 'reason': 'Обоснование сотрудника'}
    body.update({'outcome': 'approved'} if command_name == 'decisions' else {'amount_kopecks': 40000000, 'term_months': 12})
    result = command(client, headers, f'{BASE}/{identifier}/{command_name}', body)
    assert result.status_code == 409, result.text
    assert current(client, identifier)['status'] == 'manual_review'
    assert db.execute(text('SELECT count(*) FROM decisions WHERE actor_id IS NOT NULL')).scalar_one() == 0
    assert db.execute(text('SELECT count(*) FROM offers')).scalar_one() == 0


@pytest.mark.parametrize('overdue', [1, 89])
def test_staff_can_approve_short_overdue_with_sufficient_coverage(client, db, overdue):
    _, identifier, _ = prepared(client, 'd')
    process()
    db.execute(text("UPDATE check_results SET data=jsonb_set(data, '{overdue_days}', CAST(:days AS jsonb)) WHERE kind='bki'"), {'days': str(overdue)})
    db.commit()
    headers = authenticate(client, 'staff@example.test')
    result = command(client, headers, f'{BASE}/{identifier}/decisions', {'expected_version': current(client, identifier)['version'],
                     'outcome': 'approved', 'reason': 'Допустимый ручной разбор короткой просрочки'})
    assert result.status_code == 201, result.text


@pytest.mark.parametrize('confirmation,value', [('data_confirmed', False), ('bki_consent', False), ('consent_version', 'old'), ('message', '   ')])
def test_response_validates_confirmation_and_message_again(client, db, confirmation, value):
    headers, identifier, _ = prepared(client, 'c')
    process()
    detail = current(client, identifier)
    result = command(client, headers, f'{BASE}/{identifier}/information-responses', response_body(detail, **{confirmation: value}))
    assert result.status_code == 422, result.text
    assert db.execute(text('SELECT count(*) FROM application_revisions')).scalar_one() == 1
    assert current(client, identifier)['status'] == 'needs_info'


@pytest.mark.parametrize('endpoint', ['information-requests', 'offers', 'decisions'])
def test_staff_commands_forbid_client_and_foreign_application(client, db, endpoint):
    headers, identifier, _ = prepared(client, 'd')
    process()
    detail = current(client, identifier)
    bodies = {'information-requests': {'message': 'Уточните сведения', 'requested_fields': ['purpose']},
              'offers': {'amount_kopecks': 40000000, 'term_months': 12, 'reason': 'Проверка'},
              'decisions': {'outcome': 'approved', 'reason': 'Проверка'}}
    body = {'expected_version': detail['version'], **bodies[endpoint]}
    assert command(client, headers, f'{BASE}/{identifier}/{endpoint}', body).status_code == 403
    staff = authenticate(client, 'staff@example.test')
    assert command(client, staff, f'{BASE}/{uuid.uuid4()}/{endpoint}', body).status_code == 404
    assert command(client, staff, f'{BASE}/{identifier}/{endpoint}', {**body, 'expected_version': detail['version'] - 1}).status_code == 409
    message_field = 'message' if endpoint == 'information-requests' else 'reason'
    assert command(client, staff, f'{BASE}/{identifier}/{endpoint}', {**body, message_field: '   '}).status_code == 422


def test_client_commands_enforce_ownership_and_staff_role(client, db):
    headers, identifier, _ = prepared(client, 'b')
    process()
    detail = current(client, identifier)
    offer = detail['offers'][-1]
    body = {'expected_version': detail['version'], 'offer_version': offer['version']}
    foreign = authenticate(client, 'client2@example.test')
    for action in ('accept', 'decline'):
        assert command(client, foreign, f"/api/v1/offers/{offer['id']}/{action}", body).status_code == 404
    staff = authenticate(client, 'staff@example.test')
    assert command(client, staff, f"/api/v1/offers/{offer['id']}/accept", body).status_code == 403
    headers, identifier, _ = prepared(client, 'c')
    process()
    body = response_body(current(client, identifier))
    foreign = authenticate(client, 'client2@example.test')
    assert command(client, foreign, f'{BASE}/{identifier}/information-responses', body).status_code == 404
    staff = authenticate(client, 'staff@example.test')
    assert command(client, staff, f'{BASE}/{identifier}/information-responses', body).status_code == 403


@pytest.mark.parametrize('operation', ['information-requests', 'information-responses', 'offers', 'decisions', 'accept', 'decline'])
@pytest.mark.parametrize('same_key', [True, False])
def test_two_sessions_execute_each_command_once(client, db, operation, same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    from app.main import app

    profile = 'b' if operation in ('accept', 'decline') else 'c' if operation == 'information-responses' else 'd'
    _, identifier, _ = prepared(client, profile)
    process()
    detail = current(client, identifier)
    body = {'expected_version': detail['version']}
    path = f'{BASE}/{identifier}/{operation}'
    email = 'staff@example.test'
    status = 201
    if operation == 'information-requests':
        body.update(message='Уточните сведения', requested_fields=['purpose'])
    elif operation == 'information-responses':
        body = response_body(detail)
        email, status = 'demo-c@example.test', 202
    elif operation == 'offers':
        body.update(amount_kopecks=40000000, term_months=12, reason='Предложение сотрудника')
    elif operation == 'decisions':
        body.update(outcome='approved', reason='Решение сотрудника')
    else:
        offer = detail['offers'][-1]
        path = f"/api/v1/offers/{offer['id']}/{operation}"
        body['offer_version'] = offer['version']
        email, status = 'demo-b@example.test', 200
    barrier = Barrier(2)
    keys = [str(uuid.uuid4()), str(uuid.uuid4())]
    if same_key:
        keys[1] = keys[0]
    def send(key):
        with TestClient(app) as own:
            headers = authenticate(own, email)
            barrier.wait(timeout=10)
            return command(own, headers, path, body, key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, keys))
    assert sorted(item.status_code for item in results) == ([status, status] if same_key else sorted([status, 409]))
    if same_key:
        assert results[0].json() == results[1].json()
    assert current(client, identifier)['version'] == detail['version'] + 1
    headers = authenticate(client, email)
    assert command(client, headers, path, {**body, 'expected_version': detail['version'] + 1}, keys[results[0].status_code != status]).status_code == 409


@pytest.mark.parametrize('change', ['patch', 'upload'])
def test_response_races_with_working_copy_change(client, db, change):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    from app.main import app
    from test_documents import upload

    headers, identifier, _ = prepared(client, 'c')
    process()
    detail = patch(client, headers, current(client, identifier), revenue_kopecks=240000000).json()
    original = deepcopy(db.execute(text('SELECT snapshot FROM application_revisions')).scalar_one())
    barrier = Barrier(2)
    def send(responding):
        with TestClient(app) as own:
            own_headers = authenticate(own, 'demo-c@example.test')
            barrier.wait(timeout=10)
            if responding:
                return command(own, own_headers, f'{BASE}/{identifier}/information-responses', response_body(detail))
            if change == 'patch':
                return patch(own, own_headers, detail, purpose='Уточнённая цель')
            return upload(own, own_headers, detail)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sent, changed = list(pool.map(send, [True, False]))
    assert (sent.status_code, changed.status_code) in ((202, 409), (409, 200 if change == 'patch' else 201))
    snapshots = db.execute(text('SELECT snapshot FROM application_revisions ORDER BY application_version')).scalars().all()
    assert snapshots[0] == original
    assert len(snapshots) == (2 if sent.status_code == 202 else 1)


def test_needs_info_actions_and_working_copy_guards(client, db):
    from test_documents import upload
    headers, identifier, _ = prepared(client, 'c')
    process()
    detail = current(client, identifier)
    assert 'edit_draft' in detail['available_actions']
    assert patch(client, headers, detail, product_code='working_capital').status_code == 422
    assert patch(client, headers, {**detail, 'version': detail['version'] - 1}, purpose='Уточнение').status_code == 409
    assert upload(client, headers, {**detail, 'version': detail['version'] - 1}).status_code == 409
    assert current(client, identifier)['version'] == detail['version']


@pytest.mark.parametrize('profile', ['c', 'd'])
def test_information_response_is_readable_by_client_and_staff(client, db, profile):
    from datetime import datetime, timezone

    headers, identifier, _ = prepared(client, profile)
    process()
    if profile == 'd':
        staff = authenticate(client, 'staff@example.test')
        requested = command(client, staff, f'{BASE}/{identifier}/information-requests', {
            'expected_version': current(client, identifier)['version'], 'message': 'Поясните размер выручки',
            'requested_fields': ['revenue_kopecks'],
        })
        assert requested.status_code == 201, requested.text
        headers = authenticate(client, 'demo-d@example.test')
    detail = current(client, identifier)
    original_request = detail['information_requests'][-1]
    response_fields = ('response_message', 'responded_by', 'responded_at', 'response_revision_id')
    for name in response_fields:
        assert original_request[name] is None
    author = client.get('/api/v1/me').json()['id']
    before = datetime.now(timezone.utc)
    body = response_body(detail, message='Проверили суммы за три месяца; выручка указана без округления')
    sent = command(client, headers, f'{BASE}/{identifier}/information-responses', body)
    assert sent.status_code == 202, sent.text
    after = datetime.now(timezone.utc)
    for email in (f'demo-{profile}@example.test', 'staff@example.test'):
        authenticate(client, email)
        visible = current(client, identifier)['information_requests'][-1]
        assert visible['response_message'] == body['message']
        assert visible['responded_by'] == author
        assert visible['response_revision_id'] == sent.json()['revision_id']
        assert before <= datetime.fromisoformat(visible['responded_at']) <= after
        assert visible['status'] == 'answered'
        assert {name: value for name, value in visible.items() if name not in (*response_fields, 'status')} == {
            name: value for name, value in original_request.items() if name not in (*response_fields, 'status')
        }
    authenticate(client, 'client2@example.test')
    assert client.get(f'{BASE}/{identifier}').status_code == 404
