import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from app.processing.policy import full_months, payment, period_months
from app.products.catalog import PRODUCTS

FEATURE_SCHEMA_VERSION = 'risk-features-v1'
FEATURE_NAMES = (
    'business_age_months', 'monthly_revenue_rub', 'operating_margin_ratio',
    'existing_debt_to_revenue_ratio', 'coverage_ratio', 'overdue_days',
    'product_code', 'requested_amount_rub', 'term_months',
)


@dataclass(frozen=True)
class FeatureVector:
    values: dict[str, float | int | str | None]
    missing_mask: dict[str, bool]
    schema_version: str = FEATURE_SCHEMA_VERSION


def _integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f'{name}: нужно неотрицательное целое число')
    return value


def _snapshot_date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f'{name}: нужна дата в формате ISO')
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'{name}: нужна дата в формате ISO') from error


def _finite_float(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Значение признака выходит за конечный числовой диапазон')
    return result


def build_features(application: Mapping[str, object], *, registered_at: date, submitted_at: date,
                   overdue_days: int, annual_rate_bps: int) -> FeatureVector:
    """Готовит признаки из снимка отправки и результатов проверок того же запуска."""
    if not isinstance(application, Mapping):
        raise ValueError('Нужен снимок полей заявки')
    if type(registered_at) is not date or type(submitted_at) is not date or registered_at > submitted_at:
        raise ValueError('Нужны даты регистрации и отправки в правильном порядке')
    overdue_days = _integer(overdue_days, 'overdue_days')
    if overdue_days > 89:
        raise ValueError('Оценка доступна при исходной просрочке от 0 до 89 дней')
    annual_rate_bps = _integer(annual_rate_bps, 'annual_rate_bps')
    try:
        product_code = application['product_code']
        if not isinstance(product_code, str) or product_code not in PRODUCTS:
            raise ValueError('Продукт отсутствует в каталоге')
        product = PRODUCTS[product_code]
        amount = _integer(application['amount_kopecks'], 'amount_kopecks')
        term = _integer(application['term_months'], 'term_months')
        if not product.min_amount_kopecks <= amount <= product.max_amount_kopecks:
            raise ValueError('Сумма выходит за границы продукта')
        if not product.min_term_months <= term <= product.max_term_months:
            raise ValueError('Срок выходит за границы продукта')
        months = period_months(_snapshot_date(application['period_start'], 'period_start'),
                               _snapshot_date(application['period_end'], 'period_end'), submitted_at)
        revenue_total = _integer(application['revenue_kopecks'], 'revenue_kopecks')
        expenses_total = _integer(application['operating_expenses_kopecks'], 'operating_expenses_kopecks')
        debt_total = _integer(application['existing_debt_payments_kopecks'], 'existing_debt_payments_kopecks')
    except KeyError as error:
        raise ValueError(f'Отсутствует обязательное поле: {error.args[0]}') from error

    with localcontext() as context:
        context.prec = 50
        revenue = Decimal(revenue_total) / months
        debt = Decimal(debt_total) / months
        # Порядок вычисления потока и K совпадает с действующим финансовым расчётом.
        flow = (Decimal(revenue_total) - Decimal(expenses_total)) / months
        monthly_payment = payment(amount, term, annual_rate_bps)
        values = dict(
            business_age_months=full_months(registered_at, submitted_at),
            monthly_revenue_rub=_finite_float(revenue / 100),
            operating_margin_ratio=_finite_float(flow / revenue) if revenue else None,
            existing_debt_to_revenue_ratio=_finite_float(debt / revenue) if revenue else None,
            coverage_ratio=_finite_float(flow / (debt + monthly_payment)),
            overdue_days=overdue_days,
            product_code=product_code,
            requested_amount_rub=_finite_float(Decimal(amount) / 100),
            term_months=term,
        )
    return FeatureVector(values=values, missing_mask={name: values[name] is None for name in FEATURE_NAMES})
