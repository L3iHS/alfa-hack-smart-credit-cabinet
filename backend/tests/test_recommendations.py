from datetime import date
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy import func, select

from app.products.calculations import calculate_terms
from app.products.catalog import CATALOG_VERSION, get_product
from app.products.financial import financial_gate
from app.recommendations.config import DEFAULT_RULES_PATH, RecommendationConfigError, load_config
from app.recommendations.context import build_context
from app.recommendations.engine import recommend
from app.recommendations.schemas import RecommendationRequest
from test_auth import csrf, login

BASE = '/api/v1/product-recommendations'
COMPANY = SimpleNamespace(inn='990000000001', name='Демо', registered_at=date(2019, 3, 15))


def request(**overrides):
    values = dict(
        purpose='working_capital', amount_kopecks=200_000_000, term_months=12,
        revenue_total_kopecks=3_000_000_000, expenses_total_kopecks=2_000_000_000,
        existing_debt_payments_kopecks=10_000_000, period_months=1,
    )
    values.update(overrides)
    return RecommendationRequest(**values)


def item_for(result, code):
    return next(item for item in result.items if item.product_code == code)


def test_no_period_requests_exact_period_input_instead_of_assuming_month():
    result = recommend(request(period_months=None), COMPANY)
    assert result.status == 'request_data'
    assert result.items == []
    assert result.missing_fields == ['period_months']
    assert [(a.kind, a.field) for a in result.actions] == [('request_field', 'period_months')]


def test_three_month_totals_use_three_months_and_keep_maximum_grid_amount():
    result = recommend(request(amount_kopecks=300_000_000, revenue_total_kopecks=240_000_000,
        expenses_total_kopecks=120_000_000, existing_debt_payments_kopecks=60_000_000,
        period_months=3), COMPANY)
    item = item_for(result, 'working_capital')
    assert item.recommended_amount_kopecks == 113_800_000
    assert item.financial_gate.allowed
    assert 'financial_amount_adjusted' in item.reason_codes


@pytest.mark.parametrize('missing', ['revenue_total_kopecks', 'expenses_total_kopecks',
                                    'existing_debt_payments_kopecks'])
def test_partial_finances_request_only_missing_field(missing):
    result = recommend(request(**{missing: None}), COMPANY)
    assert result.status == 'request_data'
    assert result.items == []
    assert result.missing_fields == [missing]
    assert [(a.kind, a.field) for a in result.actions] == [('request_field', missing)]
    assert all(a.label for a in result.actions)


def test_empty_finances_request_all_exact_inputs():
    result = recommend(request(revenue_total_kopecks=None, expenses_total_kopecks=None,
        existing_debt_payments_kopecks=None, period_months=None), COMPANY)
    assert result.status == 'request_data'
    assert result.missing_fields == ['revenue_total_kopecks', 'expenses_total_kopecks',
                                    'existing_debt_payments_kopecks', 'period_months']


def test_purpose_filters_unrelated_product_requirements():
    result = recommend(request(), COMPANY)
    assert {i.product_code for i in result.items} == {'working_capital', 'credit_line', 'overdraft'}
    assert result.missing_fields == []
    assert not any(a.kind == 'request_field' for a in result.actions)
    for item in result.items:
        assert item.required_application_fields == []
        assert 'business_plan' not in item.required_document_types
        assert 'tender_document' not in item.required_document_types


def test_catalog_cap_and_financial_cap_are_both_rechecked_and_explained():
    result = recommend(request(amount_kopecks=2_000_000_000,
        revenue_total_kopecks=80_000_000, expenses_total_kopecks=40_000_000,
        existing_debt_payments_kopecks=20_000_000), COMPANY)
    item = item_for(result, 'working_capital')
    assert item.recommended_amount_kopecks == 113_800_000
    assert {'catalog_amount_adjusted', 'financial_amount_adjusted'} <= set(item.reason_codes)
    assert not financial_gate(calculate_terms(get_product('working_capital', CATALOG_VERSION),
        113_900_000, 12), 80_000_000, 40_000_000, 20_000_000).allowed


def test_original_working_capital_minimum_and_exact_kopecks_are_preserved():
    item = item_for(recommend(request(amount_kopecks=10_000_001), COMPANY), 'working_capital')
    assert item.recommended_amount_kopecks == 10_000_001
    assert item.payment_terms.upfront_fee_kopecks == 0
    assert item.payment_terms.monthly_payment_kopecks == 945_597
    assert item.payment_terms.total_cost_kopecks == 1_347_163
    assert item.reason_codes == ['purpose_match']


