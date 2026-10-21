import math
from datetime import date, datetime
from decimal import Decimal, localcontext

import pytest


FEATURES = (
    'business_age_months', 'monthly_revenue_rub', 'operating_margin_ratio',
    'existing_debt_to_revenue_ratio', 'coverage_ratio', 'overdue_days',
    'product_code', 'requested_amount_rub', 'term_months',
)


def application(**changes):
    data = dict(product_code='equipment', amount_kopecks=200_000_000, term_months=24,
                period_start='2026-07-01', period_end='2026-09-30', revenue_kopecks=240_000_000,
                operating_expenses_kopecks=150_000_000, existing_debt_payments_kopecks=15_000_000)
    data.update(changes)
    return data


def build(data=None, **changes):
    from app.risk.features import build_features
    options = dict(registered_at=date(2024, 10, 20), submitted_at=date(2026, 10, 20),
                   overdue_days=0, annual_rate_bps=2400)
    options.update(changes)
    return build_features(application() if data is None else data, **options)


def test_features_match_processing_calculation():
    from app.processing.policy import evaluate
    from app.risk.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
    calculation = evaluate(application(), registered_at=date(2024, 10, 20),
                           submitted_at=date(2026, 10, 20), overdue_days=0, liquidated=False).calculation
    assert calculation.monthly_payment_kopecks == 10_574_220
    vector = build()
    assert vector.values == dict(
        business_age_months=24, monthly_revenue_rub=800_000.0, operating_margin_ratio=0.375,
        existing_debt_to_revenue_ratio=0.0625, coverage_ratio=float(calculation.coverage_ratio),
        overdue_days=0, product_code='equipment', requested_amount_rub=2_000_000.0, term_months=24,
    )
    assert tuple(vector.values) == tuple(vector.missing_mask) == FEATURE_NAMES == FEATURES
    assert vector.missing_mask == dict.fromkeys(FEATURES, False)
    assert vector.schema_version == FEATURE_SCHEMA_VERSION == 'risk-features-v1'


@pytest.mark.parametrize('registered_at,expected', [
    (date(2026, 4, 21), 5), (date(2026, 4, 20), 6), (date(2026, 10, 20), 0),
])
def test_business_age_is_completed_months_at_submission(registered_at, expected):
    assert build(registered_at=registered_at).values['business_age_months'] == expected


def test_zero_revenue_keeps_missing_ratios_and_finite_coverage():
    vector = build(application(revenue_kopecks=0, operating_expenses_kopecks=15_000_000))
    assert vector.values['monthly_revenue_rub'] == 0
    assert vector.values['operating_margin_ratio'] is None
    assert vector.values['existing_debt_to_revenue_ratio'] is None
    assert {key for key, missing in vector.missing_mask.items() if missing} == {
        'operating_margin_ratio', 'existing_debt_to_revenue_ratio',
    }
    assert vector.values['coverage_ratio'] == pytest.approx(-0.321043365253605)
    assert all(math.isfinite(value) for value in vector.values.values() if isinstance(value, (int, float)))


def test_negative_margin_and_zero_existing_debt_are_valid():
    vector = build(application(revenue_kopecks=150_000_000, operating_expenses_kopecks=240_000_000,
                               existing_debt_payments_kopecks=0), overdue_days=89)
    assert vector.values['operating_margin_ratio'] == -0.6
    assert vector.values['existing_debt_to_revenue_ratio'] == 0
    assert vector.values['coverage_ratio'] < 0
    assert vector.values['overdue_days'] == 89
    assert not any(vector.missing_mask.values())


def test_multi_month_finances_and_coverage_preserve_policy_precision():
    from app.processing.policy import evaluate
    data = application(revenue_kopecks=150_000_003, operating_expenses_kopecks=150_000_001,
                       existing_debt_payments_kopecks=1)
    calculation = evaluate(data, registered_at=date(2024, 10, 20), submitted_at=date(2026, 10, 20),
                           overdue_days=0, liquidated=False).calculation
    with localcontext() as context:
        context.prec = 6
        vector = build(data)
    assert vector.values['monthly_revenue_rub'] == 500_000.01
    assert vector.values['coverage_ratio'] == float(calculation.coverage_ratio)
    assert vector.values['operating_margin_ratio'] == pytest.approx(float(Decimal(2) / Decimal(150_000_003)))


