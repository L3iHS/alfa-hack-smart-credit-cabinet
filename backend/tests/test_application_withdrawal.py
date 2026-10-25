import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from test_auth import csrf
from test_application_drafts import BASE, authenticate, create, patch
from test_documents import upload
from test_processing import prepared, process
from test_review import command, current, response_body
from test_submission import submit


def withdraw(client, headers, detail):
    return client.post(f"{BASE}/{detail['id']}/withdraw", headers=headers,
                       json={'expected_version': detail['version']})


@pytest.mark.parametrize('status,profile', [
    ('submitted', 'a'), ('processing', 'a'), ('needs_info', 'c'),
    ('manual_review', 'd'), ('counteroffer', 'b'),
])
def test_withdraw_active_application_preserves_evidence(client, db, status, profile):
    headers, identifier, submission = prepared(client, profile)
    if status == 'processing':
        from app.processing.service import claim_next
        assert claim_next() is not None
    elif status != 'submitted':
        assert process()
    detail = current(client, identifier)
    assert detail['status'] == status
    assert 'withdraw' in detail['available_actions']
    # Отзыв меняет состояние рассмотрения, но сохраняет исходные финансовые сведения.
    preserved = {table: db.execute(text(f'SELECT * FROM {table} ORDER BY id')).all()
                 for table in ('documents', 'application_revisions', 'check_results', 'calculations', 'decisions')}
    documents = client.get(f'{BASE}/{identifier}/documents').json()
    response = withdraw(client, headers, detail)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['id'] == identifier and result['status'] == 'withdrawn'
    assert result['version'] == detail['version'] + 1
    assert result['available_actions'] == []
    assert result['public_reasons'] == ['Заявка отозвана клиентом. Рассмотрение прекращено.']
    assert not set(result['public_reasons']) & set(detail['public_reasons'])
    assert result['information_requests'] == detail['information_requests']
    assert current(client, identifier) == result
    assert client.get(BASE, params={'status': 'withdrawn'}).json()['items'] == [result]
    for table, rows in preserved.items():
        assert db.execute(text(f'SELECT * FROM {table} ORDER BY id')).all() == rows
    assert client.get(f'{BASE}/{identifier}/documents').json() == documents
    for document in documents['items']:
        assert client.get(f"{BASE}/{identifier}/documents/{document['id']}").status_code == 200
    event = client.get(f'{BASE}/{identifier}/history').json()['items'][-1]
    assert event['event_type'] == 'application_withdrawn'
    assert event['application_version'] == result['version']
    assert event['actor_type'] == 'user' and event['actor_id']
    assert event['revision_id'] == submission['revision_id']
    assert event['processing_run_id'] == submission['processing_run_id']
    run = db.execute(text('SELECT status, error_code, finished_at FROM processing_runs')).one()
    if status in ('submitted', 'processing'):
        assert run.status == 'interrupted' and run.error_code == 'application_withdrawn'
        assert run.finished_at is not None
        assert not process()
        from app.processing.service import recover_interrupted
        assert recover_interrupted() == 0
        assert current(client, identifier) == result
    else:
        assert run.status == 'succeeded' and run.error_code is None
    if status == 'counteroffer':
        offer = result['offers'][-1]
        assert offer['status'] == 'superseded'
        assert offer['version'] == detail['offers'][-1]['version'] + 1
        assert offer['responded_at'] is None and offer['decline_reason'] is None


@pytest.mark.parametrize('profile,status', [('a', 'approved'), ('e', 'rejected'), (None, 'draft')])
def test_final_decision_or_draft_cannot_be_withdrawn(client, db, profile, status):
    if profile:
        headers, identifier, _ = prepared(client, profile)
        assert process()
        detail = current(client, identifier)
    else:
        headers = authenticate(client)
        detail = create(client, headers)
        identifier = detail['id']
    assert detail['status'] == status and 'withdraw' not in detail['available_actions']
    history = client.get(f'{BASE}/{identifier}/history').json()
    assert withdraw(client, headers, detail).status_code == 409
    assert current(client, identifier) == detail
    assert client.get(f'{BASE}/{identifier}/history').json() == history