@pytest.mark.parametrize('purpose,code,amount,term,kind,fee', [
    ('working_capital', 'working_capital', 200_000_000, 12, 'annuity', 0),
    ('equipment', 'equipment', 200_000_000, 12, 'annuity', 0),
    ('cash_gap', 'overdraft', 200_000_000, 3, 'revolving', 0),
    ('working_capital', 'credit_line', 200_000_000, 12, 'revolving', 1_000_000),
    ('investment', 'investment', 500_000_000, 36, 'annuity', 7_500_000),
    ('tender_guarantee', 'tender_guarantee', 200_000_000, 12, 'guarantee', 6_000_000),
])
def test_all_six_use_real_codes_shared_terms_and_can_be_applied(purpose, code, amount, term, kind, fee):
    result = recommend(request(purpose=purpose, amount_kopecks=amount, term_months=term), COMPANY)
    item = item_for(result, code)
    assert item.recommended_amount_kopecks == amount
    assert item.term_months == term
    assert item.payment_terms.payment_kind == kind
    assert item.payment_terms.upfront_fee_kopecks == fee
    assert item.payment_terms == calculate_terms(get_product(code, CATALOG_VERSION), amount, term)
    assert item.financial_gate.allowed
    action = next(a for a in result.actions if a.recommendation_id == item.recommendation_id)
    assert action.kind == 'apply_recommendation'
    assert action.product_code == code
    assert action.field is None


def test_credit_line_cost_contains_fee_and_principal_due_at_end():
    terms = item_for(recommend(request(), COMPANY), 'credit_line').payment_terms
    assert terms.total_cost_kopecks == 41_000_008
    assert terms.total_payment_kopecks == 241_000_008
    assert terms.principal_due_at_end_kopecks == 200_000_000
    assert terms.assessment_monthly_burden_kopecks == 21_000_001


def test_guarantee_is_not_a_loan_and_reports_submission_requirements():
    result = recommend(request(purpose='tender_guarantee'), COMPANY)
    assert result.status == 'ok'
    item = result.items[0]
    assert item.payment_terms.annual_rate_bps is None
    assert item.payment_terms.monthly_payment_kopecks is None
    assert item.payment_terms.total_cost_kopecks == 6_000_000
    assert item.payment_terms.contingent_liability_kopecks == 200_000_000
    assert item.required_application_fields == ['tender_number', 'beneficiary_name']
    assert item.required_document_types == ['financial_statement', 'tender_document']
    assert result.missing_fields == []


def test_equipment_and_investment_do_not_require_uploads_or_collateral_before_draft():
    equipment = recommend(request(purpose='equipment'), COMPANY)
    assert equipment.status == 'ok'
    assert equipment.items[0].product_code == 'equipment'
    assert equipment.items[0].required_document_types == ['financial_statement', 'equipment_invoice']
    investment = recommend(request(purpose='investment', amount_kopecks=500_000_000, term_months=36), COMPANY)
    assert investment.status == 'ok'
    assert investment.items[0].required_application_fields == ['project_description']


def test_guarantee_finds_joint_maximum_of_fee_and_liability_caps():
    result = recommend(request(purpose='tender_guarantee', amount_kopecks=1_000_000_000,
        term_months=36, revenue_total_kopecks=30_000_000, expenses_total_kopecks=20_000_000,
        existing_debt_payments_kopecks=1_000_000), COMPANY)
    item = result.items[0]
    assert item.recommended_amount_kopecks == 100_000_000
    assert item.payment_terms.upfront_fee_kopecks == 9_000_000
    assert item.financial_gate.guarantee_fee_affordable
    assert item.financial_gate.guarantee_liability_within_limit


def test_term_adjustment_preserves_reason_and_rechecks_finances():
    result = recommend(request(purpose='cash_gap', term_months=12), COMPANY)
    assert result.status == 'adjusted'
    assert result.items[0].product_code == 'overdraft'
    assert result.items[0].term_months == 3
    assert 'term_adjusted' in result.items[0].reason_codes
    assert result.items[0].payment_terms.term_months == 3
    assert result.items[0].financial_gate.allowed


def test_amount_below_minimum_is_never_increased():
    result = recommend(request(amount_kopecks=5_000_000), COMPANY)
    assert result.status == 'no_match'
    assert result.items == []
    assert result.actions[0].kind == 'change_amount'


def test_financial_failure_below_product_minimum_has_no_match():
    result = recommend(request(purpose='investment', amount_kopecks=500_000_000,
        term_months=36, revenue_total_kopecks=100_000, expenses_total_kopecks=100_000,
        existing_debt_payments_kopecks=0), COMPANY)
    assert result.status == 'no_match'
    assert result.items == []


def test_purpose_is_ranked_before_cheaper_secondary_and_sort_is_stable():
    first = recommend(request(purpose='equipment', amount_kopecks=500_000_000, term_months=36), COMPANY)
    second = recommend(request(purpose='equipment', amount_kopecks=500_000_000, term_months=36), COMPANY)
    assert [i.product_code for i in first.items] == ['equipment', 'investment']
    assert [i.product_code for i in second.items] == ['equipment', 'investment']
    assert [i.rank for i in first.items] == [1, 2]


