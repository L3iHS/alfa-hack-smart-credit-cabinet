import copy

import pytest
from sqlalchemy import func, select, text

from app.auth.models import AuthSession
from app.core.db import SessionLocal
from app.main import app
from test_auth import csrf, login


TEXT = 'Нужно 500 тысяч на закупку сырья на 12 месяцев'
RESULT = {
    'suggested_fields': {'product_code': 'working_capital', 'amount_kopecks': 50_000_000,
                         'term_months': 12, 'purpose': 'закупку сырья'},
    'evidence': {'product_code': 'закупку сырья', 'amount_kopecks': '500 тысяч',
                 'term_months': 'на 12 месяцев', 'purpose': 'закупку сырья'},
    'questions': [], 'unsupported_need': False,
}


def post(client, text=TEXT, **extra):
    token = login(client).json()['csrf_token']
    return client.post('/api/v1/assistant/intake', json={'text': text, **extra},
                       headers={'X-CSRF-Token': token})


def test_disabled_intake_is_explicitly_unavailable(client):
    response = post(client)
    assert response.status_code == 503
    assert response.json()['code'] == 'assistant_unavailable'


@pytest.fixture
def fake():
    from app.assistant.provider import get_provider

    class Provider:
        model = 'test-model'
        result = copy.deepcopy(RESULT)
        calls = []

        def generate_json(self, *, system, user, schema):
            self.calls.append((system, user, schema))
            # Тестовый провайдер возвращает фиксированный nullable-контракт генерации.
            fields = dict.fromkeys(('product_code', 'amount_kopecks', 'term_months', 'purpose'))
            return {**self.result,
                    'suggested_fields': {**fields, **self.result['suggested_fields']},
                    'evidence': {**fields, **self.result['evidence']}}

    provider = Provider()
    app.dependency_overrides[get_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_provider, None)


def test_session_csrf_and_client_role_precede_generation(client, fake):
    assert client.post('/api/v1/assistant/intake', json={'text': TEXT}).status_code == 403
    assert client.post('/api/v1/assistant/intake', json={'text': TEXT},
                       headers={'X-CSRF-Token': csrf(client)}).status_code == 401
    token = login(client, 'staff@example.test').json()['csrf_token']
    assert client.post('/api/v1/assistant/intake', json={'text': TEXT},
                       headers={'X-CSRF-Token': token}).status_code == 403
    assert fake.calls == []


def test_intake_releases_auth_lock_and_does_not_write_business_rows(client, db, fake):
    from app.applications.models import Application, ApplicationEvent
    from app.applications.submission_models import ApplicationRevision, ProcessingRun
    from app.documents.models import Document

    models = [Application, ApplicationEvent, ApplicationRevision, ProcessingRun, Document]
    before = [db.scalar(select(func.count()).select_from(model)) for model in models]
    original = fake.generate_json

    def generate_json(**kwargs):
        with SessionLocal() as other:
            other.execute(text("SET LOCAL lock_timeout = '200ms'"))
            list(other.scalars(select(AuthSession).with_for_update(nowait=True)))
        return original(**kwargs)

    fake.generate_json = generate_json
    response = post(client)
    assert response.status_code == 200
    assert response.json() == {**RESULT, 'model': 'test-model', 'catalog_version': 'demo-v2'}
    assert [db.scalar(select(func.count()).select_from(model)) for model in models] == before


@pytest.mark.parametrize('amount,quote,kopecks', [
    ('2 млн', '2 млн', 200_000_000), ('1,5 млн рублей', '1,5 млн рублей', 150_000_000),
    ('500 тыс.', '500 тыс.', 50_000_000), ('500 000 рублей', '500 000 рублей', 50_000_000),
])
def test_russian_amounts_have_independent_unit_validation(client, fake, amount, quote, kopecks):
    fake.result['suggested_fields']['amount_kopecks'] = kopecks
    fake.result['evidence']['amount_kopecks'] = quote
    response = post(client, TEXT.replace('500 тысяч', amount))
    assert response.status_code == 200
    assert response.json()['suggested_fields']['amount_kopecks'] == kopecks


@pytest.mark.parametrize('text,quote,term,want', [
    ('Купить две печи за 2 млн, окупить за полтора года', 'окупить за полтора года', 18, None),
    ('Купить оборудование за 2 млн, окупаемость 12 месяцев', '12 месяцев', 12, None),
    ('Купить оборудование за 2 млн, кредит на 2 года', 'кредит на 2 года', 24, 24),
    ('Купить оборудование за 2 млн, срок кредита 18 месяцев, окупаемость 12 месяцев', '18 месяцев', 18, 18),
])
def test_payback_is_not_a_loan_term(client, fake, text, quote, term, want):
    fake.result = {'suggested_fields': {'product_code': 'equipment', 'amount_kopecks': 200_000_000,
                                       'term_months': term, 'purpose': None},
                   'evidence': {'product_code': 'оборудование' if 'оборудование' in text else 'печи',
                                'amount_kopecks': '2 млн', 'term_months': quote},
                   'questions': [], 'unsupported_need': False}
    response = post(client, text)
    assert response.status_code == 200
    assert response.json()['suggested_fields']['term_months'] == want
    if want is None:
        assert 'term_months' not in response.json()['evidence']
        assert response.json()['questions']


