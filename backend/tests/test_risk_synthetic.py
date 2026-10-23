import math
import random
from dataclasses import FrozenInstanceError
from datetime import date, timedelta

import pytest

from app.risk.catalog import ML_PRODUCTS as PRODUCTS
from app.risk.features import FEATURE_NAMES, build_features
from app.risk.labels import add_months, label_loan_90dpd_12m


def generate(*args, **kwargs):
    from app.risk.synthetic import generate_loans
    return generate_loans(*args, **kwargs)


@pytest.fixture(scope='module')
def loans():
    return generate(2000, seed=20261021)


def test_generation_same_seed_is_reproducible():
    assert generate(20, seed=20261021) == generate(20, seed=20261021)
    assert generate(20, seed=20261021) == generate(30, seed=20261021)[:20]


def test_generation_different_seed_changes_examples():
    assert generate(20, seed=20261021) != generate(20, seed=20261022)


def test_generation_does_not_change_global_random_state():
    before = random.getstate()
    generate(20)
    assert random.getstate() == before


def test_default_generation_produces_ten_thousand_loans():
    assert len(generate()) == 10000


@pytest.mark.parametrize('count', [0, -1, True, False, 1.5, '10', None])
def test_generation_rejects_invalid_count(count):
    with pytest.raises(ValueError, match='count'):
        generate(count)


@pytest.mark.parametrize('seed', [True, False, 1.5, '10', None])
def test_generation_rejects_noninteger_seed(seed):
    with pytest.raises(ValueError, match='seed'):
        generate(1, seed=seed)


def test_zero_and_negative_integer_seeds_are_reproducible():
    for seed in (0, -7):
        assert generate(2, seed=seed) == generate(2, seed=seed)


def test_generated_inputs_match_catalog_and_feature_builder(loans):
    for index, loan in enumerate(loans, start=1):
        application = loan.application
        product = PRODUCTS[application['product_code']]
        assert loan.company_id == f'synthetic-company-{index:06d}'
        assert loan.application_id == f'synthetic-application-{index:06d}'
        assert loan.submitted_at == date(2025, 1, 15)
        assert application['period_start'] == '2024-10-01'
        assert application['period_end'] == '2024-12-31'
        assert loan.registered_at <= date(2024, 10, 1)
        assert 0 <= loan.overdue_days <= 89
        assert application['purpose']
        assert application['description']
        assert product.min_amount_kopecks <= application['amount_kopecks'] <= product.max_amount_kopecks
        assert product.min_term_months <= application['term_months'] <= product.max_term_months
        for name in ('amount_kopecks', 'revenue_kopecks', 'operating_expenses_kopecks',
                     'existing_debt_payments_kopecks'):
            assert type(application[name]) is int and application[name] >= 0
        assert loan.features == build_features(application, registered_at=loan.registered_at,
                                               submitted_at=loan.submitted_at, overdue_days=loan.overdue_days,
                                               annual_rate_bps=product.annual_rate_bps)
        assert loan.features.values['monthly_revenue_rub'] == pytest.approx(application['revenue_kopecks'] / 300)


def test_generated_population_contains_required_financial_cases(loans):
    assert {loan.application['product_code'] for loan in loans} == set(PRODUCTS)
    assert any(loan.features.values['business_age_months'] < 6 for loan in loans)
    assert any(loan.features.values['business_age_months'] > 120 for loan in loans)
    assert any(loan.application['operating_expenses_kopecks'] > loan.application['revenue_kopecks'] for loan in loans)
    assert 0 < sum(loan.application['revenue_kopecks'] == 0 for loan in loans) < len(loans) // 10
    assert len({loan.application['term_months'] for loan in loans}) > 10
    assert any(loan.overdue_days == 0 for loan in loans)
    assert any(loan.overdue_days == 89 for loan in loans)


def test_generated_outcomes_have_consistent_event_and_repayment_dates(loans):
    labels = set()
    short_negative = long_negative = False
    for loan in loans:
        outcome = loan.outcome
        horizon = date(2026, 1, 15)
        maturity = add_months(loan.submitted_at, loan.application['term_months'])
        assert outcome.origination_date == loan.submitted_at
        label = label_loan_90dpd_12m(outcome)
        assert label in (0, 1)
        labels.add(label)
        assert math.isfinite(loan.true_probability) and 0 < loan.true_probability < 1
        if label == 1:
            assert date(2025, 2, 15) + timedelta(days=90) <= outcome.first_90dpd_date <= horizon
            missed_payment = outcome.first_90dpd_date - timedelta(days=90)
            assert missed_payment in {add_months(loan.submitted_at, month)
                                      for month in range(1, loan.application['term_months'] + 1)}
            assert outcome.fully_repaid_date is None
            assert outcome.first_90dpd_date <= outcome.observed_through <= horizon
        elif loan.application['term_months'] < 12:
            short_negative = True
            assert outcome.first_90dpd_date is None
            assert outcome.fully_repaid_date == outcome.observed_through == maturity
        else:
            long_negative = True
            assert outcome.first_90dpd_date is None
            assert outcome.fully_repaid_date is None
            assert outcome.observed_through == horizon
    assert labels == {0, 1}
    assert short_negative and long_negative


def test_generated_features_exclude_future_values_and_diagnostics(loans):
    for loan in loans:
        assert tuple(loan.features.values) == FEATURE_NAMES
        assert tuple(loan.features.missing_mask) == FEATURE_NAMES
        assert all(math.isfinite(value) for value in loan.features.values.values()
                   if isinstance(value, (int, float)))
        assert not {'true_probability', 'label', 'decision', 'first_90dpd_date',
                    'company_id', 'application_id'} & loan.application.keys()


def test_generated_labels_do_not_duplicate_coverage_rule(loans):
    for above_threshold in (False, True):
        labels = {label_loan_90dpd_12m(loan.outcome) for loan in loans
                  if (loan.features.values['coverage_ratio'] >= 1.30) is above_threshold}
        assert labels == {0, 1}


def test_extra_outcome_random_draws_do_not_change_inputs(monkeypatch):
    from app.risk import synthetic
    baseline = generate(20)
    original = synthetic._generate_outcome

    def extra_draws(term, probability, rng):
        result = original(term, probability, rng)
        for _ in range(7):
            rng.random()
        return result

    monkeypatch.setattr(synthetic, '_generate_outcome', extra_draws)
    changed = generate(20)
    assert [(loan.application, loan.registered_at, loan.overdue_days, loan.features, loan.true_probability)
            for loan in baseline] == [
                (loan.application, loan.registered_at, loan.overdue_days, loan.features, loan.true_probability)
                for loan in changed]
    assert [loan.outcome for loan in baseline] != [loan.outcome for loan in changed]


def test_generated_loan_record_is_frozen():
    loan = generate(1)[0]
    with pytest.raises(FrozenInstanceError):
        loan.company_id = 'other-company'
