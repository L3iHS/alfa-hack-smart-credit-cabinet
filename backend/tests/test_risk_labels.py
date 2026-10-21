from datetime import date, datetime

import pytest


def label(**changes):
    from app.risk.labels import LoanOutcome, label_loan_90dpd_12m
    values = dict(origination_date=date(2026, 1, 31), observed_through=date(2027, 1, 31))
    values.update(changes)
    return label_loan_90dpd_12m(LoanOutcome(**values))


@pytest.mark.parametrize('event,expected', [
    (date(2027, 1, 30), 1), (date(2027, 1, 31), 1), (date(2027, 2, 1), 0), (None, 0),
])
def test_annual_event_boundary_is_inclusive(event, expected):
    assert label(observed_through=date(2027, 2, 1), first_90dpd_date=event) == expected


def test_observed_event_labels_positive_before_horizon_is_complete():
    assert label(observed_through=date(2026, 6, 1), first_90dpd_date=date(2026, 5, 1)) == 1


def test_short_observation_without_final_repayment_is_censored():
    assert label(observed_through=date(2026, 6, 1)) is None


@pytest.mark.parametrize('repaid', [date(2026, 1, 31), date(2026, 6, 1)])
def test_final_repayment_before_horizon_resolves_negative_label(repaid):
    assert label(observed_through=date(2026, 6, 1), fully_repaid_date=repaid) == 0


def test_repayment_does_not_erase_preceding_event():
    assert label(observed_through=date(2026, 7, 1), first_90dpd_date=date(2026, 5, 1),
                 fully_repaid_date=date(2026, 6, 1)) == 1


def test_event_on_final_repayment_day_still_counts():
    assert label(observed_through=date(2026, 6, 1), first_90dpd_date=date(2026, 6, 1),
                 fully_repaid_date=date(2026, 6, 1)) == 1


@pytest.mark.parametrize('event,expected', [(date(2025, 2, 28), 1), (date(2025, 3, 1), 0)])
def test_leap_day_annual_horizon(event, expected):
    assert label(origination_date=date(2024, 2, 29), observed_through=date(2025, 3, 1),
                 first_90dpd_date=event) == expected


@pytest.mark.parametrize('value,months,expected', [
    (date(2024, 2, 29), 12, date(2025, 2, 28)),
    (date(2026, 1, 31), 1, date(2026, 2, 28)),
    (date(2024, 1, 31), 1, date(2024, 2, 29)),
    (date(2026, 12, 31), 2, date(2027, 2, 28)),
    (date(2026, 3, 31), -1, date(2026, 2, 28)),
    (date(2026, 1, 31), 0, date(2026, 1, 31)),
])
def test_add_months_uses_calendar_month_end(value, months, expected):
    from app.risk.labels import add_months
    assert add_months(value, months) == expected


@pytest.mark.parametrize('changes', [
    {'observed_through': date(2026, 1, 30)},
    {'first_90dpd_date': date(2026, 1, 30)},
    {'fully_repaid_date': date(2026, 1, 30)},
    {'first_90dpd_date': date(2027, 2, 1)},
    {'fully_repaid_date': date(2027, 2, 1)},
    {'fully_repaid_date': date(2026, 6, 1), 'first_90dpd_date': date(2026, 6, 2)},
    {'origination_date': None}, {'observed_through': '2027-01-31'},
    {'first_90dpd_date': datetime(2026, 6, 1)}, {'fully_repaid_date': '2026-06-01'},
])
def test_contradictory_or_invalid_dates_are_rejected(changes):
    with pytest.raises(ValueError):
        label(**changes)


@pytest.mark.parametrize('value,months', [
    (date(2026, 1, 1), True), (date(2026, 1, 1), 1.0),
    (date(2026, 1, 1), None), ('2026-01-01', 1),
    (datetime(2026, 1, 1), 1), (date(9999, 12, 1), 1), (date(1, 1, 1), -1),
])
def test_add_months_rejects_invalid_types_or_unrepresentable_date(value, months):
    from app.risk.labels import add_months
    with pytest.raises(ValueError):
        add_months(value, months)