def test_extra_snapshot_identifiers_and_future_outcomes_are_not_features():
    data = application(inn='1234567890', company_id='company', application_id='request',
                       first_90dpd_date='2027-02-01', fully_repaid_date='2027-03-01',
                       true_probability=0.8, label=1, decision='rejected')
    assert build(data) == build()


@pytest.mark.parametrize('product_code,amount,term', [
    ('working_capital', 10_000_000, 3), ('working_capital', 500_000_000, 24),
    ('equipment', 30_000_000, 6), ('equipment', 1_000_000_000, 36),
])
def test_catalog_boundaries_are_supported(product_code, amount, term):
    vector = build(application(product_code=product_code, amount_kopecks=amount, term_months=term))
    assert vector.values['product_code'] == product_code
    assert vector.values['requested_amount_rub'] == amount / 100
    assert vector.values['term_months'] == term


@pytest.mark.parametrize('field', [
    'product_code', 'amount_kopecks', 'term_months', 'period_start', 'period_end',
    'revenue_kopecks', 'operating_expenses_kopecks', 'existing_debt_payments_kopecks',
])
def test_missing_required_snapshot_fields_are_rejected(field):
    data = application()
    del data[field]
    with pytest.raises(ValueError):
        build(data)


@pytest.mark.parametrize('field', [
    'amount_kopecks', 'term_months', 'revenue_kopecks',
    'operating_expenses_kopecks', 'existing_debt_payments_kopecks',
])
@pytest.mark.parametrize('value', [True, None, '100', 100.0, -1])
def test_invalid_numeric_snapshot_values_are_rejected(field, value):
    with pytest.raises(ValueError):
        build(application(**{field: value}))


@pytest.mark.parametrize('changes', [
    {'product_code': 'unknown'}, {'product_code': None}, {'product_code': []},
    {'amount_kopecks': 29_999_999}, {'amount_kopecks': 1_000_000_001},
    {'term_months': 5}, {'term_months': 37},
    {'product_code': 'working_capital', 'amount_kopecks': 9_999_999},
    {'product_code': 'working_capital', 'amount_kopecks': 500_000_001},
    {'product_code': 'working_capital', 'term_months': 2},
    {'product_code': 'working_capital', 'term_months': 25},
    {'period_start': None}, {'period_end': 'bad'}, {'period_start': date(2026, 7, 1)},
    {'period_start': '2026-07-02'}, {'period_end': '2026-09-29'},
    {'period_start': '2026-10-01', 'period_end': '2026-10-31'},
    {'period_start': '2027-01-01', 'period_end': '2027-01-31'},
    {'period_start': '2026-09-01', 'period_end': '2026-07-31'},
    {'revenue_kopecks': 10 ** 400},
])
def test_invalid_snapshot_domain_values_are_rejected(changes):
    with pytest.raises(ValueError):
        build(application(**changes))


@pytest.mark.parametrize('changes', [
    {'registered_at': date(2026, 10, 21)}, {'registered_at': '2024-01-01'},
    {'registered_at': datetime(2024, 1, 1)}, {'submitted_at': None},
    {'submitted_at': datetime(2026, 10, 20)},
    {'overdue_days': -1}, {'overdue_days': 90}, {'overdue_days': True}, {'overdue_days': 1.0},
    {'annual_rate_bps': True}, {'annual_rate_bps': None}, {'annual_rate_bps': 2400.0},
    {'annual_rate_bps': -1},
])
def test_invalid_run_parameters_are_rejected(changes):
    with pytest.raises(ValueError):
        build(**changes)


def test_explicit_zero_or_alternative_rate_is_used_for_payment():
    zero_rate = build(annual_rate_bps=0)
    assert zero_rate.values['coverage_ratio'] == pytest.approx(2.2499998875000056)
    alternative_rate = build(annual_rate_bps=2500)
    assert alternative_rate.values['coverage_ratio'] < build().values['coverage_ratio']
