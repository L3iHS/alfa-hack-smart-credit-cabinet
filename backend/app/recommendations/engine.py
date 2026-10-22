"""Детерминированный движок L0-L5 для подбора кредитных продуктов."""

import uuid
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Iterable

from app.processing.policy import payment
from app.recommendations.config import (
    Adjustment, Product, RecommendationConfig, Rule, RecommendationConfigError, load_config,
)
from app.recommendations.context import build_context
from app.recommendations.models import (
    FAIL_ADJUSTABLE, FAIL_HARD, MISSING_DATA, OUTCOME_ALTERNATIVE, OUTCOME_COUNTER_OFFER,
    OUTCOME_NO_MATCH, OUTCOME_OK, OUTCOME_REQUEST_DATA, PASS, Evaluation, RecommendationContext,
    RuleResult,
)
from app.recommendations.schemas import (
    RecommendationAction, RecommendationItem, RecommendationRequest, RecommendationResponse,
)

MISSING_LABELS = {
    'client_type': 'Тип клиента',
    'business_age_months': 'Дата регистрации компании',
    'egrul_status': 'Статус ЕГРЮЛ',
    'okved': 'ОКВЭД',
    'tax_regime': 'Налоговый режим',
    'credit_history_score': 'Данные кредитной истории',
    'overdue_days': 'Данные о просрочках',
    'max_overdue_days': 'Данные о просрочках',
    'annual_revenue': 'Выручка за период',
    'avg_monthly_turnover': 'Среднемесячная выручка',
    'net_profit': 'Финансовый результат',
    'amount': 'Сумма кредита',
    'term_months': 'Срок кредита',
    'term_days': 'Срок кредита',
    'has_collateral': 'Наличие залога',
    'collateral_type': 'Тип залога',
    'supplier_invoice_attached': 'Счёт поставщика',
    'down_payment_pct': 'Первоначальный взнос',
    'business_plan_attached': 'Бизнес-план',
    'tender_number': 'Номер тендера',
}
MISSING_ORDER = tuple(MISSING_LABELS)


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op == 'exists':
        return actual is not None and actual != ''
    if op == 'eq':
        return actual == expected
    if op == 'ne':
        return actual != expected
    if op == 'in':
        return actual in expected
    if op == 'not_in':
        return actual not in expected
    if op == 'not_prefix':
        return isinstance(actual, str) and not any(actual.startswith(str(item)) for item in expected)
    if op == 'between':
        left = _number(actual)
        low, high = _number(expected[0]), _number(expected[1])
        return left is not None and low is not None and high is not None and low <= left <= high
    left, right = _number(actual), _number(expected)
    if left is None or right is None:
        return False
    if op == 'gt':
        return left > right
    if op == 'gte':
        return left >= right
    if op == 'lt':
        return left < right
    if op == 'lte':
        return left <= right
    raise RecommendationConfigError(f'Неизвестный оператор: {op}')


def _when_matches(rule: Rule, context: RecommendationContext) -> bool:
    return all(_compare(context.get(field), 'eq', value) for field, value in rule.when)


def _rate_pct(product: Product, context: RecommendationContext) -> float:
    pricing = product.pricing
    base = float(pricing.get('base_rate_pct') or 0)
    if context.get('has_collateral'):
        base -= float(pricing.get('rate_discount_if_collateral_pct') or 0)
    return max(0.0, base)


def _monthly_payment_kopecks(product: Product, context: RecommendationContext) -> int | None:
    amount = context.get('amount_kopecks')
    term = context.get('term_months')
    if not amount or not term:
        return None
    rate = _rate_pct(product, context)
    if rate:
        return payment(amount, term, int(round(rate * 100)))
    commission = product.pricing.get('commission_year_pct')
    if commission:
        monthly = Decimal(amount) * Decimal(str(commission)) / Decimal(1200)
        return int(monthly.to_integral_value(rounding=ROUND_FLOOR))
    return None


def _actual(field: str, context: RecommendationContext, product: Product | None) -> Any:
    if field not in ('amount_to_revenue', 'monthly_payment', 'payment_to_turnover', 'dti'):
        return context.get(field)
    if product is None:
        return None
    amount = context.get('amount')
    revenue = context.get('annual_revenue')
    turnover = context.get('avg_monthly_turnover')
    debt = context.get('existing_debt_payments_monthly')
    monthly = _monthly_payment_kopecks(product, context)
    monthly_rub = Decimal(monthly) / 100 if monthly is not None else None
    if field == 'amount_to_revenue':
        return amount / revenue if amount is not None and revenue else None
    if field == 'monthly_payment':
        return monthly_rub
    if field == 'payment_to_turnover':
        return monthly_rub / turnover if monthly_rub is not None and turnover else None
    if field == 'dti':
        if monthly_rub is None or debt is None or not turnover:
            return None
        return (monthly_rub + debt) / turnover
    return None


