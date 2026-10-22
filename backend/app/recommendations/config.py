"""Загрузка и проверка конфигурации правил подбора продуктов."""

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / 'config' / 'rules'
RULE_FIELDS = frozenset((
    'client_type', 'business_age_months', 'egrul_status', 'okved', 'tax_regime',
    'mass_address_flag', 'director_disqualified_flag', 'max_overdue_days', 'overdue_days',
    'credit_history_score', 'annual_revenue', 'avg_monthly_turnover', 'net_profit',
    'amount', 'term_months', 'term_days', 'has_collateral', 'collateral_type',
    'amount_to_revenue', 'monthly_payment', 'payment_to_turnover', 'dti',
    'supplier_invoice_attached', 'down_payment_pct', 'business_plan_attached', 'tender_number',
))
OPERATORS = frozenset(('eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between', 'in', 'not_in',
                       'not_prefix', 'exists'))
ON_FAIL = frozenset(('reject_product', 'adjust', 'request_data'))
ACTIONS = frozenset(('cap_amount', 'clamp_term', 'suggest_product', 'offer_two_options',
                     'request_change'))
WEIGHT_NAMES = ('purpose_match', 'amount_term_fit', 'cost_score', 'approval_likelihood', 'speed_score')
_FILE_NAMES = ('products.yaml', 'purpose_map.yaml', 'ranking.yaml', 'reasons.yaml', 'stop_factors.yaml')


class RecommendationConfigError(ValueError):
    """Конфигурация не соответствует контракту движка."""


@dataclass(frozen=True)
class Rule:
    id: str
    field: str
    op: str
    value: Any
    on_fail: str
    reason_code: str
    when: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class Adjustment:
    when: str
    action: str
    product_id: str | None = None
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    type: str
    purposes: tuple[str, ...]
    alt_purposes: tuple[str, ...]
    cabinet_product_code: str | None
    eligibility: tuple[Rule, ...]
    needs: tuple[Rule, ...]
    financial_limits: tuple[Rule, ...]
    pricing: Mapping[str, Any]
    adjustments: tuple[Adjustment, ...]


@dataclass(frozen=True)
class Purpose:
    code: str
    label: str
    primary: tuple[str, ...]
    secondary: tuple[str, ...]


@dataclass(frozen=True)
class Reason:
    client: str
    staff: str
    hint: str


@dataclass(frozen=True)
class Ranking:
    default_weights: Mapping[str, float]
    urgency_overrides: Mapping[str, Mapping[str, float]]
    show_top_n: int
    close_score_delta: float
    availability_bonus: float
    cost_cap: float
    rounding_kopecks: int
    high_urgency_threshold_hours: int
    fast_score: float
    normal_score: float


@dataclass(frozen=True)
class RecommendationConfig:
    version: str
    fingerprint: str
    products: tuple[Product, ...]
    purposes: Mapping[str, Purpose]
    ranking: Ranking
    reasons: Mapping[str, Reason]
    global_rules: tuple[Rule, ...]
    excluded_okved_prefixes: tuple[str, ...]

    def product(self, product_id: str) -> Product:
        for product in self.products:
            if product.id == product_id:
                return product
        raise RecommendationConfigError(f'Неизвестный продукт: {product_id}')

    def purpose(self, code: str) -> Purpose:
        try:
            return self.purposes[code]
        except KeyError as error:
            raise RecommendationConfigError(f'Неизвестная цель: {code}') from error


def _read_yaml(path: Path) -> dict:
    try:
        value = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RecommendationConfigError(f'{path.name}: не удалось прочитать YAML') from error
    if not isinstance(value, dict):
        raise RecommendationConfigError(f'{path.name}: нужен объект YAML')
    return value