@pytest.mark.parametrize('field,value,quote', [
    ('amount_kopecks', 1, '500 тысяч'), ('amount_kopecks', 60_000_000, '500 тысяч'),
    ('term_months', 36, 'на 12 месяцев'), ('product_code', 'mortgage', 'закупку сырья'),
    ('purpose', 'Несуществующая цель', 'выдуманная цитата'),
])
def test_unfounded_or_unknown_fields_are_not_suggested(client, fake, field, value, quote):
    fake.result['suggested_fields'][field] = value
    fake.result['evidence'][field] = quote
    response = post(client)
    assert response.status_code == 200
    assert response.json()['suggested_fields'][field] is None
    assert field not in response.json()['evidence']
    assert response.json()['questions']


def test_product_ranges_are_not_silently_adjusted(client, fake):
    fake.result['suggested_fields']['term_months'] = 36
    fake.result['evidence']['term_months'] = '36 месяцев'
    response = post(client, TEXT.replace('12 месяцев', '36 месяцев'))
    assert response.status_code == 200
    assert response.json()['suggested_fields']['term_months'] is None
    assert response.json()['questions']


def test_unsupported_need_has_no_values_for_application(client, fake):
    fake.result['unsupported_need'] = True
    response = post(client)
    assert response.status_code == 200
    assert all(value is None for value in response.json()['suggested_fields'].values())
    assert response.json()['evidence'] == {}


@pytest.mark.parametrize('extra', [{'catalog_version': 'unknown'}, {'text': '  '}, {'text': 'x' * 6001}, {'url': 'https://evil.test'}])
def test_invalid_inputs_never_call_model(client, fake, extra):
    token = login(client).json()['csrf_token']
    response = client.post('/api/v1/assistant/intake', json={'text': TEXT, **extra},
                           headers={'X-CSRF-Token': token})
    assert response.status_code == 422
    assert not fake.calls


@pytest.mark.parametrize('field,value', [('amount_kopecks', True), ('term_months', '12'), ('amount_kopecks', 9_007_199_254_740_992)])
def test_wrong_model_types_are_unavailable(client, fake, field, value):
    fake.result['suggested_fields'][field] = value
    response = post(client)
    assert response.status_code == 503
    assert response.json()['code'] == 'assistant_unavailable'


@pytest.mark.parametrize('amount,quote', [('-500 тысяч', '500 тысяч'), ('- 500 тысяч', '500 тысяч'), ('1500 тысяч', '500 тысяч')])
def test_amount_citation_cannot_hide_sign_or_leading_digits(client, fake, amount, quote):
    fake.result['evidence']['amount_kopecks'] = quote
    response = post(client, TEXT.replace('500 тысяч', amount))
    assert response.status_code == 200
    assert response.json()['suggested_fields']['amount_kopecks'] is None


@pytest.mark.parametrize('code,phrase,amount,term', [
    ('working_capital', 'сырьё', 50_000_000, 12),
    ('equipment', 'оборудование', 50_000_000, 12),
    ('overdraft', 'кассовый разрыв', 50_000_000, 2),
    ('credit_line', 'кредитная линия', 50_000_000, 12),
    ('investment', 'развитие бизнеса', 300_000_000, 24),
    ('tender_guarantee', 'гарантия тендера', 50_000_000, 12),
])
def test_all_six_catalog_products_are_available(client, fake, code, phrase, amount, term):
    rubles = amount // 100
    fake.result = {'suggested_fields': {'product_code': code, 'amount_kopecks': amount,
                                       'term_months': term, 'purpose': phrase},
                   'evidence': {'product_code': phrase, 'amount_kopecks': f'{rubles} рублей',
                                'term_months': f'кредит на {term} месяцев', 'purpose': phrase},
                   'questions': [], 'unsupported_need': False}
    response = post(client, f'{phrase}, {rubles} рублей, кредит на {term} месяцев')
    assert response.status_code == 200
    assert response.json()['suggested_fields'] == fake.result['suggested_fields']


def test_model_cannot_add_financial_fields(client, fake):
    fake.result['suggested_fields']['revenue_kopecks'] = 99_000_000
    response = post(client)
    assert response.status_code == 503
    assert response.json()['code'] == 'assistant_unavailable'


def test_empty_result_asks_for_missing_information(client, fake):
    fake.result = {'suggested_fields': {}, 'evidence': {}, 'questions': [], 'unsupported_need': False}
    response = post(client)
    assert response.status_code == 200
    assert all(value is None for value in response.json()['suggested_fields'].values())
    assert len(response.json()['questions']) == 4


