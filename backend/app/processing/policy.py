import calendar
import math
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from dataclasses import dataclass
from types import MappingProxyType

from app.processing.schemas import CalculationOutput, OfferTerms, PolicyResult
from app.products.catalog import get_product
from app.products.calculations import calculate_terms
from app.products.financial import COVERAGE, financial_gate

POLICY_VERSION = 'demo-policy-0.4'
LEGACY_POLICY_VERSIONS = frozenset(('demo-policy-0.2', 'demo-policy-v1'))


@dataclass(frozen=True)
class PolicyProfile:
    catalog_version: str
    uses_risk_assessments: bool


POLICY_PROFILES = MappingProxyType({
    'demo-policy-v1': PolicyProfile('demo-v1', False),
    'demo-policy-0.2': PolicyProfile('demo-v1', False),
    'demo-policy-0.3': PolicyProfile('demo-v1', True),
    'demo-policy-0.4': PolicyProfile('demo-v2', True),
})
SUPPORTED_POLICY_VERSIONS = frozenset(POLICY_PROFILES)


def policy_profile(policy_version: str, catalog_version: str | None = None) -> PolicyProfile:
    if policy_version not in SUPPORTED_POLICY_VERSIONS:
        raise ValueError('Неизвестная версия политики')
    profile = POLICY_PROFILES[policy_version]
    if catalog_version is not None and catalog_version != profile.catalog_version:
        raise ValueError('Версии каталога и политики несовместимы')
    return profile


def requires_model(policy_version: str, product_code: str) -> bool:
    profile = policy_profile(policy_version)
    get_product(product_code, profile.catalog_version)
    return profile.uses_risk_assessments and product_code in ('working_capital', 'equipment')


def offer_terms(product, amount: int, term: int) -> OfferTerms:
    terms = calculate_terms(product, amount, term)
    return OfferTerms(product_code=product.code, amount_kopecks=amount, term_months=term,
        monthly_payment_kopecks=terms.monthly_payment_kopecks or 0,
        total_payment_kopecks=terms.total_payment_kopecks, annual_rate_bps=terms.annual_rate_bps or 0,
        payment_terms=terms)


def full_months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day)


def period_months(start: date, end: date, submitted_at: date) -> int:
    if start.day != 1 or end.day != calendar.monthrange(end.year, end.month)[1] or start > end or end >= submitted_at.replace(day=1):
        raise ValueError('Нужен период завершённых календарных месяцев')
    return (end.year - start.year) * 12 + end.month - start.month + 1


def payment(amount: int, term: int, annual_rate_bps: int = 2400) -> int:
    with localcontext() as ctx:
        ctx.prec = 50
        rate = Decimal(annual_rate_bps) / Decimal(120000)
        factor = (1 + rate) ** term
        value = Decimal(amount) / term if not rate else Decimal(amount) * rate * factor / (factor - 1)
        return int(value.to_integral_value(rounding=ROUND_CEILING))


def covered(flow: Decimal, debt: Decimal, monthly_payment: int, months: int = 1) -> bool:
    # Сравнение сумм за период исключает погрешность деления месячных средних.
    return flow >= COVERAGE * (debt + monthly_payment * months)


def find_offer(data: dict, flow: Decimal, debt: Decimal, months: int = 1, *, catalog_version='demo-v1') -> OfferTerms | None:
    product = get_product(data['product_code'], catalog_version)
    amount, term = data['amount_kopecks'], data['term_months']
    for candidate in range(term + 1, product.max_term_months + 1):
        monthly = payment(amount, candidate, product.annual_rate_bps)
        if covered(flow, debt, monthly, months):
            return offer_terms(product, amount, candidate)
    maximum_payment = (flow / COVERAGE - debt) / months
    if maximum_payment <= 0:
        return None
    term = product.max_term_months
    rate = Decimal(product.annual_rate_bps) / Decimal(120000)
    factor = (1+rate) ** term
    maximum_amount = maximum_payment * (factor-1)/(rate*factor)
    amount = int((min(maximum_amount, Decimal(amount), Decimal(product.max_amount_kopecks)) / 100000).to_integral_value(rounding=ROUND_FLOOR))*100000
    while amount >= product.min_amount_kopecks:
        monthly = payment(amount, term, product.annual_rate_bps)
        if covered(flow, debt, monthly, months):
            return offer_terms(product, amount, term)
        amount -= 100000
    return None


