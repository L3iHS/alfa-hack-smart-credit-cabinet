"""Оформление использует принятое решение, не пересчитывая кредит."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.auth.models import User
from app.core.db import SessionLocal
from app.main import app
from test_application_drafts import BASE, authenticate
from test_processing import prepared, process
from test_product_processing import CASES, new_submission
from test_review import command, current
from test_assistant_chat import fake  # noqa: F401


def deal_command(client, headers, identifier, action, version, key=None, **changes):
    return command(client, headers, f'{BASE}/{identifier}/deal/{action}',
                   {'expected_version': version, **changes}, key)


def approved(client, *, code='equipment', accept=False):
    if code == 'equipment' and accept:
        from app.demo.profiles import application_fields
        from test_application_drafts import create
        from test_documents import attach
        from test_submission import submit
        headers = authenticate(client, 'demo-d@example.test')
        draft = create(client, headers, **{**application_fields('d'), 'product_code': 'equipment'})
        draft, _ = attach(client, headers, draft)
        draft, _ = attach(client, headers, draft, 'equipment_invoice')
        sent = submit(client, headers, draft)
        assert sent.status_code == 202, sent.text
        assert process()
        identifier, email = draft['id'], 'demo-d@example.test'
    elif code in ('equipment', 'working_capital'):
        profile = 'b' if accept else 'a' if code == 'equipment' else 'd'
        _, identifier, _ = prepared(client, profile)
        assert process()
        email = f'demo-{profile}@example.test'
    else:
        _, identifier, _ = new_submission(client, next(case for case in CASES if case[0] == code))
        email = 'client1@example.test'
    staff = authenticate(client, 'staff@example.test')
    detail = current(client, identifier)
    if accept:
        if detail['status'] != 'counteroffer':
            made = command(client, staff, f'{BASE}/{identifier}/offers', {
                'expected_version': detail['version'], 'amount_kopecks': detail['amount_kopecks'],
                'term_months': detail['term_months'], 'reason': 'Согласованные условия', 'risk_acknowledged': True})
            assert made.status_code == 201, made.text
            detail = current(client, identifier)
        offer = detail['offers'][-1]
        client_headers = authenticate(client, email)
        accepted = command(client, client_headers, f"/api/v1/offers/{offer['id']}/accept", {
            'expected_version': detail['version'], 'offer_version': offer['version']})
        assert accepted.status_code == 200, accepted.text
        staff = authenticate(client, 'staff@example.test')
    elif detail['status'] == 'manual_review':
        result = command(client, staff, f'{BASE}/{identifier}/decisions', {
            'expected_version': detail['version'], 'outcome': 'approved',
            'reason': 'Проверено сотрудником', 'risk_acknowledged': True})
        assert result.status_code == 201, result.text
    return identifier, email, staff, current(client, identifier)


@pytest.mark.parametrize('code,kind', [('working_capital', 'credit'), ('equipment', 'credit'),
    ('overdraft', 'limit'), ('credit_line', 'limit'), ('investment', 'credit'), ('tender_guarantee', 'guarantee')])
@pytest.mark.parametrize('accept', [False, True])
def test_all_products_preserve_approved_terms_and_finish(client, db, monkeypatch, code, kind, accept):
    identifier, email, staff, before = approved(client, code=code, accept=accept)
    assert before['deal'] is None and 'prepare_deal' in before['available_actions']
    snapshot = db.execute(text("SELECT payment_terms FROM decisions WHERE outcome='approved' ORDER BY application_version DESC LIMIT 1")).scalar_one()
    assert snapshot is not None
    original = db.execute(text('SELECT to_jsonb(d) FROM decisions d ORDER BY application_version')).scalars().all()
    if accept:
        assert snapshot == before['offers'][-1]['payment_terms']
    from app.products import calculations
    monkeypatch.setattr(calculations, 'calculate_terms', lambda *a, **k: pytest.fail('Оформление не пересчитывает решение'))
    result = deal_command(client, staff, identifier, 'prepare', before['version'])
    assert result.status_code == 200, result.text
    detail = result.json()
    deal = detail['deal']
    assert detail['status'] == 'approved' and detail['version'] == before['version'] + 1
    assert (deal['status'], deal['completion_kind'], deal['product_code']) == ('prepared', kind, code)
    assert deal['amount_kopecks'] == snapshot['amount_kopecks']
    assert deal['term_months'] == snapshot['term_months']
    assert deal['payment_terms'] == snapshot
    assert deal['reference'] and deal['product_name']
    assert deal['available_actions'] == ['cancel_deal']
    assert detail['available_actions'] == []
    headers = authenticate(client, email)
    detail = current(client, identifier)
    assert detail['deal']['available_actions'] == ['confirm_deal', 'cancel_deal']
    result = deal_command(client, headers, identifier, 'confirm', detail['version'], terms_confirmed=True)
    assert result.status_code == 200, result.text
    detail = result.json()
    assert detail['deal']['confirmed_at'] and detail['deal']['status'] == 'confirmed'
    staff = authenticate(client, 'staff@example.test')
    assert current(client, identifier)['deal']['available_actions'] == ['complete_deal', 'cancel_deal']
    result = deal_command(client, staff, identifier, 'complete', detail['version'])
    assert result.status_code == 200, result.text
    finished = result.json()
    assert finished['status'] == 'approved' and finished['deal']['status'] == 'completed'
    assert finished['deal']['completed_at'] and finished['deal']['available_actions'] == []
    assert finished['deal']['payment_terms'] == snapshot
    assert db.execute(text('SELECT to_jsonb(d) FROM decisions d ORDER BY application_version')).scalars().all() == original
    history = client.get(f'{BASE}/{identifier}/history').json()['items']
    assert [item['event_type'] for item in history[-3:]] == ['deal_prepared', 'deal_confirmed', 'deal_completed']
    assert all(item['revision_id'] for item in history[-3:])


@pytest.mark.parametrize('action', ['prepare', 'confirm', 'complete', 'cancel'])
@pytest.mark.parametrize('same_key', [True, False])
def test_commands_serialize_and_replay_exact_response(client, db, action, same_key):
    identifier, email, staff, detail = approved(client)
    if action != 'prepare':
        detail = deal_command(client, staff, identifier, 'prepare', detail['version']).json()
    if action == 'complete':
        headers = authenticate(client, email)
        detail = deal_command(client, headers, identifier, 'confirm', detail['version'], terms_confirmed=True).json()
    actor = email if action == 'confirm' else 'staff@example.test'
    extras = {'terms_confirmed': True} if action == 'confirm' else {'reason': 'Финансирование больше не нужно'} if action == 'cancel' else {}
    keys = [str(uuid.uuid4()), str(uuid.uuid4())]
    if same_key:
        keys[1] = keys[0]
    barrier = Barrier(2)
    def send(key):
        with TestClient(app) as own:
            headers = authenticate(own, actor)
            barrier.wait(timeout=15)
            return deal_command(own, headers, identifier, action, detail['version'], key, **extras)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, keys))
    assert sorted(item.status_code for item in results) == ([200, 200] if same_key else [200, 409]), [item.text for item in results]
    if same_key:
        assert results[0].json() == results[1].json()
    staff = authenticate(client, 'staff@example.test')
    assert current(client, identifier)['version'] == detail['version'] + 1
    assert db.execute(text('SELECT count(*) FROM deals')).scalar_one() == 1
    assert db.execute(text('SELECT count(*) FROM application_events WHERE event_type=:event'), {'event': f'deal_{"prepared" if action == "prepare" else "confirmed" if action == "confirm" else "completed" if action == "complete" else "cancelled"}'}).scalar_one() == 1


def test_complete_races_cancel_and_terminals_are_final(client, db):
    identifier, email, staff, detail = approved(client)
    detail = deal_command(client, staff, identifier, 'prepare', detail['version']).json()
    headers = authenticate(client, email)
    detail = deal_command(client, headers, identifier, 'confirm', detail['version'], terms_confirmed=True).json()
    barrier = Barrier(2)
    def send(action):
        with TestClient(app) as own:
            headers = authenticate(own, 'staff@example.test')
            barrier.wait(timeout=15)
            return deal_command(own, headers, identifier, action, detail['version'], **({'reason': 'Отмена оформления'} if action == 'cancel' else {}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, ['complete', 'cancel']))
    assert sorted(item.status_code for item in results) == [200, 409]
    staff = authenticate(client, 'staff@example.test')
    detail = current(client, identifier)
    assert detail['deal']['status'] in ('completed', 'cancelled')
    assert detail['deal']['available_actions'] == []
    for action in ('prepare', 'complete', 'cancel'):
        assert deal_command(client, staff, identifier, action, detail['version'], **({'reason': 'Новая причина'} if action == 'cancel' else {})).status_code == 409


def test_access_versions_validation_and_idempotency_scope(client, db):
    identifier, email, staff, before = approved(client)
    path = f'{BASE}/{identifier}/deal/prepare'
    assert client.post(path, json={'expected_version': before['version']}).status_code == 403
    assert command(client, staff, path, {'expected_version': before['version'] - 1}).status_code == 409
    for version in (True, 0, '1'):
        assert command(client, staff, path, {'expected_version': version}).status_code == 422
    assert client.post(path, json={'expected_version': before['version']}, headers=staff).status_code == 422
    key = str(uuid.uuid4())
    detail = deal_command(client, staff, identifier, 'prepare', before['version'], key).json()
    assert deal_command(client, staff, identifier, 'prepare', detail['version'], key).status_code == 409
    foreign = authenticate(client, 'client2@example.test')
    for action in ('prepare', 'confirm', 'complete', 'cancel'):
        extra = {'terms_confirmed': True} if action == 'confirm' else {'reason': 'Отмена'} if action == 'cancel' else {}
        response = deal_command(client, foreign, identifier, action, detail['version'], **extra)
        assert response.status_code in (403, 404)
    assert client.get(f'{BASE}/{identifier}/deal/document').status_code == 404
    headers = authenticate(client, email)
    assert deal_command(client, headers, identifier, 'prepare', detail['version']).status_code == 403
    assert deal_command(client, headers, identifier, 'complete', detail['version']).status_code == 403
    for value in (False, 1, 'true', None):
        assert deal_command(client, headers, identifier, 'confirm', detail['version'], terms_confirmed=value).status_code == 422
    for reason in ('  ', 'x' * 1001):
        assert deal_command(client, headers, identifier, 'cancel', detail['version'], reason=reason).status_code == 422
    staff = authenticate(client, 'staff@example.test')
    assert deal_command(client, staff, identifier, 'confirm', detail['version'], terms_confirmed=True).status_code == 403
    assert deal_command(client, staff, identifier, 'complete', detail['version']).status_code == 409
    headers = authenticate(client, email)
    result = deal_command(client, headers, identifier, 'cancel', detail['version'], reason='  Отменено клиентом  ')
    assert result.status_code == 200, result.text
    detail = result.json()
    assert detail['deal']['cancel_reason'] == 'Отменено клиентом' and detail['deal']['cancelled_at']
    assert deal_command(client, headers, identifier, 'confirm', detail['version'], terms_confirmed=True).status_code == 409
    # Смена компании после успешного запроса закрывает даже сохранённый повтор.
    owner = db.scalar(select(User).where(User.email == email))
    owner.company_id = db.scalar(select(User.company_id).where(User.email == 'client2@example.test'))
    db.commit()
    assert client.get(f'{BASE}/{identifier}').status_code == 404


def test_historical_snapshot_uses_saved_calculation_or_conflicts(client, db, monkeypatch):
    identifier, _, staff, detail = approved(client)
    db.execute(text('UPDATE decisions SET payment_terms=NULL'))
    db.commit()
    saved = deepcopy(db.execute(text('SELECT data FROM calculations')).scalar_one()['payment_terms'])
    from app.products import calculations
    monkeypatch.setattr(calculations, 'calculate_terms', lambda *a, **k: pytest.fail('Пересчёт исторического решения'))
    result = deal_command(client, staff, identifier, 'prepare', detail['version'])
    assert result.status_code == 200, result.text
    assert result.json()['deal']['payment_terms'] == saved


@pytest.mark.parametrize('tamper', ['missing_terms', 'wrong_revision', 'wrong_amount', 'missing_decision', 'unapproved'])
def test_unprovable_historical_conditions_fail_closed(client, db, tamper):
    identifier, _, staff, detail = approved(client)
    db.execute(text('UPDATE decisions SET payment_terms=NULL'))
    statements = {
        'missing_terms': "UPDATE calculations SET data=data-'payment_terms'",
        'wrong_revision': "UPDATE decisions SET application_version=application_version-1",
        'wrong_amount': "UPDATE calculations SET data=jsonb_set(data,'{payment_terms,amount_kopecks}','1')",
        'missing_decision': 'DELETE FROM decisions',
        'unapproved': "UPDATE applications SET status='rejected'",
    }
    db.execute(text(statements[tamper]))
    db.commit()
    response = deal_command(client, staff, identifier, 'prepare', detail['version'])
    assert response.status_code == 409, response.text
    assert db.execute(text('SELECT count(*) FROM deals')).scalar_one() == 0


def test_document_and_assistant_reflect_saved_deal(client, db):
    from app.assistant.context import application_sources_for_question, build_application_context
    from app.assistant.summary import summary_snapshot
    identifier, email, staff, detail = approved(client)
    assert client.get(f'{BASE}/{identifier}/deal/document').status_code == 404
    detail = deal_command(client, staff, identifier, 'prepare', detail['version']).json()
    key = str(uuid.uuid4())
    headers = authenticate(client, email)
    body = {'terms_confirmed': True}
    confirmed = deal_command(client, headers, identifier, 'confirm', detail['version'], key, **body)
    assert confirmed.status_code == 200, confirmed.text
    staff = authenticate(client, 'staff@example.test')
    detail = deal_command(client, staff, identifier, 'complete', confirmed.json()['version']).json()
    # Повтор потерянного ответа возвращает исходный ответ и не откатывает итог.
    headers = authenticate(client, email)
    assert deal_command(client, headers, identifier, 'confirm', confirmed.json()['version'] - 1, key, **body).json() == confirmed.json()
    document = client.get(f'{BASE}/{identifier}/deal/document')
    assert document.status_code == 200, document.text
    assert 'text/markdown' in document.headers['content-type']
    assert 'attachment;' in document.headers['content-disposition']
    assert 'no-store' in document.headers['cache-control']
    assert detail['display_number'] in document.text and detail['deal']['reference'] in document.text
    assert 'демонстрацион' in document.text.lower() and 'выдан' in document.text.lower()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))
        context = build_application_context(session, user, uuid.UUID(identifier), detail['version'])
        sources = application_sources_for_question(context, 'Оформление сделки завершено?')
        source = next(item for item in sources if item.id.endswith(':deal'))
        facts = json.loads(source.text)
        assert facts['status'] == 'completed' and facts['available_actions'] == []
        assert facts['payment_terms'] == detail['deal']['payment_terms']
        staff_user = session.scalar(select(User).where(User.email == 'staff@example.test'))
        *_, summary_facts = summary_snapshot(uuid.UUID(identifier), detail['version'], session, staff_user)
        assert any(item['id'].endswith(':deal') for item in summary_facts['sources'])


def test_historical_accepted_offer_keeps_stored_numbers(client, db):
    identifier, _, staff, detail = approved(client, code='working_capital', accept=True)
    db.execute(text('UPDATE offers SET payment_terms=NULL, annual_rate_bps=1700, total_payment_kopecks=297177863'))
    db.execute(text('UPDATE decisions SET payment_terms=NULL'))
    db.commit()
    result = deal_command(client, staff, identifier, 'prepare', detail['version'])
    assert result.status_code == 200, result.text
    deal = result.json()['deal']
    assert deal['amount_kopecks'] == 234200000 != detail['amount_kopecks']
    assert deal['payment_terms']['annual_rate_bps'] == 1700
    assert deal['payment_terms']['total_payment_kopecks'] == 297177863


@pytest.mark.parametrize('wrong_version', [False, True])
@pytest.mark.parametrize('missing_time', [False, True])
def test_historical_accepted_offer_without_response_time_requires_exact_decision_link(client, db, wrong_version, missing_time):
    identifier, _, staff, detail = approved(client, code='working_capital', accept=True)
    offer = detail['offers'][-1]
    saved = deepcopy(offer['payment_terms'])
    if missing_time:
        db.execute(text('UPDATE offers SET responded_at=NULL'))
    db.execute(text('UPDATE decisions SET payment_terms=NULL'))
    if wrong_version:
        db.execute(text('UPDATE offers SET application_version=application_version-1'))
    db.commit()
    result = deal_command(client, staff, identifier, 'prepare', detail['version'])
    if wrong_version:
        assert result.status_code == 409, result.text
    else:
        assert result.status_code == 200, result.text
        assert result.json()['deal']['payment_terms'] == saved
        assert result.json()['deal']['confirmed_at'] is None
        if missing_time:
            assert db.execute(text('SELECT responded_at FROM offers')).scalar_one() is None


def test_summary_cache_invalidates_after_each_deal_transition(client, db, fake):
    from test_assistant_summary import summary, facts
    identifier, email, staff, detail = approved(client)
    assert summary(client, staff, detail).status_code == 200
    assert len(fake.calls) == 1
    assert summary(client, staff, detail).status_code == 200 and len(fake.calls) == 1
    detail = deal_command(client, staff, identifier, 'prepare', detail['version']).json()
    assert summary(client, staff, detail).status_code == 200
    assert len(fake.calls) == 2 and facts(fake)['deal']['status'] == 'prepared'
    headers = authenticate(client, email)
    detail = deal_command(client, headers, identifier, 'confirm', detail['version'], terms_confirmed=True).json()
    staff = authenticate(client, 'staff@example.test')
    assert summary(client, staff, detail).status_code == 200
    assert len(fake.calls) == 3 and facts(fake)['deal']['status'] == 'confirmed'
    detail = deal_command(client, staff, identifier, 'complete', detail['version']).json()
    assert summary(client, staff, detail).status_code == 200
    assert len(fake.calls) == 4 and facts(fake)['deal']['status'] == 'completed'
    assert facts(fake)['deal']['next_steps'] == []


def test_document_escapes_untrusted_text_and_keeps_company_snapshot(client, db):
    from app.applications.submission_models import ApplicationRevision
    from app.companies.models import Company
    identifier, _, staff, detail = approved(client)
    revision = db.scalar(select(ApplicationRevision))
    snapshot = deepcopy(revision.snapshot)
    snapshot['company']['name'] = '# Компания [ссылка](https://example.test) <script>alert(1)</script>\n## Заголовок'
    revision.snapshot = snapshot
    db.commit()
    detail = deal_command(client, staff, identifier, 'prepare', detail['version']).json()
    company = db.get(Company, uuid.UUID(snapshot['company']['id']))
    company.name = 'Новое название после оформления'
    db.commit()
    detail = deal_command(client, staff, identifier, 'cancel', detail['version'],
                          reason='[отмена](javascript:alert(1))\n# Новый блок <img src=x>').json()
    document = client.get(f'{BASE}/{identifier}/deal/document').text
    assert 'Новое название после оформления' not in document
    assert '<script>' not in document and '<img ' not in document
    assert '\\[ссылка\\]\\(' in document and '\\[отмена\\]\\(' in document
    assert '\n## Заголовок' not in document and '\n# Новый блок' not in document


def test_cancelled_confirmed_deal_keeps_confirmation_and_reason(client, db):
    identifier, email, staff, detail = approved(client)
    detail = deal_command(client, staff, identifier, 'prepare', detail['version']).json()
    headers = authenticate(client, email)
    detail = deal_command(client, headers, identifier, 'confirm', detail['version'], terms_confirmed=True).json()
    confirmed_at = detail['deal']['confirmed_at']
    detail = deal_command(client, headers, identifier, 'cancel', detail['version'], reason='Изменились планы').json()
    assert detail['deal']['status'] == 'cancelled' and detail['deal']['confirmed_at'] == confirmed_at
    assert detail['deal']['cancel_reason'] == 'Изменились планы' and detail['deal']['completed_at'] is None
    assert 'Изменились планы' in client.get(f'{BASE}/{identifier}/deal/document').text