def test_no_fake_percent_or_approval_contract_is_exposed():
    body = recommend(request(), COMPANY).model_dump(mode='json')
    forbidden = {'approval_likelihood', 'approval_time_hours', 'effective_annual_cost_pct',
                 'approved_amount_kopecks', 'offer_id', 'score'}
    assert all(not forbidden.intersection(item) for item in body['items'])
    assert body['staff_trace'] is None
    assert body['catalog_version'] == 'demo-v2'


def test_staff_trace_contains_real_checks_without_changing_result():
    staff = recommend(request(), COMPANY, role='staff')
    assert staff.staff_trace
    assert any(row['rule_id'] == 'STOP_ACTIVE_OVERDUE' for row in staff.staff_trace)
    assert any(row.get('product_code') == 'working_capital' and row['stage'] == 'financial_gate'
               for row in staff.staff_trace)
    assert [i.product_code for i in staff.items] == [i.product_code for i in recommend(request(), COMPANY).items]


@pytest.mark.parametrize('field,value', [('liquidated', True), ('overdue_days', 90)])
def test_agreed_global_stop_factors_prevent_recommendations(field, value):
    checks = {'registry': {'registered_at': '2019-03-15', 'liquidated': False},
              'bki': {'overdue_days': 0}}
    checks['registry' if field == 'liquidated' else 'bki'][field] = value
    result = recommend(request(), COMPANY, source_checks=checks)
    assert result.status == 'no_match'
    assert result.items == []


def test_no_new_business_age_okved_address_director_or_minor_overdue_ban():
    young = SimpleNamespace(inn=COMPANY.inn, name='Новая', registered_at=date(2026, 9, 1),
        okved='64.99', mass_address_flag=True, director_disqualified_flag=True, credit_history_score=1)
    checks = {'registry': {'registered_at': '2026-09-01', 'liquidated': False},
              'bki': {'overdue_days': 89}}
    result = recommend(request(), young, source_checks=checks, as_of_date=date(2026, 10, 23))
    assert item_for(result, 'working_capital').recommended_amount_kopecks == 200_000_000


@pytest.mark.parametrize('inn,expected_overdue', [('990000000001', 0), ('990000000105', 100),
                                               ('1234567890', 0), ('123456789012', 0)])
def test_context_uses_the_same_company_sources_as_processing(inn, expected_overdue):
    from app.demo.profiles import SOURCE_VERSION
    from app.processing import providers
    company = SimpleNamespace(inn=inn, name='Компания', registered_at=date(2019, 3, 15))
    snapshot = {'company': {'inn': inn, 'registered_at': '2019-03-15'}}
    registry = providers.check('registry', snapshot, SOURCE_VERSION)
    bki = providers.check('bki', snapshot, SOURCE_VERSION)
    assert registry['liquidated'] is False
    assert bki['overdue_days'] == expected_overdue
    context = build_context(request(), company)
    assert context.get('egrul_status') == 'active'
    assert context.get('max_overdue_days') == expected_overdue
    result = recommend(request(), company)
    assert result.status == ('no_match' if expected_overdue >= 90 else 'ok')


@pytest.mark.parametrize('registry,bki', [
    ({'liquidated': None}, {'overdue_days': 0}),
    ({'liquidated': False}, {}),
    ({'liquidated': False}, {'overdue_days': -1}),
    ({'liquidated': False}, {'overdue_days': '0'}),
])
def test_unavailable_or_invalid_source_data_does_not_become_a_clean_check(registry, bki):
    result = recommend(request(), COMPANY, source_checks={'registry': registry, 'bki': bki})
    assert result.status == 'no_match'
    assert result.items == []


def test_as_of_date_is_used_for_financial_period_and_company_age():
    payload = request(period_months=None, period_start=date(2027, 1, 1), period_end=date(2027, 3, 31))
    context = build_context(payload, COMPANY, as_of_date=date(2027, 4, 15))
    assert context.get('period_months') == 3
    assert context.get('business_age_months') == 97
    assert recommend(payload, COMPANY, as_of_date=date(2027, 4, 15)).items
    with pytest.raises(ValueError, match='завершённых'):
        recommend(payload, COMPANY, as_of_date=date(2027, 3, 15))


@pytest.mark.parametrize('overrides', [
    {'amount_kopecks': 0}, {'amount_kopecks': True}, {'term_months': 0}, {'term_months': 121},
    {'revenue_total_kopecks': -1}, {'expenses_total_kopecks': '1'},
    {'existing_debt_payments_kopecks': False}, {'period_months': 0}, {'period_months': 1.5},
    {'period_start': date(2026, 1, 1)},
    {'period_start': date(2026, 1, 1), 'period_end': date(2026, 3, 31)},
])
def test_invalid_types_values_and_contradictory_periods_are_rejected(overrides):
    with pytest.raises(ValueError):
        request(**overrides)


