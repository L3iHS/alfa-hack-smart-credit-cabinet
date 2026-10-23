import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from test_application_drafts import authenticate, create
from test_processing import prepared, process
from test_review import command, current

EVENTS = '/api/v1/analytics/events'


def observation(kind='form_opened', **fields):
    return {'event_id': str(uuid.uuid4()), 'kind': kind, **fields}


def opened(client, headers, product='working_capital'):
    body = observation(journey_id=str(uuid.uuid4()), product_code=product)
    result = client.post(EVENTS, json=body, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json() == {'event_id': body['event_id'], 'recorded': True}
    return body


@pytest.mark.parametrize('product', ['working_capital', 'equipment', 'overdraft', 'credit_line', 'investment', 'tender_guarantee'])
def test_observations_preserve_credit_history_and_version(client, db, product):
    headers = authenticate(client)
    start = opened(client, headers, product)
    draft = create(client, headers, product_code=product)
    before = client.get(f"/api/v1/applications/{draft['id']}/history").json()
    step = observation('form_step_viewed', journey_id=start['journey_id'], step='finances')
    link = observation('draft_linked', journey_id=start['journey_id'], application_id=draft['id'])
    for body in (start, step, link, link):
        response = client.post(EVENTS, json=body, headers=headers)
        assert response.status_code == 200, response.text
    assert current(client, draft['id'])['version'] == draft['version']
    assert client.get(f"/api/v1/applications/{draft['id']}/history").json() == before
    row = db.execute(text('SELECT application_id, product_code, created_at FROM analytics_journeys')).one()
    assert str(row.application_id) == draft['id'] and row.product_code == product
    assert row.created_at.tzinfo is not None
    assert db.execute(text('SELECT count(*) FROM analytics_events')).scalar_one() == 3
    assert client.post(EVENTS, json={**step, 'step': 'review'}, headers=headers).status_code == 409


@pytest.mark.parametrize('change', [
    {'kind': 'submitted'}, {'amount_kopecks': 100}, {'created_at': '2026-10-01T00:00:00Z'},
    {'user_id': str(uuid.uuid4())}, {'company_id': str(uuid.uuid4())}, {'product_code': 'unknown'},
    {'journey_id': 1}, {'event_id': 123}, {'product_code': 1},
])
def test_strict_observation_payload(client, change):
    headers = authenticate(client)
    body = observation(journey_id=str(uuid.uuid4()), product_code='working_capital')
    assert client.post(EVENTS, json={**body, **change}, headers=headers).status_code == 422


@pytest.mark.parametrize('body', [
    observation('form_step_viewed', journey_id=str(uuid.uuid4()), step='submit'),
    observation('draft_linked', journey_id=str(uuid.uuid4()), application_id=False),
    observation('offer_viewed', offer_id=str(uuid.uuid4()), offer_version=True),
    observation('offer_viewed', offer_id=str(uuid.uuid4()), offer_version='1'),
    observation('offer_viewed', offer_id=str(uuid.uuid4()), offer_version=0),
    observation('form_opened', journey_id=str(uuid.uuid4())),
])
def test_union_rejects_invalid_variant_fields(client, body):
    headers = authenticate(client)
    assert client.post(EVENTS, json=body, headers=headers).status_code == 422


def test_events_require_session_csrf_and_client(client):
    body = observation(journey_id=str(uuid.uuid4()), product_code='working_capital')
    assert client.post(EVENTS, json=body).status_code == 403
    csrf = client.get('/api/v1/auth/csrf').json()['csrf_token']
    assert client.post(EVENTS, json=body, headers={'X-CSRF-Token': csrf}).status_code == 401
    headers = authenticate(client, 'staff@example.test')
    assert client.post(EVENTS, json=body, headers=headers).status_code == 403
    authenticate(client)
    assert client.post(EVENTS, json=body).status_code == 403


def test_journey_and_object_ownership_and_missing_ids(client, db):
    headers = authenticate(client)
    start = opened(client, headers)
    draft = create(client, headers)
    foreign = authenticate(client, 'client2@example.test')
    for body in (
        {**start, 'event_id': str(uuid.uuid4())},
        observation('form_step_viewed', journey_id=start['journey_id'], step='terms'),
        observation('draft_linked', journey_id=start['journey_id'], application_id=draft['id']),
    ):
        assert client.post(EVENTS, json=body, headers=foreign).status_code == 404
    own = opened(client, foreign)
    assert client.post(EVENTS, json=observation('draft_linked', journey_id=own['journey_id'], application_id=draft['id']), headers=foreign).status_code == 404
    assert client.post(EVENTS, json=observation('form_step_viewed', journey_id=str(uuid.uuid4()), step='terms'), headers=foreign).status_code == 404
    assert client.post(EVENTS, json=observation('offer_viewed', offer_id=str(uuid.uuid4()), offer_version=1), headers=foreign).status_code == 404
    assert db.execute(text('SELECT count(*) FROM analytics_events')).scalar_one() == 2


def test_event_key_is_scoped_to_owner(client, db):
    headers = authenticate(client)
    start = opened(client, headers)
    other = authenticate(client, 'client2@example.test')
    body = {**start, 'journey_id': str(uuid.uuid4())}
    assert client.post(EVENTS, json=body, headers=other).status_code == 200
    assert db.execute(text('SELECT count(*) FROM analytics_events')).scalar_one() == 2


def test_binding_is_once_per_journey_and_application(client, db):
    headers = authenticate(client)
    one, two = opened(client, headers), opened(client, headers)
    first, second = create(client, headers), create(client, headers)
    link = observation('draft_linked', journey_id=one['journey_id'], application_id=first['id'])
    assert client.post(EVENTS, json=link, headers=headers).status_code == 200
    assert client.post(EVENTS, json={**link, 'event_id': str(uuid.uuid4())}, headers=headers).status_code == 200
    for changes in ({'application_id': second['id']}, {'journey_id': two['journey_id']}):
        assert client.post(EVENTS, json={**link, 'event_id': str(uuid.uuid4()), **changes}, headers=headers).status_code == 409
    assert db.execute(text('SELECT count(application_id) FROM analytics_journeys')).scalar_one() == 1


def parallel_events(bodies, email='client1@example.test'):
    barrier = Barrier(len(bodies))
    def send(body):
        with TestClient(app) as own:
            headers = authenticate(own, email)
            barrier.wait(timeout=10)
            return own.post(EVENTS, json=body, headers=headers)
    with ThreadPoolExecutor(max_workers=len(bodies)) as pool:
        return list(pool.map(send, bodies))


@pytest.mark.parametrize('race', ['same_event', 'conflicting_event', 'same_journey', 'same_application', 'different_application'])
def test_concurrent_observations_are_atomic(client, db, race):
    headers = authenticate(client)
    if race in ('same_event', 'conflicting_event', 'same_journey'):
        first = observation(journey_id=str(uuid.uuid4()), product_code='working_capital')
        second = dict(first)
        if race == 'conflicting_event':
            second['product_code'] = 'equipment'
        elif race == 'same_journey':
            second['event_id'] = str(uuid.uuid4())
        expected = [200, 409] if race == 'conflicting_event' else [200, 200]
    else:
        one, two = opened(client, headers), opened(client, headers)
        draft = create(client, headers)
        first = observation('draft_linked', journey_id=one['journey_id'], application_id=draft['id'])
        second = observation('draft_linked', journey_id=two['journey_id'], application_id=draft['id'])
        if race == 'different_application':
            second['journey_id'] = one['journey_id']
            second['application_id'] = create(client, headers)['id']
        expected = [200, 409]
    results = parallel_events([first, second])
    assert sorted(item.status_code for item in results) == expected, [item.text for item in results]
    if race in ('same_application', 'different_application'):
        assert db.execute(text('SELECT count(application_id) FROM analytics_journeys')).scalar_one() == 1
    else:
        assert db.execute(text('SELECT count(*) FROM analytics_journeys')).scalar_one() == 1
        assert db.execute(text('SELECT count(*) FROM analytics_events')).scalar_one() == (2 if race == 'same_journey' else 1)


def active_offer(client):
    headers, identifier, _ = prepared(client, 'b')
    process()
    detail = current(client, identifier)
    return headers, identifier, detail, detail['offers'][-1]


def test_offer_views_do_not_mutate_offer_or_application(client, db):
    headers, identifier, detail, offer = active_offer(client)
    before = client.get(f'/api/v1/applications/{identifier}/history').json()
    body = observation('offer_viewed', offer_id=offer['id'], offer_version=offer['version'])
    for event in (body, body, {**body, 'event_id': str(uuid.uuid4())}):
        assert client.post(EVENTS, json=event, headers=headers).status_code == 200
    assert current(client, identifier) == detail
    assert client.get(f'/api/v1/applications/{identifier}/history').json() == before
    assert db.execute(text('SELECT count(*) FROM analytics_events')).scalar_one() == 2
    assert client.post(EVENTS, json={**body, 'event_id': str(uuid.uuid4()), 'offer_version': offer['version'] + 10}, headers=headers).status_code == 409
    foreign = authenticate(client, 'client2@example.test')
    assert client.post(EVENTS, json=body, headers=foreign).status_code == 404


@pytest.mark.parametrize('action', ['accept', 'decline'])
def test_answer_timestamp_reason_and_null_retry_are_atomic(client, db, action):
    headers, identifier, detail, offer = active_offer(client)
    assert offer.get('responded_at') is None and offer.get('decline_reason') is None
    body = {'expected_version': detail['version'], 'offer_version': offer['version']}
    if action == 'decline':
        body['decline_reason'] = 'high_payment'
    key = str(uuid.uuid4())
    path = f"/api/v1/offers/{offer['id']}/{action}"
    before = datetime.now(timezone.utc)
    response = command(client, headers, path, body, key)
    assert response.status_code == 200, response.text
    row = db.execute(text('SELECT responded_at, decline_reason FROM offers')).one()
    assert before <= row.responded_at <= datetime.now(timezone.utc)
    assert row.decline_reason == ('high_payment' if action == 'decline' else None)
    assert response.json()['offer']['responded_at'] is not None
    assert command(client, headers, path, body, key).json() == response.json()
    assert db.execute(text('SELECT responded_at FROM offers')).scalar_one() == row.responded_at
    if action == 'decline':
        assert command(client, headers, path, {**body, 'decline_reason': 'other'}, key).status_code == 409


@pytest.mark.parametrize('reason', ['insufficient_amount', 'high_payment', 'unsuitable_term', 'no_longer_needed', 'other', None])
def test_decline_reason_enum(client, db, reason):
    headers, identifier, detail, offer = active_offer(client)
    body = {'expected_version': detail['version'], 'offer_version': offer['version'], 'decline_reason': reason}
    result = command(client, headers, f"/api/v1/offers/{offer['id']}/decline", body)
    assert result.status_code == 200, result.text
    assert result.json()['offer']['decline_reason'] == reason


def test_accept_rejects_reason_and_decline_rejects_unknown_reason(client):
    headers, _, detail, offer = active_offer(client)
    body = {'expected_version': detail['version'], 'offer_version': offer['version']}
    for reason in ('other', None):
        assert command(client, headers, f"/api/v1/offers/{offer['id']}/accept", {**body, 'decline_reason': reason}).status_code == 422
    for reason in ('anything', 1, True):
        assert command(client, headers, f"/api/v1/offers/{offer['id']}/decline", {**body, 'decline_reason': reason}).status_code == 422


def test_legacy_decline_fingerprint_is_unchanged_and_null_is_equivalent(client, db):
    headers, identifier, detail, offer = active_offer(client)
    body = {'expected_version': detail['version'], 'offer_version': offer['version']}
    path, key = f"/api/v1/offers/{offer['id']}/decline", str(uuid.uuid4())
    response = command(client, headers, path, body, key)
    assert response.status_code == 200
    expected = hashlib.sha256(json.dumps({'application_id': identifier, 'resource_id': offer['id'], **body}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert db.execute(text("SELECT fingerprint FROM idempotency_records WHERE operation='decline_offer'")).scalar_one() == expected
    assert command(client, headers, path, {**body, 'decline_reason': None}, key).json() == response.json()
    # Сохранённый исторический ответ не содержит новых полей и не получает выдуманное время.
    old = response.json()
    old['offer'].pop('responded_at')
    old['offer'].pop('decline_reason')
    db.execute(text("UPDATE offers SET responded_at=NULL, decline_reason=NULL"))
    db.execute(text("UPDATE idempotency_records SET response=CAST(:body AS jsonb) WHERE operation='decline_offer'"), {'body': json.dumps(old)})
    db.commit()
    result = command(client, headers, path, {**body, 'decline_reason': None}, key)
    assert result.status_code == 200, result.text
    assert result.json()['offer']['responded_at'] is None
    assert db.execute(text('SELECT responded_at FROM offers')).scalar_one() is None


@pytest.mark.parametrize('action', ['accept', 'decline'])
def test_view_races_with_answer_and_original_version_remains_observable(client, db, action):
    _, identifier, detail, offer = active_offer(client)
    barrier = Barrier(2)
    view = observation('offer_viewed', offer_id=offer['id'], offer_version=offer['version'])
    def send(viewing):
        with TestClient(app) as own:
            headers = authenticate(own, 'demo-b@example.test')
            barrier.wait(timeout=10)
            if viewing:
                return own.post(EVENTS, json=view, headers=headers)
            return command(own, headers, f"/api/v1/offers/{offer['id']}/{action}", {'expected_version': detail['version'], 'offer_version': offer['version'], **({'decline_reason': 'other'} if action == 'decline' else {})})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, [True, False]))
    assert [item.status_code for item in results] == [200, 200], [item.text for item in results]
    assert db.execute(text('SELECT count(*) FROM analytics_events')).scalar_one() == 1
    assert db.execute(text('SELECT responded_at FROM offers')).scalar_one() is not None


def test_binding_rejects_preexisting_draft_and_other_author(client, db):
    headers = authenticate(client)
    old_draft = create(client, headers)
    start = opened(client, headers)
    body = observation('draft_linked', journey_id=start['journey_id'], application_id=old_draft['id'])
    assert client.post(EVENTS, json=body, headers=headers).status_code == 409
    fresh = create(client, headers)
    db.execute(text('UPDATE applications SET author_id=(SELECT id FROM users WHERE email=:email) WHERE id=:id'), {'email': 'client2@example.test', 'id': fresh['id']})
    db.commit()
    body = observation('draft_linked', journey_id=start['journey_id'], application_id=fresh['id'])
    assert client.post(EVENTS, json=body, headers=headers).status_code == 409
    assert db.execute(text('SELECT application_id FROM analytics_journeys')).scalar_one() is None


def test_database_rejects_view_without_observed_version(client, db):
    from sqlalchemy.exc import IntegrityError
    headers, _, _, offer = active_offer(client)
    user_id = client.get('/api/v1/me').json()['id']
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO analytics_events(user_id,event_id,kind,offer_id,offer_version,payload,created_at) VALUES(:user,:id,'offer_viewed',:offer,NULL,'{}',now())"),
                   {'user': user_id, 'id': uuid.uuid4(), 'offer': offer['id']})
    db.rollback()


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_declines_preserve_winning_reason_and_timestamp(client, db, same_key):
    _, identifier, detail, offer = active_offer(client)
    barrier = Barrier(2)
    key = str(uuid.uuid4())
    reasons = ['high_payment', 'unsuitable_term']
    def send(reason):
        with TestClient(app) as own:
            headers = authenticate(own, 'demo-b@example.test')
            barrier.wait(timeout=10)
            return command(own, headers, f"/api/v1/offers/{offer['id']}/decline", {
                'expected_version': detail['version'], 'offer_version': offer['version'], 'decline_reason': reason,
            }, key if same_key else str(uuid.uuid4()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, reasons))
    assert sorted(item.status_code for item in results) == [200, 409], [item.text for item in results]
    winner = results[0] if results[0].status_code == 200 else results[1]
    row = db.execute(text('SELECT responded_at, decline_reason FROM offers')).one()
    assert row.decline_reason == winner.json()['offer']['decline_reason']
    assert row.responded_at == datetime.fromisoformat(winner.json()['offer']['responded_at'])
    assert current(client, identifier)['version'] == detail['version'] + 1


def test_link_can_arrive_after_submission_without_changing_credit_state(client, db):
    headers = authenticate(client, 'demo-b@example.test')
    start = opened(client, headers)
    headers, identifier, submission = prepared(client, 'b')
    process()
    before = current(client, identifier)
    result = client.post(EVENTS, json=observation('draft_linked', journey_id=start['journey_id'], application_id=identifier), headers=headers)
    assert result.status_code == 200, result.text
    assert current(client, identifier) == before
