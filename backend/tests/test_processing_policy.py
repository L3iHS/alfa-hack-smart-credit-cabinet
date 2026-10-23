from datetime import date
from decimal import Decimal

import pytest


def calculate(**changes):
    from app.processing.policy import evaluate
    data = dict(product_code='equipment', amount_kopecks=200_000_000, term_months=24,
                period_start='2026-07-01', period_end='2026-09-30', revenue_kopecks=240_000_000,
                operating_expenses_kopecks=150_000_000, existing_debt_payments_kopecks=15_000_000)
    data.update(changes)
    return evaluate(data, registered_at=date(2024, 10, 20), submitted_at=date(2026, 10, 20), overdue_days=0, liquidated=False, policy_version='demo-policy-0.2')


def test_profile_a_payment():
    result = calculate()
    assert result.outcome == 'approved'
    assert result.calculation.monthly_payment_kopecks == 10_574_220


def test_profile_b_offer():
    result = calculate(product_code='working_capital', amount_kopecks=500_000_000, term_months=12,
                       revenue_kopecks=210_000_000, existing_debt_payments_kopecks=9_000_000)
    assert result.outcome == 'counteroffer'
    assert result.offer.amount_kopecks == 234_200_000
    assert result.offer.term_months == 24
    assert result.offer.monthly_payment_kopecks == 12_382_411


@pytest.mark.parametrize('age,outcome', [(5,'manual_review'), (6,'approved')])
def test_full_month_boundary(age, outcome):
    from app.processing.policy import evaluate
    result = evaluate(dict(product_code='equipment', amount_kopecks=200_000_000, term_months=24,
                           period_start='2026-07-01', period_end='2026-09-30', revenue_kopecks=240_000_000,
                           operating_expenses_kopecks=150_000_000, existing_debt_payments_kopecks=15_000_000),
                      registered_at=date(2026, 10-age, 20), submitted_at=date(2026, 10, 20), overdue_days=0, liquidated=False, policy_version='demo-policy-0.2')
    assert result.outcome == outcome


@pytest.mark.parametrize('days,outcome', [(0,'approved'),(1,'manual_review'),(89,'manual_review'),(90,'rejected')])
def test_overdue_boundaries(days, outcome):
    from app.processing.policy import evaluate
    data = dict(product_code='equipment', amount_kopecks=200_000_000, term_months=24,
                period_start='2026-07-01', period_end='2026-09-30', revenue_kopecks=240_000_000,
                operating_expenses_kopecks=150_000_000, existing_debt_payments_kopecks=15_000_000)
    assert evaluate(data, registered_at=date(2024, 1, 1), submitted_at=date(2026, 10, 20), overdue_days=days, liquidated=False, policy_version='demo-policy-0.2').outcome == outcome


def test_exact_coverage_boundary():
    from app.processing.policy import covered
    assert covered(Decimal('130'), Decimal('0'), 100)
    assert not covered(Decimal('129.999999999999'), Decimal('0'), 100)


def test_age_days_and_completed_calendar_period():
    from app.processing.policy import full_months, period_months
    assert full_months(date(2026,4,21), date(2026,10,20)) == 5
    assert full_months(date(2026,4,20), date(2026,10,20)) == 6
    assert period_months(date(2025,12,1),date(2026,2,28),date(2026,3,1)) == 3
    for start,end in [(date(2026,1,2), date(2026,3,31)),(date(2026,1,1),date(2026,3,30)),(date(2026,10,1),date(2026,10,31))]:
        with pytest.raises(ValueError):
            period_months(start,end,date(2026,10,20))


def test_no_affordable_offer_and_nonpositive_flow():
    assert calculate(revenue_kopecks=150_000_000).outcome == 'manual_review'
    result = calculate(revenue_kopecks=150_000_003, existing_debt_payments_kopecks=0)
    assert result.outcome == 'manual_review'
    assert result.reason_code == 'no_affordable_terms'


def test_first_extension_preferred_to_amount_reduction():
    from app.processing.policy import payment
    from decimal import ROUND_CEILING
    target_flow = int((Decimal(payment(200000000,25))*Decimal('1.30')*3).to_integral_value(rounding=ROUND_CEILING))
    result = calculate(revenue_kopecks=150000000+target_flow, existing_debt_payments_kopecks=0)
    assert result.outcome == 'counteroffer'
    assert result.offer.amount_kopecks == 200000000
    assert result.offer.term_months == 25


def test_coverage_uses_period_totals_without_rounding_monthly_averages():
    from app.processing.policy import payment
    amount,term = 200000000,24
    debt = 1
    flow = Decimal('1.3')*(debt+payment(amount,term)*3)
    # Деление на три даёт бесконечную дробь, но сравнение в копейках за период точное.
    from app.processing.policy import covered
    assert covered(flow,Decimal(debt),payment(amount,term),3)
    assert not covered(flow-Decimal('0.01'),Decimal(debt),payment(amount,term),3)


def test_information_request_has_priority_over_stop_factor():
    from app.processing.policy import evaluate
    data = dict(product_code='equipment', amount_kopecks=200000000,term_months=24,
                period_start='2026-07-01',period_end='2026-09-30',revenue_kopecks=210000000,
                operating_expenses_kopecks=150000000,existing_debt_payments_kopecks=15000000)
    result = evaluate(data,registered_at=date(2024,1,1),submitted_at=date(2026,10,20),
                      overdue_days=100,liquidated=True,expected_monthly_revenue_kopecks=80000000)
    assert result.outcome == 'needs_info'
    data['revenue_kopecks'] = 240000000
    assert evaluate(data,registered_at=date(2024,1,1),submitted_at=date(2026,10,20),overdue_days=0,liquidated=True).outcome == 'rejected'


@pytest.mark.parametrize('version', ['demo-policy-v1', 'demo-policy-0.2', 'demo-policy-0.3', 'demo-policy-0.4'])
@pytest.mark.parametrize('liquidated,overdue,outcome,code,reason', [
    (True, 100, 'rejected', 'company_liquidated', 'Синтетический реестр подтверждает ликвидацию компании'),
    (False, 90, 'rejected', 'overdue_90_plus', 'Текущая просрочка по демонстрационной проверке БКИ составляет 90 дней или более'),
    (False, 89, 'manual_review', 'current_overdue', None),
    (False, 0, 'approved', 'coverage_sufficient', None),
])
def test_company_stop_results_and_priority_stay_identical_for_historical_policies(version, liquidated, overdue, outcome, code, reason):
    from app.processing.policy import evaluate
    data = dict(product_code='equipment', amount_kopecks=200_000_000, term_months=24,
                period_start='2026-07-01', period_end='2026-09-30', revenue_kopecks=240_000_000,
                operating_expenses_kopecks=150_000_000, existing_debt_payments_kopecks=15_000_000)
    result = evaluate(data, registered_at=date(2024, 1, 1), submitted_at=date(2026, 10, 20),
                      liquidated=liquidated, overdue_days=overdue, policy_version=version, probability=.05)
    assert (result.outcome, result.reason_code) == (outcome, code)
    assert result.calculation.monthly_payment_kopecks == 10_574_220
    if reason is not None:
        assert result.reason == reason
    # Несовпадение финансовых сведений по-прежнему проверяется до обоих стопов.
    priority = evaluate(data, registered_at=date(2024, 1, 1), submitted_at=date(2026, 10, 20),
        liquidated=True, overdue_days=100, policy_version=version, probability=.05,
        expected_monthly_revenue_kopecks=1)
    assert (priority.outcome, priority.reason_code) == ('needs_info', 'revenue_mismatch')