def _text(value, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RecommendationConfigError(f'{name}: нужна непустая строка')
    return value


def _items(value, name: str) -> list:
    if not isinstance(value, list):
        raise RecommendationConfigError(f'{name}: нужен список')
    return value


def _rule(raw, source: str, reasons: Mapping[str, Reason]) -> Rule:
    if not isinstance(raw, dict):
        raise RecommendationConfigError(f'{source}: правило должно быть объектом')
    rule_id = _text(raw.get('id'), f'{source}.id')
    field = _text(raw.get('field'), f'{rule_id}.field')
    op = _text(raw.get('op'), f'{rule_id}.op')
    on_fail = _text(raw.get('on_fail'), f'{rule_id}.on_fail')
    reason_code = _text(raw.get('reason_code'), f'{rule_id}.reason_code')
    if field not in RULE_FIELDS:
        raise RecommendationConfigError(f'{rule_id}: неизвестное поле {field}')
    if op not in OPERATORS:
        raise RecommendationConfigError(f'{rule_id}: неизвестный оператор {op}')
    if on_fail not in ON_FAIL:
        raise RecommendationConfigError(f'{rule_id}: неизвестное действие {on_fail}')
    if reason_code not in reasons:
        raise RecommendationConfigError(f'{rule_id}: неизвестный reason_code {reason_code}')
    if op in ('between', 'in', 'not_in', 'not_prefix'):
        value = _items(raw.get('value'), f'{rule_id}.value')
        if op == 'between' and len(value) != 2:
            raise RecommendationConfigError(f'{rule_id}: between требует два значения')
        if op == 'not_prefix' and not all(isinstance(item, str) for item in value):
            raise RecommendationConfigError(f'{rule_id}: not_prefix требует строки')
    elif op == 'exists':
        value = True
    else:
        value = raw.get('value')
        if value is None:
            raise RecommendationConfigError(f'{rule_id}: отсутствует value')
    when = raw.get('when') or {}
    if not isinstance(when, dict):
        raise RecommendationConfigError(f'{rule_id}: when должен быть объектом')
    return Rule(rule_id, field, op, value, on_fail, reason_code,
                tuple(sorted(when.items())))


def _adjustment(raw, source: str, rules: set[str], product_ids: set[str]) -> Adjustment:
    if not isinstance(raw, dict):
        raise RecommendationConfigError(f'{source}: adjustment должен быть объектом')
    when = _text(raw.get('when'), f'{source}.when')
    action = _text(raw.get('action'), f'{source}.action')
    if when not in rules:
        raise RecommendationConfigError(f'{source}: неизвестное правило {when}')
    if action not in ACTIONS:
        raise RecommendationConfigError(f'{source}: неизвестное действие {action}')
    product_id = raw.get('product_id')
    if product_id is not None and product_id not in product_ids:
        raise RecommendationConfigError(f'{source}: неизвестный продукт {product_id}')
    options = raw.get('options') or []
    if not isinstance(options, list) or not all(isinstance(item, str) for item in options):
        raise RecommendationConfigError(f'{source}.options: нужен список строк')
    return Adjustment(when, action, product_id, tuple(options))


def _pricing(raw, product_id: str) -> dict:
    if not isinstance(raw, dict) or not raw:
        raise RecommendationConfigError(f'{product_id}: нужен pricing')
    pricing = dict(raw)
    if 'base_rate' in pricing and 'base_rate_pct' not in pricing:
        value = pricing.pop('base_rate')
        if type(value) not in (int, float) or value < 0:
            raise RecommendationConfigError(f'{product_id}: base_rate должен быть неотрицательным числом')
        pricing['base_rate_pct'] = float(value) * 100 if value <= 1 else float(value)
    if 'rate_discount_if_collateral' in pricing and 'rate_discount_if_collateral_pct' not in pricing:
        value = pricing.pop('rate_discount_if_collateral')
        if type(value) not in (int, float) or value < 0:
            raise RecommendationConfigError(f'{product_id}: скидка за залог должна быть неотрицательной')
        pricing['rate_discount_if_collateral_pct'] = float(value) * 100 if value <= 1 else float(value)
    for name in ('commission_year_pct', 'effective_annual_cost_pct'):
        if name in pricing:
            value = pricing[name]
            if type(value) not in (int, float) or value < 0:
                raise RecommendationConfigError(f'{product_id}: {name} должен быть неотрицательным числом')
            pricing[name] = float(value) * 100 if value <= 1 else float(value)
    if 'base_rate_pct' not in pricing and 'commission_year_pct' not in pricing:
        raise RecommendationConfigError(f'{product_id}: нужна ставка или комиссия')
    hours = pricing.get('approval_hours')
    if type(hours) is not int or hours < 0:
        raise RecommendationConfigError(f'{product_id}: approval_hours должен быть неотрицательным целым')
    return pricing


def _product(raw, purposes: Mapping[str, Purpose], reasons: Mapping[str, Reason],
             product_ids: set[str]) -> Product:
    if not isinstance(raw, dict):
        raise RecommendationConfigError('products: продукт должен быть объектом')
    product_id = _text(raw.get('id'), 'product.id')
    name = _text(raw.get('name'), f'{product_id}.name')
    kind = _text(raw.get('type'), f'{product_id}.type')
    product_purposes = _items(raw.get('purposes'), f'{product_id}.purposes')
    alt_purposes = raw.get('alt_purposes') or []
    if not all(isinstance(item, str) and item in purposes for item in product_purposes + alt_purposes):
        raise RecommendationConfigError(f'{product_id}: неизвестная цель продукта')
    cabinet = raw.get('cabinet_product_code')
    if cabinet is not None:
        cabinet = _text(cabinet, f'{product_id}.cabinet_product_code')
    layers = {}
    for layer in ('eligibility', 'needs', 'financial_limits'):
        rules = tuple(_rule(item, f'{product_id}.{layer}', reasons)
                      for item in _items(raw.get(layer), f'{product_id}.{layer}'))
        layers[layer] = rules
    pricing = _pricing(raw.get('pricing'), product_id)
    product_rules = {rule.id for rules in layers.values() for rule in rules}
    adjustments = tuple(_adjustment(item, f'{product_id}.adjustments', product_rules, product_ids)
                        for item in (raw.get('adjustments') or []))
    return Product(product_id, name, kind, tuple(product_purposes), tuple(alt_purposes), cabinet,
                   layers['eligibility'], layers['needs'], layers['financial_limits'],
                   pricing, adjustments)


def _weights(raw, name: str) -> dict[str, float]:
    if not isinstance(raw, dict) or set(raw) != set(WEIGHT_NAMES):
        raise RecommendationConfigError(f'{name}: нужны веса {", ".join(WEIGHT_NAMES)}')
    result = {}
    for key, value in raw.items():
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise RecommendationConfigError(f'{name}.{key}: нужен вес от 0 до 1')
        result[key] = float(value)
    if abs(sum(result.values()) - 1) > 1e-9:
        raise RecommendationConfigError(f'{name}: сумма весов должна быть равна 1')
    return result


def _ranking(raw: dict) -> Ranking:
    default = _weights(raw.get('default_weights'), 'default_weights')
    overrides = {}
    for urgency, values in (raw.get('urgency_overrides') or {}).items():
        if urgency not in ('high', 'normal'):
            raise RecommendationConfigError(f'urgency_overrides: неизвестная срочность {urgency}')
        overrides[urgency] = _weights(values, f'urgency_overrides.{urgency}')
    top_n = raw.get('show_top_n')
    delta = raw.get('close_score_delta')
    availability = raw.get('availability_bonus')
    cost_cap = raw.get('cost_cap')
    rounding = raw.get('rounding_kopecks')
    speed = raw.get('speed') or {}
    if type(top_n) is not int or top_n < 1:
        raise RecommendationConfigError('show_top_n: нужно положительное целое')
    if type(delta) not in (int, float) or delta < 0:
        raise RecommendationConfigError('close_score_delta: нужно неотрицательное число')
    if type(availability) not in (int, float) or not 0 <= availability <= 1:
        raise RecommendationConfigError('availability_bonus: нужен балл от 0 до 1')
    if type(cost_cap) not in (int, float) or cost_cap <= 0:
        raise RecommendationConfigError('cost_cap: нужно положительное число')
    if type(rounding) is not int or rounding < 1:
        raise RecommendationConfigError('rounding_kopecks: нужно положительное целое')
    threshold = speed.get('high_urgency_threshold_hours')
    fast = speed.get('fast_score')
    normal = speed.get('normal_score')
    if type(threshold) is not int or threshold < 0:
        raise RecommendationConfigError('speed.high_urgency_threshold_hours: нужно неотрицательное целое')
    for name, value in (('fast_score', fast), ('normal_score', normal)):
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise RecommendationConfigError(f'speed.{name}: нужен балл от 0 до 1')
    return Ranking(default, overrides, top_n, float(delta), float(availability), float(cost_cap),
                   rounding, threshold, float(fast), float(normal))


def _reasons(raw: dict) -> dict[str, Reason]:
    result = {}
    for code, value in raw.items():
        if not isinstance(value, dict):
            raise RecommendationConfigError(f'reasons.{code}: нужен объект')
        result[code] = Reason(_text(value.get('client'), f'{code}.client'),
                              _text(value.get('staff'), f'{code}.staff'),
                              _text(value.get('hint'), f'{code}.hint'))
    if not result:
        raise RecommendationConfigError('reasons.yaml: нужен хотя бы один код')
    return result


@lru_cache(maxsize=8)
def load_config(path: str | None = None) -> RecommendationConfig:
    """Читает все файлы один раз и проверяет ссылочную целостность."""
    directory = Path(path) if path is not None else DEFAULT_RULES_PATH
    try:
        raw = {name: _read_yaml(directory / name) for name in _FILE_NAMES}
        digest = hashlib.sha256()
        for name in _FILE_NAMES:
            digest.update(name.encode())
            digest.update((directory / name).read_bytes())
    except OSError as error:
        raise RecommendationConfigError('Не удалось прочитать конфигурацию правил') from error

    reasons = _reasons(raw['reasons.yaml'])
    purposes_raw = raw['purpose_map.yaml'].get('purposes')
    if not isinstance(purposes_raw, dict) or not purposes_raw:
        raise RecommendationConfigError('purpose_map.yaml: нужен purposes')
    purposes = {}
    for code, value in purposes_raw.items():
        if not isinstance(value, dict):
            raise RecommendationConfigError(f'purpose_map.{code}: нужен объект')
        label = _text(value.get('label'), f'purpose_map.{code}.label')
        primary = _items(value.get('primary'), f'purpose_map.{code}.primary')
        secondary = value.get('secondary') or []
        if not isinstance(secondary, list) or not all(isinstance(item, str) for item in primary + secondary):
            raise RecommendationConfigError(f'purpose_map.{code}: продукты должны быть строками')
        purposes[code] = Purpose(code, label, tuple(primary), tuple(secondary))

    product_items = raw['products.yaml'].get('products')
    version = _text(raw['products.yaml'].get('config_version'), 'config_version')
    if not isinstance(product_items, list) or not product_items:
        raise RecommendationConfigError('products.yaml: нужен непустой products')
    # Сначала собираем идентификаторы, чтобы проверить ссылки в adjustments.
    product_ids = set()
    for item in product_items:
        if not isinstance(item, dict):
            raise RecommendationConfigError('products.yaml: продукт должен быть объектом')
        product_id = _text(item.get('id'), 'product.id')
        if product_id in product_ids:
            raise RecommendationConfigError(f'Повторяющийся продукт: {product_id}')
        product_ids.add(product_id)
    products = tuple(_product(item, purposes, reasons, product_ids) for item in product_items)
    product_ids = {product.id for product in products}
    for product in products:
        for adjustment in product.adjustments:
            if adjustment.product_id is not None and adjustment.product_id not in product_ids:
                raise RecommendationConfigError(f'{product.id}: неизвестный продукт в adjustment')
    for purpose in purposes.values():
        if not set(purpose.primary + purpose.secondary) <= product_ids:
            raise RecommendationConfigError(f'purpose_map.{purpose.code}: неизвестный продукт')

    seen_rules = set()
    global_rules = tuple(_rule(item, 'stop_factors.global_stop_factors', reasons)
                         for item in _items(raw['stop_factors.yaml'].get('global_stop_factors'),
                                            'global_stop_factors'))
    for rule in global_rules:
        if rule.id in seen_rules:
            raise RecommendationConfigError(f'Повторяющийся rule id: {rule.id}')
        seen_rules.add(rule.id)
    for product in products:
        for rule in (*product.eligibility, *product.needs, *product.financial_limits):
            if rule.id in seen_rules:
                raise RecommendationConfigError(f'Повторяющийся rule id: {rule.id}')
            seen_rules.add(rule.id)
        for adjustment in product.adjustments:
            if adjustment.when not in seen_rules:
                raise RecommendationConfigError(f'{product.id}: adjustment ссылается на неизвестное правило')
    prefixes = raw['stop_factors.yaml'].get('excluded_okved_prefixes') or []
    if not isinstance(prefixes, list) or not all(isinstance(item, str) for item in prefixes):
        raise RecommendationConfigError('excluded_okved_prefixes: нужен список строк')

    ranking = _ranking(raw['ranking.yaml'])
    return RecommendationConfig(version, digest.hexdigest(), products, purposes, ranking, reasons,
                                tuple(global_rules), tuple(prefixes))
