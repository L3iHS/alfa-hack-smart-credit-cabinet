import calendar
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.main import app
from test_auth import login

BASE = '/api/v1/applications'


def authenticate(client, email='client1@example.test'):
    return {'X-CSRF-Token': login(client, email).json()['csrf_token']}


def create(client, headers, **fields):
    response = client.post(BASE, json={'product_code': 'working_capital', **fields}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, headers, draft, **fields):
    return client.patch(f"{BASE}/{draft['id']}", json={'expected_version': draft['version'], **fields}, headers=headers)


def test_draft_survives_new_db_session(client):
    headers = authenticate(client)
    draft = create(client, headers, purpose='Закупка сырья', amount_kopecks=10_000_001)
    assert draft['version'] == 1 and draft['status'] == 'draft'
    assert draft['catalog_version'] == 'demo-v1'
    assert draft['public_reasons'] == [] and draft['available_actions'] == ['edit_draft', 'upload_document', 'submit']
    assert set(draft) == {'id', 'version', 'status', 'updated_at', 'catalog_version', 'product_code', 'purpose', 'description', 'amount_kopecks', 'term_months', 'period_start', 'period_end', 'revenue_kopecks', 'operating_expenses_kopecks', 'existing_debt_payments_kopecks', 'public_reasons', 'available_actions', 'processing_status', 'information_requests', 'offers'}
    uuid.UUID(draft['id'])
    with SessionLocal() as fresh:
        row = fresh.execute(text('SELECT version, amount_kopecks FROM applications WHERE id=:id'), {'id': draft['id']}).one()
        assert tuple(row) == (1, 10_000_001)
    with TestClient(app) as fresh_client:
        authenticate(fresh_client)
        assert fresh_client.get(f"{BASE}/{draft['id']}").json() == draft
    history = client.get(f"{BASE}/{draft['id']}/history").json()
    assert history['total'] == 1
    assert history['items'][0]['event_type'] == 'draft_created'
    assert history['items'][0]['application_version'] == 1
    assert set(history['items'][0]) == {'id', 'event_type', 'created_at', 'application_version', 'actor_type', 'actor_id', 'revision_id', 'processing_run_id'}


def test_foreign_draft_is_404(client):
    headers = authenticate(client)
    draft = create(client, headers)
    headers = authenticate(client, 'client2@example.test')
    for suffix in ('', '/history'):
        assert client.get(f"{BASE}/{draft['id']}{suffix}").status_code == 404
    assert patch(client, headers, draft, purpose='Чужая заявка').status_code == 404
    assert client.get(f'{BASE}/{uuid.uuid4()}').status_code == 404


def test_staff_cannot_edit_draft(client):
    headers = authenticate(client)
    draft = create(client, headers)
    headers = authenticate(client, 'staff@example.test')
    assert client.post(BASE, headers=headers, json={'product_code': 'equipment'}).status_code == 403
    assert patch(client, headers, draft, purpose='Изменение').status_code == 403
    assert client.get(f"{BASE}/{draft['id']}").status_code == 404
    assert client.get(f"{BASE}/{draft['id']}/history").status_code == 404
    assert client.get(BASE).json()['items'] == []


def test_stale_patch_is_409(client):
    headers = authenticate(client)
    draft = create(client, headers)
    response = patch(client, headers, draft, purpose='Сырьё')
    assert response.status_code == 200
    updated = response.json()
    assert updated['version'] == 2 and updated['purpose'] == 'Сырьё'
    assert patch(client, headers, draft, purpose='Сырьё').status_code == 409
    assert patch(client, headers, updated, purpose='Сырьё').json() == updated
    history = client.get(f"{BASE}/{draft['id']}/history").json()
    assert history['total'] == 2
    assert [(event['event_type'], event['application_version']) for event in history['items']] == [('draft_created', 1), ('draft_updated', 2)]


def test_concurrent_patch_has_one_winner(client):
    headers = authenticate(client)
    draft = create(client, headers)
    barrier = Barrier(2)

    def change(purpose):
        with TestClient(app) as concurrent:
            # Разные сессии исключают сериализацию только на auth_sessions.
            own_headers = authenticate(concurrent)
            barrier.wait(timeout=10)
            return patch(concurrent, own_headers, draft, purpose=purpose)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(change, ['Первый', 'Второй']))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert client.get(f"{BASE}/{draft['id']}").json() == winner
    events = client.get(f"{BASE}/{draft['id']}/history").json()
    assert events['total'] == 2
    assert [event['application_version'] for event in events['items']] == [1, 2]