def _run_rules(rules: Iterable[Rule], context: RecommendationContext,
               product: Product | None) -> list[RuleResult]:
    results = []
    for rule in rules:
        if not _when_matches(rule, context):
            continue
        actual = _actual(rule.field, context, product)
        if actual is None:
            results.append(RuleResult(rule, MISSING_DATA, None, rule.value))
        elif _compare(actual, rule.op, rule.value):
            results.append(RuleResult(rule, PASS, actual, rule.value))
        else:
            status = FAIL_ADJUSTABLE if rule.on_fail == 'adjust' else (
                MISSING_DATA if rule.on_fail == 'request_data' else FAIL_HARD)
            results.append(RuleResult(rule, status, actual, rule.value))
    return results


def _all_rules(product: Product) -> tuple[Rule, ...]:
    return (*product.eligibility, *product.needs, *product.financial_limits)


def _adjustment_for(product: Product, rule_id: str) -> Adjustment | None:
    return next((item for item in product.adjustments if item.when == rule_id), None)


def _round_amount(value: Decimal, step_kopecks: int) -> Decimal:
    step = Decimal(step_kopecks) / 100
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _apply_adjustments(product: Product, context: RecommendationContext,
                       results: list[RuleResult], step_kopecks: int) -> tuple[RecommendationContext, bool]:
    amount = context.get('amount')
    term_months = context.get('term_months')
    term_days = context.get('term_days')
    changed = False
    for result in results:
        if result.status != FAIL_ADJUSTABLE:
            continue
        adjustment = _adjustment_for(product, result.rule.id)
        if adjustment is None or adjustment.action not in ('cap_amount', 'clamp_term'):
            continue
        expected = result.rule.value
        if adjustment.action == 'cap_amount':
            target = None
            limit = _number(expected[1] if result.rule.op == 'between' else expected)
            if result.rule.field == 'amount':
                target = limit
            elif result.rule.field == 'amount_to_revenue':
                revenue = context.get('annual_revenue')
                target = revenue * limit if revenue is not None and limit is not None else None
            elif result.rule.field in ('payment_to_turnover', 'dti'):
                turnover = context.get('avg_monthly_turnover')
                monthly = _monthly_payment_kopecks(product, context)
                current = Decimal(monthly) / 100 if monthly is not None else None
                if (turnover is not None and current and current > 0 and limit is not None
                        and amount is not None):
                    available = turnover * limit
                    if result.rule.field == 'dti':
                        debt = context.get('existing_debt_payments_monthly') or Decimal(0)
                        available -= debt
                    target = amount * available / current
            if target is not None and amount is not None and target < amount:
                rounded = _round_amount(max(Decimal(1), target), step_kopecks)
                amount = rounded if rounded > 0 else Decimal(1)
                changed = True
        elif adjustment.action == 'clamp_term':
            if result.rule.field == 'term_days':
                target_days = _number(expected[1] if result.rule.op == 'between' else expected)
                if target_days is not None and (term_days is None or target_days < term_days):
                    term_days = int(target_days)
                    term_months = max(1, term_days // 30)
                    changed = True
            elif result.rule.field == 'term_months':
                target_months = _number(expected[1] if result.rule.op == 'between' else expected)
                if target_months is not None and (term_months is None or target_months < term_months):
                    term_months = int(target_months)
                    term_days = term_months * 30
                    changed = True
    if changed:
        return context.with_terms(amount_rub=amount, term_months=term_months, term_days=term_days), True
    return context, False


def _evaluate(product: Product, context: RecommendationContext, config: RecommendationConfig,
              requested: RecommendationRequest) -> Evaluation:
    amount = context.get('amount')
    term = context.get('term_months')
    if amount is None or term is None:
        raise RecommendationConfigError('В контексте нет суммы или срока')
    counter = False
    results: list[RuleResult] = []
    for _ in range(6):
        results = _run_rules(_all_rules(product), context, product)
        hard = [result for result in results if result.status == FAIL_HARD]
        if hard:
            return Evaluation(product, tuple(results), OUTCOME_NO_MATCH, context.get('amount'),
                              context.get('term_months'), context.get('term_days'),
                              _missing_fields(results), (), ())
        missing = [result for result in results if result.status == MISSING_DATA]
        if missing:
            if any(result.status == FAIL_ADJUSTABLE for result in results):
                _, changed = _apply_adjustments(
                    product, context, results, config.ranking.rounding_kopecks,
                )
                if not changed:
                    return Evaluation(
                        product, tuple(results), OUTCOME_NO_MATCH, context.get('amount'),
                        context.get('term_months'), context.get('term_days'),
                        _missing_fields(results), (), (),
                    )
            return Evaluation(product, tuple(results), OUTCOME_REQUEST_DATA, context.get('amount'),
                              context.get('term_months'), context.get('term_days'),
                              _missing_fields(results), (), ())
        if not any(result.status == FAIL_ADJUSTABLE for result in results):
            break
        context, changed = _apply_adjustments(product, context, results, config.ranking.rounding_kopecks)
        if not changed:
            return Evaluation(product, tuple(results), OUTCOME_NO_MATCH, context.get('amount'),
                              context.get('term_months'), context.get('term_days'),
                              _missing_fields(results), (), ())
        counter = True
    else:
        return Evaluation(product, tuple(results), OUTCOME_NO_MATCH, context.get('amount'),
                          context.get('term_months'), context.get('term_days'),
                          _missing_fields(results), (), ())

    purpose_match = requested.purpose in product.purposes
    if requested.purpose not in (*product.purposes, *product.alt_purposes):
        return Evaluation(product, tuple(results), OUTCOME_NO_MATCH, context.get('amount'),
                          context.get('term_months'), context.get('term_days'), (), (), ())
    if counter or context.get('amount') != amount or context.get('term_months') != term:
        outcome = OUTCOME_COUNTER_OFFER
    else:
        outcome = OUTCOME_OK
    if not purpose_match:
        outcome = OUTCOME_ALTERNATIVE
    return Evaluation(product, tuple(results), outcome, context.get('amount'),
                      context.get('term_months'), context.get('term_days'), (), (), ())


def _missing_fields(results: Iterable[RuleResult]) -> tuple[str, ...]:
    fields = {result.rule.field for result in results if result.status == MISSING_DATA}
    return tuple(field for field in MISSING_ORDER if field in fields) or tuple(sorted(fields))


def _missing_labels(evaluation: Evaluation) -> list[str]:
    return [MISSING_LABELS.get(field, field) for field in evaluation.missing_fields]


def _cost_values(product: Product, context: RecommendationContext) -> tuple[float | None, int | None, int | None]:
    monthly = _monthly_payment_kopecks(product, context)
    rate = _rate_pct(product, context)
    commission = product.pricing.get('commission_year_pct')
    if rate:
        effective = rate
    elif commission is not None:
        effective = float(commission)
    else:
        effective = float(product.pricing.get('effective_annual_cost_pct') or 0)
    term = context.get('term_months')
    total = monthly * term if monthly is not None and term else None
    return effective, monthly, total


def _approval_likelihood(context: RecommendationContext, evaluation: Evaluation) -> float:
    score = 0.45
    history = context.get('credit_history_score')
    if history is not None:
        score += max(-0.20, min(0.25, (float(history) - 550) / 400))
    overdue = context.get('max_overdue_days')
    if overdue is not None:
        score += 0.10 if overdue == 0 else -0.25
    if context.get('mass_address_flag') or context.get('director_disqualified_flag'):
        score -= 0.35
    if context.get('has_collateral'):
        score += 0.05
    if evaluation.adjustable:
        score -= 0.05
    return max(0.05, min(0.95, score))


def _purpose_strength(product: Product, purpose: str, config: RecommendationConfig) -> float:
    mapping = config.purpose(purpose)
    if product.id in mapping.primary:
        return 1.0
    if product.id in mapping.secondary:
        return 0.55
    return 0.0


def _score(product: Product, context: RecommendationContext, evaluation: Evaluation,
           config: RecommendationConfig, requested: RecommendationRequest) -> int:
    purpose = _purpose_strength(product, requested.purpose, config)
    approved = float(context.get('amount') or 0)
    requested_amount = float(Decimal(requested.amount_kopecks) / 100) or 1.0
    amount_fit = 1.0 if abs(approved - requested_amount) < 1 else max(0.5, min(1.0, approved / requested_amount))
    effective, _, _ = _cost_values(product, context)
    cost = max(0.0, min(1.0, 1.0 - float(effective or 0) / config.ranking.cost_cap))
    likelihood = _approval_likelihood(context, evaluation)
    hours = int(product.pricing.get('approval_hours') or 0)
    speed = config.ranking.fast_score if hours <= config.ranking.high_urgency_threshold_hours else config.ranking.normal_score
    weights = config.ranking.urgency_overrides.get(requested.urgency, config.ranking.default_weights)
    value = (weights['purpose_match'] * purpose + weights['amount_term_fit'] * amount_fit
             + weights['cost_score'] * cost + weights['approval_likelihood'] * likelihood
             + weights['speed_score'] * speed)
    if product.cabinet_product_code is not None:
        value += config.ranking.availability_bonus
    return max(0, min(100, int(round(value * 100))))


def _item(product: Product, context: RecommendationContext, evaluation: Evaluation,
          config: RecommendationConfig, requested: RecommendationRequest, rank: int,
          reasons: list[str]) -> RecommendationItem:
    effective, monthly, total = _cost_values(product, context)
    rate = _rate_pct(product, context)
    commission = product.pricing.get('commission_year_pct')
    likelihood = _approval_likelihood(context, evaluation)
    amount = int((context.get('amount') or 0) * 100)
    term = int(context.get('term_months') or requested.term_months)
    changed = amount != requested.amount_kopecks or term != requested.term_months
    available = product.cabinet_product_code is not None
    hint = None
    if changed:
        hint = 'Проверьте изменённые сумму и срок — банк готов рассмотреть такую заявку.'
    elif available:
        hint = 'Можно перейти к оформлению заявки в кабинете.'
    else:
        hint = 'Оформление этого продукта в кабинете пока не подключено.'
    return RecommendationItem(
        offer_id=f'{product.id}-{amount}-{term}',
        product_id=product.id,
        product_name=product.name,
        product_type=product.type,
        cabinet_product_code=product.cabinet_product_code,
        is_available_in_cabinet=available,
        rank=rank,
        score=_score(product, context, evaluation, config, requested),
        purpose_match=_purpose_strength(product, requested.purpose, config) == 1.0,
        approved_amount_kopecks=amount,
        term_months=term,
        term_days=context.get('term_days'),
        base_rate_pct=rate or None,
        commission_year_pct=float(commission) if commission is not None else None,
        effective_annual_cost_pct=float(effective or 0),
        monthly_payment_kopecks=monthly,
        total_cost_kopecks=total,
        approval_likelihood=int(round(likelihood * 100)),
        approval_time_hours=int(product.pricing.get('approval_hours') or 0),
        client_reasons=reasons,
        missing_data=_missing_labels(evaluation),
        next_action=hint,
    )


def _reasons(evaluation: Evaluation, config: RecommendationConfig,
            requested: RecommendationRequest, product: Product) -> list[str]:
    codes = []
    if _purpose_strength(product, requested.purpose, config) == 1.0:
        codes.append('purpose_match')
    for result in evaluation.results:
        if result.status in (FAIL_ADJUSTABLE, MISSING_DATA):
            codes.append(result.rule.reason_code)
    seen = set()
    result = []
    for code in codes:
        reason = config.reasons.get(code)
        if reason is None or code in seen:
            continue
        seen.add(code)
        result.append(reason.client)
        if len(result) == 3:
            break
    return result


def _trace(evaluations: list[Evaluation], global_results: list[RuleResult]) -> list[dict]:
    trace = []
    for result in global_results:
        trace.append({
            'product_id': None,
            'rule_id': result.rule.id,
            'field': result.rule.field,
            'status': result.status,
            'actual': _json_value(result.actual),
            'expected': _json_value(result.expected),
        })
    for evaluation in evaluations:
        for result in evaluation.results:
            trace.append({
                'product_id': evaluation.product.id,
                'rule_id': result.rule.id,
                'field': result.rule.field,
                'status': result.status,
                'actual': _json_value(result.actual),
                'expected': _json_value(result.expected),
            })
    return trace


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _actions(items: list[RecommendationItem], evaluations: list[Evaluation],
             requested: RecommendationRequest) -> list[RecommendationAction]:
    actions = []
    seen = set()

    def add(action: RecommendationAction):
        key = (action.kind, action.code, action.product_id)
        if key not in seen:
            seen.add(key)
            actions.append(action)

    if items:
        for item in items:
            if item.is_available_in_cabinet:
                add(RecommendationAction(kind='open_cabinet', code='open_cabinet',
                                         label='Перейти к оформлению заявки', product_id=item.product_id))
            if item.approved_amount_kopecks != requested.amount_kopecks:
                add(RecommendationAction(kind='change_amount', code='apply_approved_amount',
                                         label='Согласиться с суммой', product_id=item.product_id))
            if item.term_months != requested.term_months:
                add(RecommendationAction(kind='change_term', code='apply_approved_term',
                                         label='Согласиться со сроком', product_id=item.product_id))
        return actions
    missing = {field for evaluation in evaluations for field in evaluation.missing_fields}
    if 'collateral_type' in missing or 'has_collateral' in missing:
        add(RecommendationAction(kind='change_collateral', code='add_collateral',
                                 label='Указать залог'))
    if missing & {'supplier_invoice_attached', 'business_plan_attached', 'tender_number'}:
        add(RecommendationAction(kind='attach_document', code='attach_documents',
                                 label='Приложить документы'))
    if missing & {'amount', 'annual_revenue', 'avg_monthly_turnover', 'net_profit'}:
        add(RecommendationAction(kind='change_amount', code='clarify_finance',
                                 label='Уточнить сумму и финансовые данные'))
    if 'term_months' in missing or 'term_days' in missing:
        add(RecommendationAction(kind='change_term', code='clarify_term', label='Уточнить срок'))
    return actions


def _message(status: str, items: list[RecommendationItem]) -> str:
    if status == 'ok':
        return 'Подобраны продукты, которые подходят под параметры заявки.'
    if status == 'counter_offer':
        return 'Для части продуктов банк готов предложить скорректированные сумму или срок.'
    if status == 'request_data':
        return 'Для точного подбора не хватает данных о компании или заявке.'
    if status == 'alternative_product':
        return 'По выбранной цели есть продукты с отличающимися условиями.'
    return 'Подходящих продуктов не найдено. Можно изменить цель, сумму или срок.'


def recommend(request: RecommendationRequest, company, *, config: RecommendationConfig | None = None,
              role: str = 'client', as_of_date=None, profile: dict | None = None) -> RecommendationResponse:
    config = config or load_config()
    context = build_context(request, company, as_of_date=as_of_date, profile=profile)
    global_results = _run_rules(config.global_rules, context, None)
    global_missing = [result for result in global_results if result.status == MISSING_DATA]
    global_failed = [result for result in global_results if result.status == FAIL_HARD]
    if global_failed:
        return RecommendationResponse(
            status='no_match', message='Подбор недоступен: компания не соответствует требованиям банка.',
            items=[], alternatives=[], actions=[], config_version=config.version,
            trace_id=uuid.uuid4().hex,
            staff_trace=_trace([], global_results) if role == 'staff' else None,
        )
    if global_missing:
        evaluations = [Evaluation(product, tuple(), OUTCOME_REQUEST_DATA, context.get('amount'),
                                  context.get('term_months'), context.get('term_days'),
                                  _missing_fields(global_missing), (), ())
                       for product in config.products]
        return RecommendationResponse(
            status='request_data', message=_message('request_data', []),
            items=[], alternatives=[], actions=_actions([], evaluations, request),
            config_version=config.version, trace_id=uuid.uuid4().hex,
            staff_trace=_trace(evaluations, global_results) if role == 'staff' else None,
        )

    evaluations = [_evaluate(product, context, config, request) for product in config.products]
    candidates = [evaluation for evaluation in evaluations
                  if evaluation.outcome in (OUTCOME_OK, OUTCOME_COUNTER_OFFER, OUTCOME_ALTERNATIVE)]
    ranked = []
    for evaluation in candidates:
        adjusted_context = context.with_terms(amount_rub=evaluation.amount_rub,
                                              term_months=evaluation.term_months,
                                              term_days=evaluation.term_days)
        item = _item(evaluation.product, adjusted_context, evaluation, config, request, 0,
                     _reasons(evaluation, config, request, evaluation.product))
        ranked.append((item.score, item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].product_name))
    top_n = config.ranking.show_top_n
    items = []
    for index, (_, item) in enumerate(ranked[:top_n], 1):
        items.append(item.model_copy(update={'rank': index}))
    alternatives = [item.model_copy(update={'rank': top_n + index})
                    for index, (_, item) in enumerate(ranked[top_n:top_n + 2], 1)]
    if items:
        top = items[0]
        status = 'counter_offer' if (
            top.approved_amount_kopecks != request.amount_kopecks
            or top.term_months != request.term_months) else 'ok'
    elif any(evaluation.outcome == OUTCOME_REQUEST_DATA for evaluation in evaluations):
        status = 'request_data'
    elif any(evaluation.outcome == OUTCOME_ALTERNATIVE for evaluation in evaluations):
        status = 'alternative_product'
    else:
        status = 'no_match'
    return RecommendationResponse(
        status=status, message=_message(status, items), items=items, alternatives=alternatives,
        actions=_actions(items, evaluations, request), config_version=config.version,
        trace_id=uuid.uuid4().hex,
        staff_trace=_trace(evaluations, global_results) if role == 'staff' else None,
    )
