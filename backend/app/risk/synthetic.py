"""Явно синтетические кредитные истории; коэффициенты придуманы для эксперимента."""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from random import Random

from app.risk.catalog import ML_PRODUCTS as PRODUCTS
from app.risk.features import FeatureVector, build_features
from app.risk.labels import HORIZON_MONTHS, LoanOutcome, add_months

GENERATOR_VERSION = 'risk-synthetic-v1'
DEFAULT_SEED = 20261021
_SUBMITTED_AT = date(2025, 1, 15)
_HORIZON = add_months(_SUBMITTED_AT, HORIZON_MONTHS)


@dataclass(frozen=True)
class SyntheticLoan:
    company_id: str
    application_id: str
    application: dict
    submitted_at: date
    registered_at: date
    overdue_days: int
    features: FeatureVector
    outcome: LoanOutcome
    true_probability: float


def _event_dates(term: int) -> list[date]:
    """Допускает пропуск платежа до погашения и достижение 90 дней в горизонте."""
    dates = [add_months(_SUBMITTED_AT, month) + timedelta(days=90)
             for month in range(1, min(term, HORIZON_MONTHS) + 1)]
    return [event for event in dates if event <= _HORIZON]


def _true_probability(features: FeatureVector) -> float:
    """Плавная игрушечная вероятность целевого события, а не банковская оценка.

    Месячная интенсивность q = sigmoid(z). Возраст и оборот снижают z,
    маржа и покрытие тоже; долговая нагрузка и известная просрочка повышают.
    Для нулевой выручки неопределённые отношения заменены нейтральным нулём
    только внутри генератора; exp(-R/100000) плавно повышает риск малого R.
    За n допустимых платежей p = 1 - (1-q)**n: короткий срок уменьшает
    экспозицию, а платежи, не успевающие достичь 90 дней за год, исключены.
    Все коэффициенты заданы вручную, не оценены на банковских данных.
    """
    values = features.values
    age = float(values['business_age_months'])
    revenue = float(values['monthly_revenue_rub'])
    margin = float(values['operating_margin_ratio'] or 0)
    debt_ratio = float(values['existing_debt_to_revenue_ratio'] or 0)
    coverage = float(values['coverage_ratio'])
    overdue = float(values['overdue_days'])
    score = (-2.6 - 0.45 * math.log1p(age / 12) - 0.25 * math.log1p(revenue / 100_000)
             - 1.2 * math.tanh(margin) + 1.8 * math.tanh(debt_ratio)
             - 0.45 * math.tanh(coverage / 2) + 1.5 * overdue / 89
             + 0.8 * math.exp(-revenue / 100_000))
    monthly_probability = 1 / (1 + math.exp(-score))
    exposure = len(_event_dates(int(values['term_months'])))
    return -math.expm1(exposure * math.log1p(-monthly_probability))


def _generate_outcome(term: int, probability: float, rng: Random) -> LoanOutcome:
    """Разыгрывает событие, затем равномерно выбирает допустимый пропуск платежа."""
    if rng.random() < probability:
        # Старые обязательства не задают возраст просрочки по новому кредиту.
        event = rng.choice(_event_dates(term))
        return LoanOutcome(origination_date=_SUBMITTED_AT, observed_through=_HORIZON,
                           first_90dpd_date=event)
    if term < HORIZON_MONTHS:
        maturity = add_months(_SUBMITTED_AT, term)
        return LoanOutcome(origination_date=_SUBMITTED_AT, observed_through=maturity,
                           fully_repaid_date=maturity)
    return LoanOutcome(origination_date=_SUBMITTED_AT, observed_through=_HORIZON)


def generate_loans(count: int = 10000, seed: int = DEFAULT_SEED) -> list[SyntheticLoan]:
    """Создаёт по одной полной заявке и известному годовому исходу на компанию.

    Финансы относятся к трём завершённым месяцам. Деньги генерируются целыми
    копейками; нормализация, платёж и признаки считаются общим build_features.
    Все компании действуют, а регистрация предшествует финансовому периоду.
    Потоки входов и исходов разделены, чтобы смена разметки не меняла компании.
    true_probability служит диагностикой генератора и не входит в признаки.
    """
    if type(count) is not int or count < 1:
        raise ValueError('count: нужно положительное целое число')
    if type(seed) is not int:
        raise ValueError('seed: нужно целое число')
    inputs_rng = Random(f'{seed}:inputs')
    outcomes_rng = Random(f'{seed}:outcomes')
    products = tuple(PRODUCTS.values())
    loans = []
    for index in range(1, count + 1):
        product = inputs_rng.choice(products)
        age = inputs_rng.randint(4, 5) if inputs_rng.random() < 0.1 else inputs_rng.randint(6, 240)
        registered_at = add_months(_SUBMITTED_AT, -age)
        revenue = 0 if inputs_rng.random() < 0.03 else inputs_rng.randint(15_000_000, 1_200_000_000)
        expenses = (revenue * inputs_rng.randint(2500, 12000) // 10_000 if revenue
                    else inputs_rng.randint(1_500_000, 90_000_000))
        debt = revenue * inputs_rng.randint(0, 3000) // 10_000
        overdue_days = 0 if inputs_rng.random() < 0.7 else inputs_rng.randint(1, 89)
        application = dict(
            product_code=product.code, purpose=product.purpose_description,
            description='Синтетическая заявка действующей компании для эксперимента',
            amount_kopecks=inputs_rng.randint(product.min_amount_kopecks, product.max_amount_kopecks),
            term_months=inputs_rng.randint(product.min_term_months, product.max_term_months),
            period_start='2024-10-01', period_end='2024-12-31', revenue_kopecks=revenue,
            operating_expenses_kopecks=expenses, existing_debt_payments_kopecks=debt,
        )
        features = build_features(application, registered_at=registered_at, submitted_at=_SUBMITTED_AT,
                                  overdue_days=overdue_days, annual_rate_bps=product.annual_rate_bps)
        probability = _true_probability(features)
        loans.append(SyntheticLoan(
            company_id=f'synthetic-company-{index:06d}',
            application_id=f'synthetic-application-{index:06d}', application=application,
            submitted_at=_SUBMITTED_AT, registered_at=registered_at, overdue_days=overdue_days,
            features=features, outcome=_generate_outcome(application['term_months'], probability, outcomes_rng),
            true_probability=probability,
        ))
    return loans
