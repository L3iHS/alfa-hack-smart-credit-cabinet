"""Сбор контекста компании и параметров заявки для правил."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.demo.profiles import recommendation_profile
from app.processing.policy import full_months, period_months
from app.recommendations.models import RecommendationContext
from app.recommendations.schemas import RecommendationRequest

if TYPE_CHECKING:
    from app.companies.models import Company


def _rubles(kopecks: int | None) -> Decimal | None:
    return None if kopecks is None else Decimal(kopecks) / 100


def _financial_values(request: RecommendationRequest) -> dict[str, Any]:
    if request.revenue_total_kopecks is None:
        return {
            'monthly_revenue': None,
            'annual_revenue': None,
            'avg_monthly_turnover': None,
            'net_profit': None,
            'existing_debt_payments_monthly': None,
            'period_months': None,
        }
    months = (period_months(request.period_start, request.period_end, date.today())
              if request.period_start is not None and request.period_end is not None else None)
    if months is None:
        months = request.period_months or 1
    monthly_revenue = _rubles(request.revenue_total_kopecks) / months
    expenses = _rubles(request.expenses_total_kopecks)
    debt = _rubles(request.existing_debt_payments_kopecks)
    monthly_expenses = expenses / months if expenses is not None else None
    monthly_debt = debt / months if debt is not None else None
    return {
        'monthly_revenue': monthly_revenue,
        'annual_revenue': monthly_revenue * 12,
        'avg_monthly_turnover': monthly_revenue,
        'net_profit': (monthly_revenue - monthly_expenses
                       if monthly_expenses is not None else None),
        'existing_debt_payments_monthly': monthly_debt,
        'period_months': months,
    }


def _collateral_values(request: RecommendationRequest) -> tuple[bool, str]:
    kind = request.collateral_type
    has_collateral = request.has_collateral
    if has_collateral is None and kind is not None:
        has_collateral = kind != 'none'
    if has_collateral is None:
        has_collateral = False
    if kind is None:
        kind = 'none'
    return has_collateral, kind


def build_context(request: RecommendationRequest, company: Company | None,
                  *, as_of_date: date | None = None,
                  profile: dict | None = None) -> RecommendationContext:
    """Объединяет данные кабинета, мок-источников и параметры заявки."""
    as_of = as_of_date or date.today()
    inn = company.inn if company is not None else None
    data = profile if profile is not None else recommendation_profile(inn or '')
    business_age = full_months(company.registered_at, as_of) if company is not None else None
    has_collateral, collateral_type = _collateral_values(request)
    financials = _financial_values(request)
    values = {
        'client_type': data.get('client_type'),
        'business_age_months': business_age,
        'egrul_status': data.get('egrul_status'),
        'okved': data.get('okved'),
        'tax_regime': data.get('tax_regime'),
        'mass_address_flag': data.get('mass_address_flag'),
        'director_disqualified_flag': data.get('director_disqualified_flag'),
        'credit_history_score': data.get('credit_history_score'),
        'overdue_days': data.get('overdue_days'),
        'max_overdue_days': data.get('max_overdue_days', data.get('overdue_days')),
        'amount': Decimal(request.amount_kopecks) / 100,
        'amount_kopecks': request.amount_kopecks,
        'term_months': request.term_months,
        'term_days': request.term_months * 30 if request.term_months is not None else None,
        'has_collateral': has_collateral,
        'collateral_type': collateral_type,
        'supplier_invoice_attached': request.supplier_invoice_attached,
        'down_payment_pct': request.down_payment_pct,
        'business_plan_attached': request.business_plan_attached,
        'tender_number': request.tender_number,
        'inn': inn,
        'company_name': company.name if company is not None else None,
    }
    values.update(financials)
    return RecommendationContext(values)
