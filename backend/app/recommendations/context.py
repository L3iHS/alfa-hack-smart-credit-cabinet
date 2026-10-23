"""Сбор контекста без подмены отсутствующих финансовых показателей."""

from datetime import date
from typing import TYPE_CHECKING

from app.demo.profiles import SOURCE_VERSION
from app.processing import providers
from app.processing.policy import full_months, period_months
from app.recommendations.models import RecommendationContext
from app.recommendations.schemas import RecommendationRequest

if TYPE_CHECKING:
    from app.companies.models import Company


def build_context(request: RecommendationRequest, company: 'Company | None', *,
                  as_of_date: date | None = None, source_checks: dict | None = None) -> RecommendationContext:
    """Проверяет календарь даже при неполных финансах; суммы остаются totals."""
    as_of = as_of_date or date.today()
    if source_checks is None:
        if company is None:
            source_checks = {}
        else:
            snapshot = {'company': {'inn': company.inn, 'registered_at': company.registered_at.isoformat()}}
            source_checks = {kind: providers.check(kind, snapshot, SOURCE_VERSION)
                             for kind in ('registry', 'bki')}
    registry = source_checks.get('registry', {})
    bki = source_checks.get('bki', {})
    liquidated = registry.get('liquidated')
    overdue = bki.get('overdue_days')
    # Неизвестный результат не подменяется благополучным состоянием.
    status = ('liquidated' if liquidated else 'active') if type(liquidated) is bool else None
    if type(overdue) is not int or overdue < 0:
        overdue = None
    months = (period_months(request.period_start, request.period_end, as_of)
              if request.period_start is not None else request.period_months)
    return RecommendationContext({
        'business_age_months': full_months(company.registered_at, as_of) if company else None,
        'egrul_status': status,
        'max_overdue_days': overdue,
        'revenue_total_kopecks': request.revenue_total_kopecks,
        'expenses_total_kopecks': request.expenses_total_kopecks,
        'existing_debt_payments_kopecks': request.existing_debt_payments_kopecks,
        'period_months': months,
    })
