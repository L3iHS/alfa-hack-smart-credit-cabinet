from decimal import localcontext

import pytest
from pydantic import ValidationError


def terms(code, amount, term):
    from app.products.calculations import calculate_terms
    from app.products.catalog import get_product
    return calculate_terms(get_product(code, 'demo-v2'), amount, term)


def test_versioned_catalog_is_isolated_and_retains_historical_products():
    from app.products.catalog import CATALOG_VERSION, PRODUCTS, get_catalog, get_product
    assert CATALOG_VERSION == 'demo-v1'
    assert set(PRODUCTS) == {'working_capital', 'equipment'}
    v1, v2 = get_catalog('demo-v1'), get_catalog('demo-v2')
    assert set(v1) == {'working_capital', 'equipment'}
    assert set(v2) == set(v1) | {'overdraft', 'credit_line', 'investment', 'tender_guarantee'}
    assert v1['equipment'] == v2['equipment']
    assert v1['working_capital'].min_amount_kopecks == 10_000_000
    assert v1['equipment'].max_amount_kopecks == 1_000_000_000
    v2.clear()
    assert len(get_catalog('demo-v2')) == 6
    with pytest.raises(ValidationError):
        get_product('equipment', 'demo-v1').annual_rate_bps = 0
    with pytest.raises(TypeError):
        PRODUCTS['equipment'] = PRODUCTS['working_capital']
    for code, version in [('overdraft', 'demo-v1'), ('unknown', 'demo-v2'), ('equipment', 'unknown')]:
        with pytest.raises(ValueError):
            get_product(code, version)
    with pytest.raises(ValueError):
        get_catalog('unknown')


def test_product_specific_requirements_and_rates():
    from app.products.catalog import get_product
    cases = [
        ('overdraft', 10_000_000, 300_000_000, 1, 3, 2100, 0, 0, 'revolving', ('bank_statement',), ()),
        ('credit_line', 50_000_000, 1_500_000_000, 6, 24, 2000, 50, 0, 'revolving', ('bank_statement',), ()),
        ('investment', 300_000_000, 10_000_000_000, 24, 120, 1600, 150, 0, 'annuity', ('business_plan',), ('project_description',)),
        ('tender_guarantee', 10_000_000, 2_000_000_000, 1, 36, None, 0, 300, 'guarantee', ('tender_document',), ('tender_number', 'beneficiary_name')),
    ]
    for code, minimum, maximum, mint, maxt, rate, fee, annual, kind, documents, fields in cases:
        product = get_product(code, 'demo-v2')
        assert (product.min_amount_kopecks, product.max_amount_kopecks, product.min_term_months, product.max_term_months) == (minimum, maximum, mint, maxt)
        assert (product.annual_rate_bps, product.upfront_fee_bps, product.annual_commission_bps, product.payment_kind) == (rate, fee, annual, kind)
        assert product.required_document_types == ('financial_statement',) + documents
        assert product.required_application_fields == fields


@pytest.mark.parametrize('code,amount,term,monthly,fee,principal,last,total,cost,burden,liability', [
    ('equipment', 200_000_000, 24, 10_574_220, 0, 0, 10_574_220, 253_781_280, 53_781_280, 10_574_220, 0),
    ('working_capital', 234_200_000, 24, 12_382_411, 0, 0, 12_382_411, 297_177_864, 62_977_864, 12_382_411, 0),
    ('overdraft', 10_000_000, 2, 175_000, 0, 10_000_000, 10_175_000, 10_350_000, 350_000, 5_175_000, 0),
    ('credit_line', 60_000_000, 6, 1_000_000, 300_000, 60_000_000, 61_000_000, 66_300_000, 6_300_000, 11_300_000, 0),
    ('tender_guarantee', 100_000_000, 12, None, 3_000_000, 0, 0, 3_000_000, 3_000_000, None, 100_000_000),
])
def test_exact_payment_terms(code, amount, term, monthly, fee, principal, last, total, cost, burden, liability):
    result = terms(code, amount, term)
    assert result.amount_kopecks == amount
    assert result.term_months == term
    assert result.monthly_payment_kopecks == monthly
    assert result.upfront_fee_kopecks == fee
    assert result.principal_due_at_end_kopecks == principal
    assert result.last_payment_kopecks == last
    assert result.total_payment_kopecks == total
    assert result.total_cost_kopecks == cost
    assert result.assessment_monthly_burden_kopecks == burden
    assert result.contingent_liability_kopecks == liability
    assert result.assumptions


def test_fractional_kopecks_are_rounded_up_and_context_is_local():
    # 100000,01 ₽: проценты 1750,000175 ₽; резерв за 3 месяца 33333,33666… ₽.
    with localcontext() as context:
        context.prec = 6
        result = terms('overdraft', 10_000_001, 3)
    assert result.monthly_payment_kopecks == 175_001
    assert result.assessment_monthly_burden_kopecks == 3_508_335
    assert terms('credit_line', 50_000_001, 6).upfront_fee_kopecks == 250_001
    assert terms('tender_guarantee', 10_000_001, 1).upfront_fee_kopecks == 25_001


def test_investment_annuity_includes_fee_in_first_month_burden():
    result = terms('investment', 300_000_000, 120)
    assert result.monthly_payment_kopecks == 5_025_394
    assert result.upfront_fee_kopecks == 4_500_000
    assert result.assessment_monthly_burden_kopecks == 9_525_394
    assert result.total_payment_kopecks == 607_547_280


@pytest.mark.parametrize('code', ['working_capital', 'equipment', 'overdraft', 'credit_line', 'investment', 'tender_guarantee'])
def test_catalog_boundaries(code):
    from app.products.catalog import get_product
    product = get_product(code, 'demo-v2')
    terms(code, product.min_amount_kopecks, product.min_term_months)
    terms(code, product.max_amount_kopecks, product.max_term_months)
    for amount, term in [(product.min_amount_kopecks-1, product.min_term_months),
                         (product.max_amount_kopecks+1, product.min_term_months),
                         (product.min_amount_kopecks, product.min_term_months-1),
                         (product.min_amount_kopecks, product.max_term_months+1),
                         (True, product.min_term_months), (product.min_amount_kopecks, 3.5)]:
        with pytest.raises(ValueError):
            terms(code, amount, term)


def test_legacy_offer_uses_persisted_totals_without_catalog_repricing():
    from app.processing.models import Offer
    from app.products.calculations import payment_terms_from_legacy_offer
    offer = Offer(product_code='working_capital', amount_kopecks=10_000_000,
                  term_months=3, annual_rate_bps=1700,
                  monthly_payment_kopecks=3_428_220, total_payment_kopecks=10_284_659)
    result = payment_terms_from_legacy_offer(offer)
    assert result.annual_rate_bps == 1700
    assert result.monthly_payment_kopecks == 3_428_220
    assert result.total_payment_kopecks == 10_284_659
    assert result.total_cost_kopecks == 284_659
    assert result.assessment_monthly_burden_kopecks == 3_428_220
    assert result.last_payment_kopecks == 3_428_220


def test_unactivated_product_is_rejected_safely_in_draft_api(client):
    from test_auth import login
    headers = {'X-CSRF-Token': login(client).json()['csrf_token']}
    response = client.post('/api/v1/applications', json={'product_code': 'overdraft'}, headers=headers)
    assert response.status_code == 422
    assert response.json()['field_errors']['product_code']