def evaluate(data: dict, *, registered_at: date, submitted_at: date, overdue_days: int, liquidated: bool,
             expected_monthly_revenue_kopecks: int | None = None, policy_version: str = POLICY_VERSION,
             probability: float | None = None, catalog_version: str | None = None) -> PolicyResult:
    profile = policy_profile(policy_version, catalog_version)
    product = get_product(data['product_code'], profile.catalog_version)
    model_required = requires_model(policy_version, product.code)
    with localcontext() as ctx:
        ctx.prec = 50
        try:
            months = period_months(date.fromisoformat(data['period_start']), date.fromisoformat(data['period_end']), submitted_at)
            revenue = Decimal(data['revenue_kopecks']) / months
            expenses = Decimal(data['operating_expenses_kopecks']) / months
            debt = Decimal(data['existing_debt_payments_kopecks']) / months
        except (KeyError, TypeError, ValueError):
            return PolicyResult(outcome='needs_info', reason_code='financial_period_required', reason='Уточните период и финансовые сведения',
                                requested_fields=['period_start', 'period_end', 'revenue_kopecks', 'operating_expenses_kopecks', 'existing_debt_payments_kopecks'])
        missing_fields = [field for field in product.required_application_fields
                          if not isinstance(data.get(field), str) or not data[field].strip()]
        if missing_fields:
            return PolicyResult(outcome='needs_info', reason_code='product_fields_required',
                                reason='Уточните обязательные сведения выбранного продукта', requested_fields=missing_fields)
        if expected_monthly_revenue_kopecks is not None and revenue != expected_monthly_revenue_kopecks:
            return PolicyResult(outcome='needs_info', reason_code='revenue_mismatch', reason='Уточните выручку за указанный период: она отличается от синтетического источника', requested_fields=['revenue_kopecks'])
        flow_total = Decimal(data['revenue_kopecks']) - Decimal(data['operating_expenses_kopecks'])
        debt_total = Decimal(data['existing_debt_payments_kopecks'])
        flow = flow_total / months
        terms = calculate_terms(product, data['amount_kopecks'], data['term_months'])
        monthly = terms.monthly_payment_kopecks or 0
        gate = financial_gate(terms, data['revenue_kopecks'], data['operating_expenses_kopecks'],
                              data['existing_debt_payments_kopecks'], period_months=months)
        calculation = CalculationOutput(months=months, monthly_revenue_kopecks=str(revenue), monthly_operating_expenses_kopecks=str(expenses),
                                        monthly_debt_kopecks=str(debt), available_flow_kopecks=str(flow), monthly_payment_kopecks=monthly,
                                        coverage_ratio=gate.coverage_ratio, policy_version=policy_version,
                                        payment_terms=terms, financial_gate=gate)
        def result(outcome, code, reason, offer=None):
            return PolicyResult(outcome=outcome, reason_code=code, reason=reason, calculation=calculation, offer=offer)
        if liquidated:
            return result('rejected', 'company_liquidated', 'Синтетический реестр подтверждает ликвидацию компании')
        if overdue_days >= 90:
            return result('rejected', 'overdue_90_plus', 'Текущая просрочка по демонстрационной проверке БКИ составляет 90 дней или более')
        if profile.uses_risk_assessments and not model_required:
            return result('manual_review', 'unsupported_product', 'Модель риска для этого продукта пока не применяется. Заявку рассматривает сотрудник')
        if model_required and probability is None:
            return result('manual_review', 'risk_required', 'Для решения требуется оценка риска')
        if model_required and (type(probability) not in (float,int)
                or not math.isfinite(probability) or not 0<=probability<=1):
            raise ValueError('Нужна конечная вероятность от нуля до единицы')
        if full_months(registered_at, submitted_at) < 6:
            return result('manual_review', 'short_business_history', 'Компания работает менее 6 полных месяцев; требуется рассмотрение сотрудника')
        if overdue_days > 0:
            return result('manual_review', 'current_overdue', 'Есть текущая просрочка; требуется рассмотрение сотрудника')
        if flow <= 0:
            return result('manual_review', 'nonpositive_flow', 'Доход после операционных расходов недостаточен; требуется рассмотрение сотрудника')
        if model_required and probability >= .10:
            return result('manual_review', 'risk_review_required', 'Оценка риска требует рассмотрения сотрудником')
        if covered(flow_total, debt_total, monthly, months):
            return result('approved', 'coverage_sufficient', 'Запрошенные условия соответствуют демонстрационным правилам покрытия платежей')
        offer = find_offer(data, flow_total, debt_total, months, catalog_version=profile.catalog_version)
        if offer:
            return result('counteroffer', 'alternative_terms', 'Предложены условия с допустимой нагрузкой; увеличение срока может увеличить общую сумму платежей', offer)
        return result('manual_review', 'no_affordable_terms', 'Допустимые условия автоматически не найдены; требуется рассмотрение сотрудника')