@pytest.mark.parametrize('start,end', [('2026-01-02', '2026-03-31'), ('2026-03-01', '2026-02-28'),
                                      ('2026-01-01', '2026-03-30'), ('2099-01-01', '2099-01-31')])
def test_api_invalid_calendar_period_returns_422_even_with_partial_finances(client, start, end):
    token = login(client).json()['csrf_token']
    payload = request(period_months=None, period_start=start, period_end=end).model_dump(mode='json')
    payload['revenue_total_kopecks'] = None
    assert client.post(BASE, json=payload, headers={'X-CSRF-Token': token}).status_code == 422


def test_options_and_client_endpoint_and_no_database_mutations(client, db):
    from app.applications.models import Application
    from app.applications.submission_models import ApplicationRevision
    from app.processing.models import Decision, Offer
    models = (Application, ApplicationRevision, Decision, Offer)
    before = [db.scalar(select(func.count()).select_from(model)) for model in models]
    token = login(client).json()['csrf_token']
    options = client.get(f'{BASE}/options')
    assert options.status_code == 200
    assert len(options.json()['purposes']) == 6
    assert set(options.json()) == {'purposes', 'config_version'}
    response = client.post(BASE, json=request().model_dump(mode='json'), headers={'X-CSRF-Token': token})
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['product_code'] == 'working_capital'
    assert response.json()['staff_trace'] is None
    assert [db.scalar(select(func.count()).select_from(model)) for model in models] == before


def test_client_cannot_select_another_company_or_staff_trace(client, db):
    from app.companies.models import Company
    token = login(client).json()['csrf_token']
    other = db.scalar(select(Company).where(Company.inn == '990000000105'))
    response = client.post(f'{BASE}?company_id={other.id}', json=request().model_dump(mode='json'),
                           headers={'X-CSRF-Token': token})
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'
    assert response.json()['items']
    assert response.json()['staff_trace'] is None


def test_staff_requires_explicit_company_and_gets_its_checks(client, db):
    from app.companies.models import Company
    token = login(client, 'staff@example.test').json()['csrf_token']
    headers = {'X-CSRF-Token': token}
    assert client.post(BASE, json=request().model_dump(mode='json'), headers=headers).status_code == 422
    company = db.scalar(select(Company).where(Company.inn == '990000000105'))
    response = client.post(f'{BASE}?company_id={company.id}', json=request().model_dump(mode='json'), headers=headers)
    assert response.status_code == 200
    assert response.json()['status'] == 'no_match'
    assert response.json()['staff_trace']


def test_recommendations_require_session_and_csrf(client):
    response = client.post(BASE, json=request().model_dump(mode='json'), headers={'X-CSRF-Token': csrf(client)})
    assert response.status_code == 401
    login(client)
    assert client.post(BASE, json=request().model_dump(mode='json')).status_code == 403


@pytest.mark.parametrize('extra', [{'company_id': 'fake'}, {'role': 'staff'}, {'profile': {}},
                                  {'supplier_invoice_attached': True}, {'urgency': 'high'}])
def test_api_rejects_forged_context_and_obsolete_unexecutable_inputs(client, extra):
    token = login(client).json()['csrf_token']
    response = client.post(BASE, json={**request().model_dump(mode='json'), **extra},
                           headers={'X-CSRF-Token': token})
    assert response.status_code == 422


@pytest.mark.parametrize('file,change', [
    ('products.yaml', lambda raw: raw.update(products=['unknown'])),
    ('products.yaml', lambda raw: raw['products'].append(raw['products'][0])),
    ('purpose_map.yaml', lambda raw: raw['purposes']['equipment'].update(primary=['unknown'])),
    ('ranking.yaml', lambda raw: raw.update(show_top_n=0)),
    ('ranking.yaml', lambda raw: raw.update(approval_likelihood=0.2)),
    ('stop_factors.yaml', lambda raw: raw.update(excluded_okved_prefixes=['64.99'])),
    ('stop_factors.yaml', lambda raw: raw['global_stop_factors'][0].update(reason_code='unknown')),
])
def test_configuration_rejects_bad_references_and_unexecutable_fields(tmp_path, file, change):
    for source in DEFAULT_RULES_PATH.glob('*.yaml'):
        (tmp_path / source.name).write_bytes(source.read_bytes())
    target = tmp_path / file
    raw = yaml.safe_load(target.read_text())
    change(raw)
    target.write_text(yaml.safe_dump(raw, allow_unicode=True))
    with pytest.raises(RecommendationConfigError):
        load_config(str(tmp_path))