@pytest.mark.parametrize('field,value', [('company_id', str(uuid.uuid4())), ('status', 'approved'), ('version', 9), ('unknown', 3)])
def test_unknown_or_forbidden_fields_are_422(client, field, value):
    headers = authenticate(client)
    draft = create(client, headers)
    for response in [client.post(BASE, headers=headers, json={'product_code': 'equipment', field: value}), patch(client, headers, draft, **{field: value})]:
        assert response.status_code == 422
        assert field in response.json()['field_errors']
    assert client.get(f"{BASE}/{draft['id']}/history").json()['total'] == 1


def test_partial_draft_and_period_validation(client):
    headers = authenticate(client)
    draft = create(client, headers)
    assert draft['purpose'] is None and draft['revenue_kopecks'] is None
    partial = patch(client, headers, draft, period_start='2024-02-01')
    assert partial.status_code == 200
    draft = partial.json()
    assert patch(client, headers, draft, period_end='2024-02-29').status_code == 200
    draft = client.get(f"{BASE}/{draft['id']}").json()
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    for fields in [
        {'period_start': '2024-02-02'}, {'period_end': '2024-02-28'},
        {'period_start': '2024-03-01', 'period_end': '2024-02-29'},
        {'period_start': today.replace(day=1).isoformat(), 'period_end': today.replace(day=last_day).isoformat()},
        {'period_start': '2025-02-01', 'period_end': '2025-02-29'},
        {'product_code': 'absent'}, {'product_code': None},
        {'amount_kopecks': 9_999_999}, {'term_months': 25},
    ]:
        assert patch(client, headers, draft, **fields).status_code == 422, fields
    assert patch(client, headers, draft, period_start=None, period_end=None).status_code == 200


@pytest.mark.parametrize('field', ['amount_kopecks', 'revenue_kopecks', 'operating_expenses_kopecks', 'existing_debt_payments_kopecks', 'term_months'])
@pytest.mark.parametrize('value', [-1, 0.1, 10000000.0, True, '10000000', 2**63])
def test_money_uses_integer_kopecks(client, field, value):
    headers = authenticate(client)
    draft = create(client, headers)
    assert patch(client, headers, draft, **{field: value}).status_code == 422
    assert client.get(f"{BASE}/{draft['id']}").json()['version'] == 1


def test_exact_money_product_switch_and_null(client):
    headers = authenticate(client)
    draft = create(client, headers, amount_kopecks=10_000_001, term_months=3, revenue_kopecks=9_007_199_254_740_991, operating_expenses_kopecks=0)
    assert draft['revenue_kopecks'] == 9_007_199_254_740_991
    assert patch(client, headers, draft, product_code='equipment').status_code == 422
    response = patch(client, headers, draft, product_code='equipment', amount_kopecks=30_000_001, term_months=6)
    assert response.status_code == 200
    updated = response.json()
    assert updated['amount_kopecks'] == 30_000_001
    cleared = patch(client, headers, updated, amount_kopecks=None, term_months=None)
    assert cleared.status_code == 200 and cleared.json()['amount_kopecks'] is None


def test_pagination_limits_and_company_scope(client):
    headers = authenticate(client)
    drafts = [create(client, headers) for _ in range(3)]
    page = client.get(BASE, params={'limit': 1, 'offset': 1}).json()
    assert page['total'] == 3 and page['limit'] == 1 and page['offset'] == 1
    assert page['items'][0]['id'] == drafts[1]['id']
    for params in [{'limit': 0}, {'limit': 101}, {'offset': -1}]:
        assert client.get(BASE, params=params).status_code == 422
        assert client.get(f"{BASE}/{drafts[0]['id']}/history", params=params).status_code == 422
    assert client.get(BASE, params={'offset': 99}).json()['items'] == []
    assert client.get(BASE).json()['limit'] == 20
    assert client.get(BASE, params={'limit': 100}).status_code == 200
    assert client.get(f"{BASE}/{drafts[0]['id']}/history", params={'limit': 1, 'offset': 1}).json()['items'] == []
    headers = authenticate(client, 'client2@example.test')
    assert client.get(BASE).json()['total'] == 0
    create(client, headers)
    assert client.get(BASE).json()['total'] == 1


