from datetime import date
from types import SimpleNamespace

import pytest

from app.demo.profiles import recommendation_profile
from app.recommendations.config import load_config
from app.recommendations.engine import recommend
from app.recommendations.schemas import RecommendationRequest
from test_auth import login

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


def test_config_contains_all_products_and_cabinet_mapping():
    config = load_config()
    assert config.version == 'rules-2026.10.1'
    assert len(config.products) == 6
    assert config.purpose('working_capital').primary == ('working_capital_loan', 'credit_line_smb')
    assert {item.id: item.cabinet_product_code for item in config.products} == {
        'overdraft_smb': None,
        'working_capital_loan': 'working_capital',
        'credit_line_smb': None,
        'equipment_loan': 'equipment',
        'investment_loan': None,
        'tender_guarantee': None,
    }
    assert len(config.fingerprint) == 64


def test_working_capital_returns_ranked_products_without_client_trace():
    result = recommend(request(), COMPANY)
    assert result.status == 'ok'
    assert [item.product_id for item in result.items][:2] == [
        'working_capital_loan', 'credit_line_smb'
    ]
    assert all(item.purpose_match for item in result.items[:2])
    assert all(0 <= item.score <= 100 for item in result.items)
    assert all(
        'недоступен' not in reason
        for item in result.items for reason in item.client_reasons
    )
    assert result.staff_trace is None


def test_staff_sees_trace():
    result = recommend(request(), COMPANY, role='staff')
    assert result.staff_trace
    assert any(item['rule_id'] == 'WC_AMOUNT' for item in result.staff_trace)


def test_equipment_without_invoice_requests_documents():
    result = recommend(request(purpose='equipment'), COMPANY)
    assert result.status == 'request_data'
    assert result.items == []
    assert any(action.kind == 'attach_document' for action in result.actions)


def test_equipment_with_invoice_and_down_payment_is_available():
    result = recommend(request(purpose='equipment', supplier_invoice_attached=True,
                               down_payment_pct=10), COMPANY)
    assert result.status == 'ok'
    assert result.items[0].product_id == 'equipment_loan'
    assert result.items[0].cabinet_product_code == 'equipment'


def test_investment_loan_for_established_company():
    result = recommend(request(
        purpose='investment', amount_kopecks=500_000_000, term_months=36,
        has_collateral=True, collateral_type='real_estate', business_plan_attached=True,
    ), COMPANY)
    assert result.status == 'ok'
    assert result.items[0].product_id == 'investment_loan'
    assert result.items[0].cabinet_product_code is None


def test_tender_requires_number():
    missing = recommend(request(purpose='tender_guarantee'), COMPANY)
    assert missing.status == 'request_data'
    ready = recommend(request(purpose='tender_guarantee', tender_number='T-42'), COMPANY)
    assert ready.status == 'ok'
    item = ready.items[0]
    assert item.product_id == 'tender_guarantee'
    assert item.commission_year_pct == 3.0
    assert item.monthly_payment_kopecks == 500_000


def test_amount_and_term_are_capped_for_counter_offer():
    result = recommend(request(amount_kopecks=2_000_000_000, has_collateral=True,
                               collateral_type='equipment'), COMPANY)
    assert result.status == 'counter_offer'
    items = {item.product_id: item for item in result.items}
    assert items['working_capital_loan'].approved_amount_kopecks == 500_000_000
    assert items['credit_line_smb'].approved_amount_kopecks == 1_500_000_000
    assert items['working_capital_loan'].client_reasons


def test_payment_burden_caps_working_capital_amount():
    result = recommend(request(
        amount_kopecks=300_000_000, revenue_total_kopecks=80_000_000,
        expenses_total_kopecks=40_000_000, existing_debt_payments_kopecks=0,
    ), COMPANY)
    working_capital = next(
        item for item in result.items if item.product_id == 'working_capital_loan'
    )
    assert working_capital.approved_amount_kopecks == 210_000_000


def test_amount_below_every_product_minimum_has_no_match():
    result = recommend(request(
        amount_kopecks=5_000_000, supplier_invoice_attached=True, down_payment_pct=20,
        has_collateral=True, collateral_type='equipment', business_plan_attached=True,
        tender_number='T-1',
    ), COMPANY)
    assert result.status == 'no_match'
    assert result.items == []


def test_cash_gap_clamps_overdraft_term():
    result = recommend(request(purpose='cash_gap', amount_kopecks=50_000_000), COMPANY)
    assert result.status == 'counter_offer'
    assert result.items[0].product_id == 'overdraft_smb'
    assert result.items[0].term_months == 3


def test_missing_financial_data_requests_data():
    result = recommend(request(revenue_total_kopecks=None, expenses_total_kopecks=None,
                               existing_debt_payments_kopecks=None), COMPANY)
    assert result.status == 'request_data'
    assert result.items == []
    assert any(action.kind == 'change_amount' for action in result.actions)


def test_global_overdue_stops_recommendations():
    result = recommend(request(), COMPANY, profile=recommendation_profile('990000000105'))
    assert result.status == 'no_match'
    assert result.items == []


def test_short_business_history_rejects_products():
    young = SimpleNamespace(inn='990000000001', name='Новая', registered_at=date.today().replace(day=1))
    result = recommend(request(), young)
    assert result.items == []
    assert result.status in ('no_match', 'request_data')


@pytest.mark.parametrize('amount,term', [(0, 12), (1_000_000, 0), (1_000_000, 121)])
def test_invalid_request_is_rejected(amount, term):
    with pytest.raises(ValueError):
        RecommendationRequest(purpose='working_capital', amount_kopecks=amount, term_months=term)


def test_contradictory_collateral_is_rejected():
    with pytest.raises(ValueError):
        RecommendationRequest(
            purpose='working_capital', amount_kopecks=1_000_000, term_months=12,
            has_collateral=True, collateral_type='none',
        )


def test_options_and_client_endpoint(client):
    headers = {'X-CSRF-Token': login(client).json()['csrf_token']}
    options = client.get(f'{BASE}/options')
    assert options.status_code == 200
    assert len(options.json()['purposes']) == 6
    response = client.post(BASE, json=request().model_dump(), headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['config_version'] == 'rules-2026.10.1'
    assert body['items'][0]['product_id'] == 'working_capital_loan'
    assert body['staff_trace'] is None


def test_staff_requires_company_id(client, db):
    from app.companies.models import Company
    from sqlalchemy import select
    login(client, 'staff@example.test')
    headers = {'X-CSRF-Token': client.get('/api/v1/auth/csrf').json()['csrf_token']}
    assert client.post(BASE, json=request().model_dump(), headers=headers).status_code == 422
    company = db.scalar(select(Company).where(Company.inn == '990000000001'))
    response = client.post(f'{BASE}?company_id={company.id}', json=request().model_dump(),
                           headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['staff_trace']