def test_historical_catalog_does_not_accept_new_product(client, fake):
    fake.result['suggested_fields']['product_code'] = 'overdraft'
    response = post(client, catalog_version='demo-v1')
    assert response.status_code == 200
    assert response.json()['suggested_fields']['product_code'] is None
    assert response.json()['catalog_version'] == 'demo-v1'


@pytest.mark.parametrize('duration,quote', [('112 месяцев', '12 месяцев'), ('-12 месяцев', '12 месяцев')])
def test_term_citation_cannot_hide_sign_or_leading_digits(client, fake, duration, quote):
    fake.result['evidence']['term_months'] = quote
    response = post(client, 'Нужен кредит. Кредит ' + TEXT.replace('12 месяцев', duration))
    assert response.status_code == 200
    assert response.json()['suggested_fields']['term_months'] is None


@pytest.mark.parametrize('text,term,quote', [
    ('Нужен кредит на оборудование, 12 месяцев — срок окупаемости', 12, '12 месяцев'),
    ('Нужен кредит на оборудование, 12 месяцев окупаемости проекта', 12, '12 месяцев'),
    ('Нужен кредит на оборудование, бизнес работает 5 лет', 60, '5 лет'),
    ('Нужен кредит на оборудование бизнес работает 5 лет', 60, '5 лет'),
    ('Нужен кредит на оборудование, компании 5 лет', 60, '5 лет'),
    ('Нужен кредит на оборудование, срок службы оборудования 3 года', 36, '3 года'),
    ('Кредит на оборудование на 12 месяцев — срок окупаемости', 12, '12 месяцев'),
])
def test_duration_requires_a_local_loan_reference(client, fake, text, term, quote):
    fake.result = {'suggested_fields': {'product_code': 'investment' if term > 36 else 'equipment', 'amount_kopecks': None,
                                       'term_months': term, 'purpose': None},
                   'evidence': {'product_code': 'оборудование', 'term_months': quote},
                   'questions': [], 'unsupported_need': False}
    response = post(client, text)
    assert response.status_code == 200
    assert response.json()['suggested_fields']['term_months'] is None
    assert 'term_months' not in response.json()['evidence']
    assert any('срок' in question.lower() for question in response.json()['questions'])


@pytest.mark.parametrize('text', [
    'Нужен кредит на оборудование на 24 месяца',
    'Оборудование, 24 месяца — срок кредита',
    'Оборудование, срок кредита 24 месяца; бизнес работает 5 лет',
])
def test_loan_duration_can_be_bound_on_either_side(client, fake, text):
    fake.result = {'suggested_fields': {'product_code': 'equipment', 'amount_kopecks': None,
                                       'term_months': 24, 'purpose': None},
                   'evidence': {'product_code': 'оборудование' if 'оборудование' in text else 'Оборудование',
                                'term_months': '24 месяца'},
                   'questions': [], 'unsupported_need': False}
    response = post(client, text)
    assert response.status_code == 200
    assert response.json()['suggested_fields']['term_months'] == 24
    assert response.json()['evidence']['term_months'] == '24 месяца'


def test_nullable_wire_evidence_does_not_change_public_output(client, fake):
    fake.result['suggested_fields']['purpose'] = None
    fake.result['evidence']['purpose'] = None
    response = post(client)
    assert response.status_code == 200
    assert response.json()['suggested_fields']['purpose'] is None
    assert 'purpose' not in response.json()['evidence']


@pytest.mark.parametrize('text', [
    'Нужен кредит на оборудование на 24 месяца и окупить за 3 года',
    'Для работающего бизнеса нужен кредит на 24 месяца',
    'Кредит для работающего бизнеса нужен на 24 месяца',
    'Окупаемость 3 года и нужен кредит на 24 месяца',
])
def test_explicit_loan_term_survives_a_separate_business_duration(client, fake, text):
    fake.result = {'suggested_fields': {'product_code': None, 'amount_kopecks': None,
                                       'term_months': 24, 'purpose': None},
                   'evidence': {'term_months': '24 месяца'}, 'questions': [], 'unsupported_need': False}
    response = post(client, text)
    assert response.status_code == 200
    assert response.json()['suggested_fields']['term_months'] == 24
    assert response.json()['evidence']['term_months'] == '24 месяца'


def test_conjunction_does_not_hide_payback_qualifying_the_same_duration(client, fake):
    fake.result = {'suggested_fields': {'product_code': None, 'amount_kopecks': None,
                                       'term_months': 24, 'purpose': None},
                   'evidence': {'term_months': '24 месяца'}, 'questions': [], 'unsupported_need': False}
    response = post(client, 'Кредит на оборудование на 24 месяца и это срок окупаемости')
    assert response.status_code == 200
    assert response.json()['suggested_fields']['term_months'] is None
    assert 'term_months' not in response.json()['evidence']
