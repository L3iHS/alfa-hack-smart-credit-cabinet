"""Предварительный подбор по единому каталогу и общему финансовому допуску."""

import uuid
from decimal import Decimal

from app.products.calculations import calculate_terms
from app.products.catalog import CATALOG_VERSION, get_product
from app.products.financial import financial_gate
from app.products.schemas import ProductOutput
from app.recommendations.config import RecommendationConfig, load_config
from app.recommendations.context import build_context
from app.recommendations.models import RecommendationContext
from app.recommendations.schemas import (
    RecommendationAction, RecommendationItem, RecommendationRequest, RecommendationResponse,
)

AMOUNT_STEP_KOPECKS = 100_000
MISSING_LABELS = {
    'revenue_total_kopecks': 'Укажите выручку за финансовый период',
    'expenses_total_kopecks': 'Укажите операционные расходы за тот же период',
    'existing_debt_payments_kopecks': 'Укажите платежи по действующим кредитам за тот же период; если их нет, введите 0',
    'period_months': 'Выберите даты начала и конца завершённого финансового периода или укажите число завершённых месяцев',
}


def _gate(terms, context: RecommendationContext):
    return financial_gate(terms, context.get('revenue_total_kopecks'),
        context.get('expenses_total_kopecks'), context.get('existing_debt_payments_kopecks'),
        period_months=context.get('period_months'))


def _maximum_terms(product: ProductOutput, upper: int, term: int, context: RecommendationContext):
    """Сохраняет допустимую точную сумму; иначе ищет максимум на сетке за O(log N)."""
    terms = calculate_terms(product, upper, term)
    gate = _gate(terms, context)
    if gate.allowed:
        return terms, gate, False
    left = (product.min_amount_kopecks + AMOUNT_STEP_KOPECKS - 1) // AMOUNT_STEP_KOPECKS
    right = upper // AMOUNT_STEP_KOPECKS
    best = None
    while left <= right:
        middle = (left + right) // 2
        candidate = calculate_terms(product, middle * AMOUNT_STEP_KOPECKS, term)
        if _gate(candidate, context).allowed:
            best = candidate
            left = middle + 1
        else:
            right = middle - 1
    if best is None:
        return None, gate, True
    # Повторная проверка окончательных условий не использует старую нагрузку.
    return best, _gate(best, context), True


def _sort_key(item: RecommendationItem, request: RecommendationRequest, config: RecommendationConfig):
    amount_distance = Decimal(request.amount_kopecks - item.recommended_amount_kopecks) / request.amount_kopecks
    term_distance = Decimal(abs(request.term_months - item.term_months)) / request.term_months
    distance = (amount_distance * Decimal(str(config.ranking.amount_weight))
                + term_distance * Decimal(str(config.ranking.term_weight)))
    cost_ratio = Decimal(item.payment_terms.total_cost_kopecks) / item.recommended_amount_kopecks
    return not item.purpose_match, distance, cost_ratio, item.product_code


def recommend(request: RecommendationRequest, company, *, role: str = 'client',
              as_of_date=None, source_checks: dict | None = None,
              config: RecommendationConfig | None = None) -> RecommendationResponse:
    """Подбор не вызывает модель, не читает документы и ничего не сохраняет."""
    config = config or load_config()
    purpose = config.purpose(request.purpose)
    relevant = set(purpose.primary + purpose.secondary)
    context = build_context(request, company, as_of_date=as_of_date, source_checks=source_checks)
    trace = []

    def response(status, message, items=None, missing=None, actions=None):
        return RecommendationResponse(status=status, message=message, items=items or [],
            missing_fields=missing or [], actions=actions or [], config_version=config.version,
            catalog_version=CATALOG_VERSION, trace_id=uuid.uuid4().hex,
            staff_trace=trace if role == 'staff' else None)

    stop_messages = []
    for rule in config.global_rules:
        actual = context.get(rule.field)
        passed = actual is not None and (actual == rule.value if rule.op == 'eq' else actual < rule.value)
        trace.append({'stage': 'company', 'rule_id': rule.id, 'actual': actual,
                      'expected': rule.value, 'passed': passed})
        if not passed:
            stop_messages.append(config.reasons[rule.reason_code if actual is not None else 'company_data_missing'])
    if stop_messages:
        return response('no_match', ' '.join(dict.fromkeys(stop_messages)))

    missing = [name for name in MISSING_LABELS if context.get(name) is None]
    if missing:
        return response('request_data', 'Для расчёта условий заполните финансовые сведения и период.',
            missing=missing, actions=[RecommendationAction(kind='request_field', field=name,
                                      label=MISSING_LABELS[name]) for name in missing])

    items = []
    for code in config.products:
        if code not in relevant:
            continue
        product = get_product(code, CATALOG_VERSION)
        upper = min(request.amount_kopecks, product.max_amount_kopecks)
        if upper < product.min_amount_kopecks:
            trace.append({'stage': 'catalog', 'rule_id': 'amount_below_minimum',
                          'product_code': code, 'passed': False})
            continue
        term = min(max(request.term_months, product.min_term_months), product.max_term_months)
        terms, gate, financially_adjusted = _maximum_terms(product, upper, term, context)
        trace.append({'stage': 'financial_gate', 'rule_id': gate.reason_code, 'product_code': code,
                      **gate.model_dump(mode='json')})
        if terms is None or not gate.allowed:
            continue
        reason_codes = ['purpose_match' if code in purpose.primary else 'purpose_alternative']
        if upper != request.amount_kopecks:
            reason_codes.append('catalog_amount_adjusted')
        if term != request.term_months:
            reason_codes.append('term_adjusted')
        if financially_adjusted:
            reason_codes.append('financial_amount_adjusted')
        items.append(RecommendationItem(recommendation_id=uuid.uuid4().hex, product_code=code,
            product_name=product.name, rank=0, purpose_match=code in purpose.primary,
            recommended_amount_kopecks=terms.amount_kopecks, term_months=term,
            payment_terms=terms, financial_gate=gate, reason_codes=reason_codes,
            client_reasons=[config.reasons[reason] for reason in reason_codes],
            required_application_fields=list(product.required_application_fields),
            required_document_types=list(product.required_document_types)))
    items.sort(key=lambda item: _sort_key(item, request, config))
    items = [item.model_copy(update={'rank': rank})
             for rank, item in enumerate(items[:config.ranking.show_top_n], 1)]
    if not items:
        below_all = all(request.amount_kopecks < get_product(code, CATALOG_VERSION).min_amount_kopecks
                        for code in relevant)
        return response('no_match', config.reasons['amount_below_minimum' if below_all else 'financial_no_match'],
            actions=[RecommendationAction(kind='change_amount', field='amount_kopecks',
                                          label='Измените сумму или проверьте финансовые сведения')])
    adjusted = (items[0].recommended_amount_kopecks != request.amount_kopecks or
                items[0].term_months != request.term_months)
    return response('adjusted' if adjusted else 'ok',
        'Подобраны предварительные условия. Изменения указаны в карточках; решение принимается после подачи.'
        if adjusted else 'Подобраны предварительные условия. Решение принимается после подачи заявки.',
        items=items, actions=[RecommendationAction(kind='apply_recommendation', product_code=item.product_code,
            recommendation_id=item.recommendation_id, label='Подставить в заявку') for item in items])
