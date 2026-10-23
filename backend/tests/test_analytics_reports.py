"""Контролируемые когорты: неверная база или время должны менять ожидаемые числа."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.analytics.models import AnalyticsEvent, AnalyticsJourney
from app.applications.models import Application
from app.applications.submission_models import ApplicationRevision
from app.auth.models import User
from app.processing.models import Offer
from test_application_drafts import authenticate

BASE = '/api/v1/analytics'
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
START = datetime(2026, 10, 1, 21, tzinfo=timezone.utc)  # 02.10, 00:00 Москва
PARAMS = {'date_from': '2026-10-02', 'date_to': '2026-10-02'}
PRODUCTS = ['working_capital', 'equipment', 'overdraft', 'credit_line', 'investment', 'tender_guarantee']


def actor(db):
    return db.scalar(select(User).where(User.email == 'client1@example.test'))


def application(db, product='working_capital', status='draft'):
    user = actor(db)
    row = Application(id=uuid.uuid4(), company_id=user.company_id, author_id=user.id,
                      catalog_version='demo-v1', product_code=product, status=status,
                      amount_kopecks=999_999_900, term_months=48, created_at=START)
    db.add(row)
    db.flush()
    return row


def revision(db, row, version=2):
    rev = ApplicationRevision(id=uuid.uuid4(), application_id=row.id, application_version=version,
                              submitted_by=row.author_id, created_at=START + timedelta(days=10),
                              snapshot={'application': {'product_code': row.product_code,
                                        'amount_kopecks': 100_000_000, 'term_months': 12}})
    db.add(rev)
    db.flush()
    return rev


def journey(db, linked=None, at=START, product='working_capital', steps=()):
    row = AnalyticsJourney(id=uuid.uuid4(), user_id=actor(db).id, product_code=product,
                           application_id=linked.id if linked else None, created_at=at)
    db.add(row)
    db.flush()
    for index, step in enumerate(steps):
        db.add(AnalyticsEvent(user_id=row.user_id, event_id=uuid.uuid4(), kind='form_step_viewed',
                              journey_id=row.id, payload={'step': step}, created_at=at + timedelta(seconds=index)))
    return row


def offer(db, *, product='working_capital', status='active', viewed=None, responded=None,
          at=START, amount=80_000_000, term=12, reason=None, identifier=None, legacy=False):
    row = application(db, product, 'counteroffer')
    rev = revision(db, row)
    kind = 'guarantee' if product == 'tender_guarantee' else 'revolving' if product in ('overdraft', 'credit_line') else 'annuity'
    monthly = None if kind == 'guarantee' else 1_000_000
    terms = {'payment_kind': kind, 'amount_kopecks': amount, 'term_months': term,
             'annual_rate_bps': None if kind == 'guarantee' else 1800, 'annual_commission_bps': 200,
             'monthly_payment_kopecks': monthly, 'upfront_fee_kopecks': 100,
             'principal_due_at_end_kopecks': amount if kind == 'revolving' else 0,
             'last_payment_kopecks': 0 if kind == 'guarantee' else 1_000_000,
             'total_payment_kopecks': 100 if kind == 'guarantee' else 120_000_000,
             'total_cost_kopecks': 100 if kind == 'guarantee' else 40_000_000,
             'assessment_monthly_burden_kopecks': monthly,
             'contingent_liability_kopecks': amount if kind == 'guarantee' else 0, 'assumptions': []}
    item = Offer(id=identifier or uuid.uuid4(), application_id=row.id, revision_id=rev.id,
                 application_version=2, status=status, product_code=product, amount_kopecks=amount,
                 term_months=term, monthly_payment_kopecks=monthly or 0, total_payment_kopecks=terms['total_payment_kopecks'],
                 annual_rate_bps=1800, payment_terms=None if legacy else terms, reason='Условия',
                 created_at=at, responded_at=responded, decline_reason=reason)
    db.add(item)
    db.flush()
    for timestamp in (viewed if isinstance(viewed, list) else [viewed]):
        if timestamp is not None:
            db.add(AnalyticsEvent(user_id=row.author_id, event_id=uuid.uuid4(), kind='offer_viewed',
                                  offer_id=item.id, offer_version=1, payload={}, created_at=timestamp))
    return item


@pytest.fixture
def frozen(monkeypatch):
    # Только часы фиксированы; маршруты, SQL, роли и сериализация остаются настоящими.
    import app.analytics.router as router
    monkeypatch.setattr(router, 'report_now', lambda: NOW, raising=False)


def report(client, path='summary', **params):
    response = client.get(f'{BASE}/{path}', params={**PARAMS, **params})
    assert response.status_code == 200, response.text
    return response.json()


def counts(rows, key='key'):
    return {row[key]: row['count'] for row in rows}


def test_empty_report_has_null_shares_and_typed_openapi(client, frozen):
    authenticate(client, 'staff@example.test')
    data = report(client)
    assert [row['count'] for row in data['form_funnel']] == [0, 0, 0]
    assert [row['count'] for row in data['offer_funnel']] == [0, 0, 0, 0]
    assert all(row['share_from_first'] is None and row['share_from_previous'] is None
               for row in data['form_funnel'] + data['offer_funnel'])
    assert data['metadata'] == {'date_from': '2026-10-02', 'date_to': '2026-10-02',
                                'timezone': 'Europe/Moscow', 'generated_at': '2026-10-24T12:00:00Z',
                                'product_code': None, 'no_response_hours': 72,
                                'outcomes_as_of': '2026-10-24T12:00:00Z'}
    page = report(client, 'counteroffers')
    assert page['items'] == [] and page['total'] == 0 and page['page'] == 1 and page['page_size'] == 20
    schemas = client.get('/api/v1/openapi.json').json()['components']['schemas']
    assert schemas['AnalyticsSummary']['properties']['offer_funnel']['items']['$ref'].endswith('/FunnelStage')
    assert schemas['CounterofferPage']['properties']['items']['items']['$ref'].endswith('/CounterofferRow')


def test_form_distinct_revisions_latest_step_and_current_linked_product(client, db, frozen):
    sent = application(db, 'equipment', 'approved')
    revision(db, sent)
    revision(db, sent, 3)
    journey(db, sent, product='working_capital', steps=('terms', 'review'))
    draft = application(db, 'equipment')
    journey(db, draft, steps=('terms', 'documents', 'finances'))
    journey(db, product='equipment', steps=('terms', 'review'))
    journey(db, product='equipment')
    # История без открытия формы не входит; границы московских суток точные.
    revision(db, application(db, 'equipment', 'approved'))
    journey(db, product='equipment', at=START - timedelta(microseconds=1))
    journey(db, product='equipment', at=START + timedelta(days=1))
    db.commit()
    authenticate(client, 'staff@example.test')
    data = report(client, product_code='equipment')
    assert counts(data['form_funnel']) == {'opened': 4, 'draft_saved': 2, 'submitted': 1}
    stage = data['form_funnel'][2]
    assert (stage['base_from_first'], stage['base_from_previous'], stage['share_from_first'], stage['share_from_previous']) == (4, 2, .25, .5)
    assert counts(data['last_steps'], 'step') == {'terms': 0, 'finances': 1, 'documents': 0, 'review': 1, 'not_observed': 1}
    assert report(client, product_code='working_capital')['form_funnel'][0]['count'] == 0


def test_offer_nested_funnel_and_all_outcomes_have_distinct_bases(client, db, frozen):
    old = NOW - timedelta(hours=72)
    offer(db, status='accepted', viewed=[old, NOW], responded=old + timedelta(seconds=1))
    offer(db, status='declined', viewed=old, responded=NOW, reason='high_payment', term=18)
    offer(db, status='accepted', responded=NOW, amount=100_000_000)
    offer(db, status='declined', viewed=NOW, responded=old, reason=None, amount=100_000_000, term=18)
    offer(db, status='accepted', viewed=old, responded=None)
    offer(db, viewed=old)  # Ровно 72 часа: без ответа.
    offer(db, viewed=old + timedelta(microseconds=1))
    offer(db)
    offer(db, status='superseded', viewed=old - timedelta(days=1))
    # Созданное вне когорты не входит даже с просмотром в выбранные сутки.
    offer(db, at=START - timedelta(microseconds=1), viewed=START)
    db.commit()
    authenticate(client, 'staff@example.test')
    data = report(client)
    assert counts(data['offer_funnel']) == {'issued': 9, 'viewed': 7, 'responded': 2, 'accepted': 1}
    assert counts(data['offer_outcomes'], 'outcome') == {'accepted': 3, 'declined': 2, 'superseded': 1,
                                                       'no_response': 1, 'awaiting_response': 1, 'not_viewed': 1}
    assert data['response_coverage'] == {'responses_without_prior_view': 3, 'response_without_registered_view': 1,
                                        'response_viewed_after_response': 1, 'response_time_unknown': 1}
    assert data['declined_after_view']['count'] == 1
    assert (data['declined_after_view']['base'], data['declined_after_view']['share']) == (7, 1 / 7)
    reasons = {row['reason']: row for row in data['decline_reasons']}
    assert reasons['high_payment']['count'] == 1 and reasons[None]['count'] == 1
    assert all(row['base'] == 2 for row in reasons.values())
    groups = {row['change']: row for row in data['condition_changes']}
    assert (groups['amount_only']['count'], groups['amount_only']['accepted']) == (6, 2)
    assert (groups['unchanged']['count'], groups['unchanged']['accepted']) == (1, 1)
    assert groups['amount_and_term']['count'] == 1 and groups['term_only']['count'] == 1
    assert groups['amount_only']['acceptance_share'] == 2 / 6
    assert data['offer_funnel'][3]['share_from_first'] == 1 / 9


@pytest.mark.parametrize('product', PRODUCTS)
def test_counteroffer_history_and_payment_kind(client, db, frozen, product):
    item = offer(db, product=product, status='declined', responded=NOW, reason='unsuitable_term', term=18,
                 legacy=product == 'working_capital')
    db.commit()
    authenticate(client, 'staff@example.test')
    page = report(client, 'counteroffers', product_code=product, outcome='declined')
    assert page['total'] == 1
    row = page['items'][0]
    assert row['id'] == str(item.id) and row['application_id'] == str(item.application_id)
    assert row['company_name']
    assert row['product_code'] == product
    assert row['original_amount_kopecks'] == 100_000_000 and row['original_term_months'] == 12
    assert row['original_monthly_payment_kopecks'] is None
    assert row['amount_delta_kopecks'] == -20_000_000 and row['amount_delta_rubles'] == '-200000.00'
    assert row['amount_delta_percent'] == -20 and row['term_delta_months'] == 6
    assert row['payment_terms']['payment_kind'] == ('guarantee' if product == 'tender_guarantee' else 'revolving' if product in ('overdraft', 'credit_line') else 'annuity')
    assert row['payment_terms']['monthly_payment_kopecks'] is None if product == 'tender_guarantee' else row['payment_terms']['monthly_payment_kopecks'] == 1_000_000
    assert row['responded_at'] == '2026-10-24T12:00:00Z' and row['first_viewed_at'] is None
    assert row['outcome'] == 'declined' and row['decline_reason'] == 'unsuitable_term'
    assert report(client, product_code=product)['offer_funnel'][0]['count'] == 1
    other = PRODUCTS[(PRODUCTS.index(product) + 1) % 6]
    assert report(client, 'counteroffers', product_code=other)['total'] == 0


def test_stable_pagination_outcome_filter_and_first_view_outside_period(client, db, frozen):
    for index in range(1, 5):
        offer(db, identifier=uuid.UUID(int=index), viewed=NOW - timedelta(hours=73) if index % 2 else None)
    offer(db, at=START + timedelta(days=1))
    db.commit()
    authenticate(client, 'staff@example.test')
    first = report(client, 'counteroffers', page_size=2)
    second = report(client, 'counteroffers', page_size=2, page=2)
    assert [row['id'] for row in first['items'] + second['items']] == [str(uuid.UUID(int=i)) for i in [4, 3, 2, 1]]
    assert first['total'] == second['total'] == 4
    assert report(client, 'counteroffers', page=3, page_size=2)['items'] == []
    assert report(client, 'counteroffers', outcome='no_response')['total'] == 2
    assert report(client, 'counteroffers', outcome='not_viewed')['total'] == 2
    assert report(client, 'counteroffers', outcome='superseded')['total'] == 0


@pytest.mark.parametrize('path', ['summary', 'counteroffers'])
def test_staff_only_report(client, path):
    assert client.get(f'{BASE}/{path}').status_code == 401
    authenticate(client)
    assert client.get(f'{BASE}/{path}').status_code == 403


@pytest.mark.parametrize('params', [
    {'date_from': 'bad'}, {'date_to': '2026-02-30'}, {'date_from': '2026-10-03', 'date_to': '2026-10-02'},
    {'date_from': '2025-01-01', 'date_to': '2026-01-02'}, {'product_code': 'unknown'},
])
@pytest.mark.parametrize('path', ['summary', 'counteroffers'])
def test_filter_validation(client, path, params):
    authenticate(client, 'staff@example.test')
    assert client.get(f'{BASE}/{path}', params={**PARAMS, **params}).status_code == 422


@pytest.mark.parametrize('params', [{'page': 0}, {'page_size': 101}, {'page_size': 0}, {'page': 'abc'}, {'outcome': 'lost'}])
def test_page_validation(client, params):
    authenticate(client, 'staff@example.test')
    assert client.get(f'{BASE}/counteroffers', params=params).status_code == 422


def test_default_and_maximum_periods(client, frozen):
    authenticate(client, 'staff@example.test')
    data = client.get(f'{BASE}/summary').json()
    assert data['metadata']['date_from'] == '2026-09-25' and data['metadata']['date_to'] == '2026-10-24'
    assert client.get(f'{BASE}/summary', params={'date_from': '2025-10-24', 'date_to': '2026-10-24'}).status_code == 200
    assert client.get(f'{BASE}/summary', params={'date_from': '2025-10-23', 'date_to': '2026-10-24'}).status_code == 422


def test_large_historical_amount_is_not_truncated_to_int32(client, db, frozen):
    item = offer(db, amount=3_000_000_000)
    rev = db.get(ApplicationRevision, item.revision_id)
    rev.snapshot = {'application': {'product_code': 'working_capital', 'amount_kopecks': 4_000_000_000, 'term_months': 12}}
    db.commit()
    authenticate(client, 'staff@example.test')
    row = report(client, 'counteroffers')['items'][0]
    assert row['original_amount_kopecks'] == 4_000_000_000
    assert row['amount_delta_kopecks'] == -1_000_000_000
    assert row['amount_delta_rubles'] == '-10000000.00' and row['amount_delta_percent'] == -25
    assert counts(report(client)['offer_funnel']) == {'issued': 1, 'viewed': 0, 'responded': 0, 'accepted': 0}


def test_response_uncertainty_categories_are_disjoint(client, db, frozen):
    offer(db, status='accepted')  # Нет времени и просмотра: только неизвестное время.
    offer(db, status='declined', viewed=NOW, responded=NOW - timedelta(seconds=1))
    offer(db, status='declined', responded=NOW)
    # Граница «до ответа» включает одновременную серверную отметку.
    offer(db, status='accepted', viewed=NOW, responded=NOW)
    db.commit()
    authenticate(client, 'staff@example.test')
    data = report(client)
    assert data['response_coverage'] == {'responses_without_prior_view': 3,
        'response_without_registered_view': 1, 'response_viewed_after_response': 1, 'response_time_unknown': 1}
    assert counts(data['offer_funnel']) == {'issued': 4, 'viewed': 2, 'responded': 1, 'accepted': 1}
    assert counts(data['offer_outcomes'], 'outcome')['accepted'] == 2


def test_report_reads_are_batched_and_do_not_change_credit_data(client, db, frozen):
    from sqlalchemy import event
    from app.core.db import engine
    for _ in range(8):
        offer(db, viewed=NOW)
    db.commit()
    authenticate(client, 'staff@example.test')
    before = [(row.id, row.status, row.version, row.responded_at) for row in db.scalars(select(Offer))]
    queries = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('SELECT', 'WITH')):
            queries.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        assert report(client, 'counteroffers', page_size=3)['total'] == 8
        assert len(queries) <= 4  # Два запроса авторизации, count и одна ограниченная страница.
        queries.clear()
        assert report(client)['offer_funnel'][0]['count'] == 8
        assert len(queries) <= 8  # Два запроса авторизации и шесть агрегатов.
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    db.expire_all()
    assert [(row.id, row.status, row.version, row.responded_at) for row in db.scalars(select(Offer))] == before


@pytest.mark.parametrize('path', ['summary', 'counteroffers'])
@pytest.mark.parametrize('params,expected', [
    ({'date_to': '0001-01-01'}, 422),
    ({'date_from': '0001-01-01', 'date_to': '0001-01-01'}, 422),
    ({'date_to': '0001-01-30'}, 422),
    ({'date_from': '0001-01-02', 'date_to': '0001-01-02'}, 200),
    ({'date_to': '0001-01-31'}, 200),
    ({'date_to': '9999-12-31'}, 200),
    ({'date_from': '9999-12-31', 'date_to': '9999-12-31'}, 200),
    (PARAMS, 200),
])
def test_extreme_iso_dates_handle_arithmetic_and_timezone_overflow(client, frozen, path, params, expected):
    authenticate(client, 'staff@example.test')
    response = client.get(f'{BASE}/{path}', params=params)
    assert response.status_code == expected, response.text