def test_creation_validation_and_required_version(client):
    headers = authenticate(client)
    for fields in [{}, {'product_code': 'unknown'}, {'product_code': None}, {'product_code': 'equipment', 'term_months': 5}]:
        assert client.post(BASE, json=fields, headers=headers).status_code == 422
    draft = create(client, headers)
    for fields in [{'purpose': 'test'}, {'expected_version': None}, {'expected_version': True}, {'expected_version': 0}]:
        assert client.patch(f"{BASE}/{draft['id']}", json=fields, headers=headers).status_code == 422


def test_atomic_history_failure_rolls_back_version_and_creation(client, db):
    headers = authenticate(client)
    draft = create(client, headers)
    # Реальный сбой записи события в PostgreSQL проверяет границу транзакции.
    db.execute(text("CREATE FUNCTION reject_draft_event() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test event failure'; END $$"))
    db.execute(text('CREATE TRIGGER reject_draft_event BEFORE INSERT ON application_events FOR EACH ROW EXECUTE FUNCTION reject_draft_event()'))
    db.commit()
    try:
        assert patch(client, headers, draft, purpose='Не сохранять').status_code == 503
        assert client.post(BASE, headers=headers, json={'product_code': 'equipment'}).status_code == 503
        assert client.get(f"{BASE}/{draft['id']}").json() == draft
        assert client.get(BASE).json()['total'] == 1
        assert client.get(f"{BASE}/{draft['id']}/history").json()['total'] == 1
    finally:
        db.execute(text('DROP TRIGGER reject_draft_event ON application_events'))
        db.execute(text('DROP FUNCTION reject_draft_event()'))
        db.commit()


def test_draft_api_auth_and_openapi(client):
    for path in [BASE, '/api/v1/company', f'{BASE}/{uuid.uuid4()}', f'{BASE}/{uuid.uuid4()}/history']:
        assert client.get(path).status_code == 401
    headers = authenticate(client)
    draft = create(client, headers)
    assert client.post(BASE, json={'product_code': 'equipment'}).status_code == 403
    assert client.patch(f"{BASE}/{draft['id']}", json={'expected_version': 1}).status_code == 403
    schema = client.get('/api/v1/openapi.json').json()
    for path in [BASE, '/api/v1/products', '/api/v1/company', f'{BASE}/{{application_id}}', f'{BASE}/{{application_id}}/history']:
        assert path in schema['paths']
    patch_schema = schema['paths'][f'{BASE}/{{application_id}}']['patch']
    assert {'404', '409', '422'} <= patch_schema['responses'].keys()


@pytest.mark.parametrize('field', ['revenue_kopecks', 'operating_expenses_kopecks', 'existing_debt_payments_kopecks'])
def test_financial_totals_are_safe_json_integers(client, field):
    headers = authenticate(client)
    draft = create(client, headers, **{field: 9_007_199_254_740_991})
    assert draft[field] == 9_007_199_254_740_991
    assert patch(client, headers, draft, **{field: 9_007_199_254_740_992}).status_code == 422
    assert client.get(f"{BASE}/{draft['id']}").json() == draft


def test_patch_product_code_openapi_matches_runtime(client):
    headers = authenticate(client)
    draft = create(client, headers)
    assert patch(client, headers, draft).json() == draft
    assert patch(client, headers, draft, product_code=None).status_code == 422
    changed = patch(client, headers, draft, product_code='equipment')
    assert changed.status_code == 200
    assert changed.json()['product_code'] == 'equipment'
    assert changed.json()['version'] == 2
    schema = client.get('/api/v1/openapi.json').json()['components']['schemas']['DraftPatch']
    assert 'product_code' not in schema['required']
    product = schema['properties']['product_code']
    assert product.get('type') == 'string'
    assert product['enum'] == ['working_capital', 'equipment']
    assert 'anyOf' not in product
    assert 'default' not in product