def test_withdraw_requires_owner_client_session_and_csrf(client, db):
    _, identifier, _ = prepared(client)
    detail = current(client, identifier)
    with TestClient(app) as anonymous:
        assert withdraw(anonymous, {}, detail).status_code == 403
        assert withdraw(anonymous, {'X-CSRF-Token': csrf(anonymous)}, detail).status_code == 401
    assert withdraw(client, {}, detail).status_code == 403
    staff = authenticate(client, 'staff@example.test')
    assert withdraw(client, staff, detail).status_code == 403
    other = authenticate(client, 'client2@example.test')
    assert withdraw(client, other, detail).status_code == 404
    assert withdraw(client, other, {**detail, 'id': str(uuid.uuid4())}).status_code == 404
    authenticate(client, 'demo-a@example.test')
    assert current(client, identifier) == detail
    assert db.execute(text("SELECT count(*) FROM application_events WHERE event_type='application_withdrawn'")).scalar_one() == 0


@pytest.mark.parametrize('body', [{}, {'expected_version': True}, {'expected_version': '4'},
                                 {'expected_version': 0}, {'expected_version': 2**31},
                                 {'expected_version': 1, 'status': 'withdrawn'}])
def test_withdraw_validates_version_and_forbids_extra_fields(client, body):
    headers, identifier, _ = prepared(client)
    response = client.post(f'{BASE}/{identifier}/withdraw', headers=headers, json=body)
    assert response.status_code == 422, response.text


def test_withdraw_stale_and_repeated_commands_do_not_duplicate_event(client, db):
    headers, identifier, _ = prepared(client)
    detail = current(client, identifier)
    assert withdraw(client, headers, {**detail, 'version': detail['version'] - 1}).status_code == 409
    response = withdraw(client, headers, detail)
    assert response.status_code == 200, response.text
    result = response.json()
    assert withdraw(client, headers, detail).status_code == 409
    assert withdraw(client, headers, result).status_code == 409
    assert current(client, identifier) == result
    assert db.execute(text("SELECT count(*) FROM application_events WHERE event_type='application_withdrawn'")).scalar_one() == 1


def test_withdraw_rolls_back_all_changes_when_history_write_fails(client, db):
    headers, identifier, _ = prepared(client)
    detail = current(client, identifier)
    db.execute(text("CREATE FUNCTION reject_withdraw_event() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.event_type = 'application_withdrawn' THEN RAISE EXCEPTION 'test event failure'; END IF; RETURN NEW; END $$"))
    db.execute(text('CREATE TRIGGER reject_withdraw_event BEFORE INSERT ON application_events FOR EACH ROW EXECUTE FUNCTION reject_withdraw_event()'))
    db.commit()
    try:
        assert withdraw(client, headers, detail).status_code == 503
        assert current(client, identifier) == detail
        assert db.execute(text('SELECT status FROM processing_runs')).scalar_one() == 'pending'
    finally:
        db.execute(text('DROP TRIGGER reject_withdraw_event ON application_events'))
        db.execute(text('DROP FUNCTION reject_withdraw_event()'))
        db.commit()


