"""Общий финансовый допуск для ручного решения и предварительного подбора."""
from decimal import Decimal, localcontext

from pydantic import BaseModel, ConfigDict

from app.products.schemas import PaymentTerms

COVERAGE = Decimal('1.30')


class FinancialGate(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason_code: str
    coverage_ratio: str | None = None
    guarantee_fee_affordable: bool | None = None
    guarantee_liability_within_limit: bool | None = None
    available_after_debt_kopecks: str
    guarantee_liability_limit_kopecks: str | None = None


def financial_gate(terms: PaymentTerms, revenue_kopecks: Decimal | int,
                   operating_expenses_kopecks: Decimal | int,
                   debt_payments_kopecks: Decimal | int, *, period_months: int = 1) -> FinancialGate:
    """Принимает суммы за указанный период; месячные значения задаются с period_months=1."""
    if type(period_months) is not int or period_months < 1:
        raise ValueError('Нужно положительное целое число месяцев')
    with localcontext() as context:
        context.prec = 50
        revenue, expenses, debt = map(Decimal, (revenue_kopecks, operating_expenses_kopecks, debt_payments_kopecks))
        if any(not value.is_finite() or value < 0 for value in (revenue, expenses, debt)):
            raise ValueError('Нужны конечные неотрицательные финансовые показатели')
        flow = revenue - expenses
        available_total = max(flow - debt, Decimal(0))
        available = available_total / period_months
        if terms.payment_kind == 'guarantee':
            limit = Decimal(6) * revenue / period_months
            fee_ok = terms.upfront_fee_kopecks * period_months <= available_total
            liability_ok = terms.contingent_liability_kopecks * period_months <= Decimal(6) * revenue
            return FinancialGate(allowed=fee_ok and liability_ok,
                reason_code='financial_gate_passed' if fee_ok and liability_ok else
                    'guarantee_fee_unaffordable' if not fee_ok else 'guarantee_liability_exceeded',
                guarantee_fee_affordable=fee_ok, guarantee_liability_within_limit=liability_ok,
                available_after_debt_kopecks=str(available), guarantee_liability_limit_kopecks=str(limit))
        if terms.assessment_monthly_burden_kopecks is None:
            raise ValueError('Не задана расчётная нагрузка продукта')
        burden = debt + terms.assessment_monthly_burden_kopecks * period_months
        allowed = flow >= COVERAGE * burden
        return FinancialGate(allowed=allowed,
            reason_code='financial_gate_passed' if allowed else 'coverage_insufficient',
            coverage_ratio=str(flow / burden) if burden else None,
            available_after_debt_kopecks=str(available))
