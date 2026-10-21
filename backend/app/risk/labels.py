import calendar
from dataclasses import dataclass
from datetime import date

TARGET_EVENT = 'loan_90dpd_12m'
HORIZON_MONTHS = 12


def add_months(value: date, months: int) -> date:
    """Сдвигает календарную дату, обрезая день до конца целевого месяца."""
    if type(value) is not date or type(months) is not int:
        raise ValueError('Нужны календарная дата и целое число месяцев')
    year, month_index = divmod(value.year * 12 + value.month - 1 + months, 12)
    if not 1 <= year <= 9999:
        raise ValueError('Дата выходит за допустимый календарный диапазон')
    month = month_index + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class LoanOutcome:
    origination_date: date
    observed_through: date
    first_90dpd_date: date | None = None
    fully_repaid_date: date | None = None


def label_loan_90dpd_12m(outcome: LoanOutcome) -> int | None:
    """Размечает событие за год, сохраняя неизвестный исход неполного наблюдения."""
    if type(outcome.origination_date) is not date or type(outcome.observed_through) is not date:
        raise ValueError('Нужны даты выдачи и окончания наблюдения')
    if outcome.observed_through < outcome.origination_date:
        raise ValueError('Наблюдение не может закончиться раньше выдачи')
    for event in (outcome.first_90dpd_date, outcome.fully_repaid_date):
        if event is not None and (type(event) is not date or not outcome.origination_date <= event <= outcome.observed_through):
            raise ValueError('Событие должно быть между выдачей и окончанием наблюдения')
    if (outcome.first_90dpd_date is not None and outcome.fully_repaid_date is not None
            and outcome.first_90dpd_date > outcome.fully_repaid_date):
        raise ValueError('Просрочка не может наступить после окончательного погашения')
    horizon = add_months(outcome.origination_date, HORIZON_MONTHS)
    if outcome.first_90dpd_date is not None and outcome.first_90dpd_date <= horizon:
        return 1
    if outcome.observed_through >= horizon or outcome.fully_repaid_date is not None:
        return 0
    return None