@pytest.mark.parametrize('provider_fails', [False, True])
def test_withdraw_during_inflight_check_fences_late_result_or_error(client, db, monkeypatch, provider_fails):
    from app.processing import providers
    headers, identifier, _ = prepared(client)
    entered, release = Event(), Event()
    original = providers.check

    def paused(kind, snapshot, version):
        if kind == 'bki':
            entered.set()
            assert release.wait(15)
            if provider_fails:
                raise RuntimeError('Поздний сбой источника')
        return original(kind, snapshot, version)

    monkeypatch.setattr(providers, 'check', paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(process)
        try:
            assert entered.wait(15)
            detail = current(client, identifier)
            assert detail['status'] == 'processing'
            response = withdraw(client, headers, detail)
            assert response.status_code == 200, response.text
            withdrawn = response.json()
        finally:
            release.set()
        assert worker.result(timeout=15)
    assert current(client, identifier) == withdrawn
    assert db.execute(text('SELECT kind FROM check_results ORDER BY kind')).scalars().all() == ['registry', 'tax']
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0
    assert db.execute(text('SELECT count(*) FROM calculations')).scalar_one() == 0
    assert db.execute(text('SELECT error_code FROM processing_runs')).scalar_one() == 'application_withdrawn'
    assert client.get(f'{BASE}/{identifier}/history').json()['items'][-1]['event_type'] == 'application_withdrawn'


@pytest.mark.parametrize('scorer_fails', [False, True])
def test_withdraw_during_inflight_risk_does_not_persist_late_assessment(client, db, monkeypatch, scorer_fails):
    from app.risk import assessments
    headers, identifier, _ = prepared(client, legacy=False)
    entered, release = Event(), Event()
    original = assessments.score_features

    def paused(features, *, model_version):
        entered.set()
        assert release.wait(15)
        if scorer_fails:
            raise assessments.RiskModelError('Поздний сбой модели')
        return original(features, model_version=model_version)

    monkeypatch.setattr(assessments, 'score_features', paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(process)
        try:
            assert entered.wait(15)
            response = withdraw(client, headers, current(client, identifier))
            assert response.status_code == 200, response.text
            withdrawn = response.json()
        finally:
            release.set()
        assert worker.result(timeout=15)
    assert current(client, identifier) == withdrawn
    assert db.execute(text('SELECT count(*) FROM check_results')).scalar_one() == 3
    for table in ('risk_assessments', 'decisions', 'calculations'):
        assert db.execute(text(f'SELECT count(*) FROM {table}')).scalar_one() == 0
    assert db.execute(text('SELECT error_code FROM processing_runs')).scalar_one() == 'application_withdrawn'
    assert client.get(f'{BASE}/{identifier}/history').json()['items'][-1]['event_type'] == 'application_withdrawn'


@pytest.mark.parametrize('opponent', ['withdraw', 'accept', 'decision'])
def test_withdraw_race_has_one_winner_and_one_event(client, db, opponent):
    profile = 'd' if opponent == 'decision' else 'b'
    _, identifier, _ = prepared(client, profile)
    assert process()
    detail = current(client, identifier)
    old_events = client.get(f'{BASE}/{identifier}/history').json()['total']
    barrier = Barrier(2)

    def act(operation):
        with TestClient(app) as own:
            email = 'staff@example.test' if operation == 'decision' else f'demo-{profile}@example.test'
            headers = authenticate(own, email)
            barrier.wait(timeout=15)
            if operation == 'withdraw':
                return withdraw(own, headers, detail)
            if operation == 'accept':
                offer = detail['offers'][-1]
                return command(own, headers, f"/api/v1/offers/{offer['id']}/accept",
                               {'expected_version': detail['version'], 'offer_version': offer['version']})
            return command(own, headers, f'{BASE}/{identifier}/decisions',
                           {'expected_version': detail['version'], 'outcome': 'rejected', 'reason': 'Решение сотрудника'})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(act, ['withdraw', opponent]))
    assert sum(response.status_code in (200, 201) for response in responses) == 1, [r.text for r in responses]
    assert sum(response.status_code == 409 for response in responses) == 1
    result = current(client, identifier)
    assert result['version'] == detail['version'] + 1
    assert result['status'] in ('withdrawn', 'approved', 'rejected')
    assert client.get(f'{BASE}/{identifier}/history').json()['total'] == old_events + 1
    if result['status'] == 'withdrawn':
        assert db.execute(text('SELECT count(*) FROM decisions WHERE actor_id IS NOT NULL')).scalar_one() == 0


@pytest.mark.parametrize('profile', ['b', 'c', 'd'])
def test_withdrawn_application_rejects_followup_business_commands(client, profile):
    headers, identifier, _ = prepared(client, profile)
    assert process()
    detail = current(client, identifier)
    response = withdraw(client, headers, detail)
    assert response.status_code == 200, response.text
    withdrawn = response.json()
    assert patch(client, headers, withdrawn, purpose='Изменить после отзыва').status_code == 409
    assert upload(client, headers, withdrawn).status_code == 409
    document = client.get(f'{BASE}/{identifier}/documents').json()['items'][0]
    assert client.delete(f"{BASE}/{identifier}/documents/{document['id']}",
                         params={'expected_version': withdrawn['version']}, headers=headers).status_code == 409
    assert submit(client, headers, withdrawn).status_code == 409
    if profile == 'c':
        assert command(client, headers, f'{BASE}/{identifier}/information-responses', response_body(withdrawn)).status_code == 409
    if profile == 'b':
        offer = withdrawn['offers'][-1]
        for action in ('accept', 'decline'):
            assert command(client, headers, f"/api/v1/offers/{offer['id']}/{action}",
                           {'expected_version': withdrawn['version'], 'offer_version': offer['version']}).status_code == 409
    staff = authenticate(client, 'staff@example.test')
    assert current(client, identifier)['available_actions'] == []
    bodies = {
        'decisions': {'outcome': 'rejected', 'reason': 'Позднее решение'},
        'offers': {'amount_kopecks': 40000000, 'term_months': 12, 'reason': 'Позднее предложение'},
        'information-requests': {'message': 'Уточните данные', 'requested_fields': ['purpose']},
        'processing-retries': {},
    }
    for suffix, body in bodies.items():
        assert command(client, staff, f'{BASE}/{identifier}/{suffix}',
                       {'expected_version': withdrawn['version'], **body}).status_code == 409
    assert current(client, identifier) == withdrawn
