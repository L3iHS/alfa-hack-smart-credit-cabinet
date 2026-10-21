"""Исполнение неизменяемой LR и линейные вклады в raw log odds."""

import hashlib
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.risk.features import FeatureVector

MODEL_VERSION = 'logistic-risk-v1'
_SCHEMA = 'risk-features-v1'
_FEATURES = ('business_age_months', 'monthly_revenue_rub', 'operating_margin_ratio',
             'existing_debt_to_revenue_ratio', 'coverage_ratio', 'overdue_days',
             'product_code', 'requested_amount_rub', 'term_months')
_NUMERIC = tuple(name for name in _FEATURES if name != 'product_code')
_MASKS = tuple(f'{name}_missing' for name in _FEATURES)
_CATEGORIES = ('equipment', 'working_capital')
_TRANSFORMED = (*[f'numeric__{name}' for name in _NUMERIC],
                *[f'product__product_code_{name}' for name in _CATEGORIES],
                *[f'masks__{name}' for name in _MASKS])
_LABELS = dict(business_age_months='Возраст бизнеса', monthly_revenue_rub='Месячная выручка',
               operating_margin_ratio='Операционная маржа',
               existing_debt_to_revenue_ratio='Доля действующих кредитных платежей в выручке',
               coverage_ratio='Покрытие кредитных платежей', overdue_days='Текущая просрочка',
               requested_amount_rub='Запрошенная сумма', term_months='Срок кредита')
_MODEL_REGISTRY = {
    MODEL_VERSION: (Path(__file__).with_name('models') / 'logistic-risk-v1.json',
                    'ae47becf2c3ead8604b25049753a43ae3d0cc35c75fb36f94cff00f9d1af8ac5'),
}


class RiskModelError(ValueError):
    """Поставка модели или входы не соответствуют контракту."""


@dataclass(frozen=True)
class RiskContribution:
    feature_name: str
    label: str
    contribution: float


@dataclass(frozen=True)
class RiskPrediction:
    model_version: str
    feature_schema_version: str
    target_event: str
    horizon_months: int
    data_kind: str
    probability: float
    explanation_method: str
    explanation_scale: str
    base_value: float
    raw_prediction: float
    contributions: tuple[RiskContribution, ...]
    top_increasing_factors: tuple[RiskContribution, ...]
    top_decreasing_factors: tuple[RiskContribution, ...]


@dataclass(frozen=True)
class _Model:
    medians: tuple[float, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _numbers(payload, name, length):
    values = payload.get(name)
    if not isinstance(values, list) or len(values) != length or not all(_finite(v) for v in values):
        raise RiskModelError(f'{name}: несовместимые числовые параметры модели')
    return tuple(float(v) for v in values)


def _decode_model(payload, model_version):
    """Проверяет контракт JSON до вычисления и замораживает его параметры."""
    expected = dict(bundle_schema_version=1, model_version=model_version,
                    feature_schema_version=_SCHEMA, target_event='loan_90dpd_12m',
                    horizon_months=12, data_kind='synthetic', numeric_features=list(_NUMERIC),
                    categorical_feature='product_code', categories=list(_CATEGORIES),
                    mask_features=list(_MASKS), transformed_features=list(_TRANSFORMED))
    if not isinstance(payload, dict) or any(payload.get(k) != v for k, v in expected.items()):
        raise RiskModelError('Несовместимые версия, цель или схема поставки модели')
    if (type(payload['bundle_schema_version']) is not int or type(payload['horizon_months']) is not int
            or not isinstance(payload.get('provenance'), dict)
            or payload['provenance'].get('candidate_id') != 'lr_c1'):
        raise RiskModelError('Неверные метаданные поставки модели')
    medians = _numbers(payload, 'imputation_medians', 8)
    means = _numbers(payload, 'scaling_means', 8)
    scales = _numbers(payload, 'scaling_scales', 8)
    coefficients = _numbers(payload, 'coefficients', 19)
    if not all(scale > 0 for scale in scales) or not _finite(payload.get('intercept')):
        raise RiskModelError('Масштабы должны быть положительными, свободный член — конечным')
    return _Model(medians, means, scales, coefficients, float(payload['intercept']))


@lru_cache(maxsize=8)
def _load_model(model_version):
    """Загружает только зарегистрированный путь и кэширует успешную версию."""
    if not isinstance(model_version, str) or model_version not in _MODEL_REGISTRY:
        raise RiskModelError('Неизвестная версия модели риска')
    path, digest = _MODEL_REGISTRY[model_version]
    try:
        contents = path.read_bytes()
        if hashlib.sha256(contents).hexdigest() != digest:
            raise RiskModelError('SHA256 поставки модели не совпадает')
        payload = json.loads(contents)
        return _decode_model(payload, model_version)
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError) as error:
        if isinstance(error, RiskModelError):
            raise
        raise RiskModelError('Не удалось загрузить поставку модели риска') from error


def _validate_features(features):
    try:
        values, masks = features.values, features.missing_mask
        if (features.schema_version != _SCHEMA or not isinstance(values, dict)
                or not isinstance(masks, dict) or set(values) != set(_FEATURES)
                or set(masks) != set(_FEATURES)):
            raise RiskModelError('Несовместимая схема входных признаков')
        for name in _FEATURES:
            value, missing = values[name], masks[name]
            if type(missing) is not bool or missing != (value is None):
                raise RiskModelError(f'{name}: маска не соответствует пропуску')
            if value is None:
                if name not in ('operating_margin_ratio', 'existing_debt_to_revenue_ratio'):
                    raise RiskModelError(f'{name}: пропуск недопустим')
            elif name != 'product_code' and not _finite(value):
                raise RiskModelError(f'{name}: нужно конечное число')
        product = values['product_code']
        if not isinstance(product, str) or product not in _CATEGORIES:
            raise RiskModelError('Неизвестный продукт')
        for name in ('business_age_months', 'overdue_days', 'term_months'):
            if values[name] < 0 or values[name] != int(values[name]):
                raise RiskModelError(f'{name}: нужно неотрицательное целое число')
        if (values['overdue_days'] > 89 or values['monthly_revenue_rub'] < 0
                or (values['operating_margin_ratio'] is not None and values['operating_margin_ratio'] > 1)
                or (values['existing_debt_to_revenue_ratio'] is not None
                    and values['existing_debt_to_revenue_ratio'] < 0)):
            raise RiskModelError('Признаки выходят за область определения модели')
        # Границы той версии каталога, с которой обучена неизменяемая поставка.
        amount_min, amount_max, term_min, term_max = (
            (300000, 10000000, 6, 36) if product == 'equipment' else (100000, 5000000, 3, 24))
        if not (amount_min <= values['requested_amount_rub'] <= amount_max
                and term_min <= values['term_months'] <= term_max):
            raise RiskModelError('Сумма или срок выходят за границы продукта модели')
        return values, masks
    except (AttributeError, TypeError, OverflowError) as error:
        raise RiskModelError('Неверный формат входных признаков') from error


def _label(name):
    if name.startswith('numeric__'):
        return _LABELS[name.removeprefix('numeric__')]
    if name.startswith('product__'):
        return ('Продукт: кредит на оборудование' if name.endswith('_equipment')
                else 'Продукт: оборотный кредит')
    feature = name.removeprefix('masks__').removesuffix('_missing')
    return 'Пропуск: ' + ('продукт' if feature == 'product_code' else _LABELS[feature].lower())


def score_features(features: 'FeatureVector', *, model_version: str = MODEL_VERSION) -> RiskPrediction:
    """Возвращает вероятность события и полные вклады без кредитного решения."""
    if not isinstance(model_version, str):
        raise RiskModelError('Неизвестная версия модели риска')
    return _predict(features, _load_model(model_version), model_version)


def _predict(features, model, model_version):
    values, masks = _validate_features(features)
    transformed = [((model.medians[i] if values[name] is None else values[name]) - model.means[i])
                   / model.scales[i] for i, name in enumerate(_NUMERIC)]
    transformed.extend(float(values['product_code'] == category) for category in _CATEGORIES)
    transformed.extend(float(masks[name]) for name in _FEATURES)
    contributions = tuple(RiskContribution(name, _label(name), value * coefficient)
                          for name, value, coefficient in zip(_TRANSFORMED, transformed, model.coefficients))
    raw = model.intercept + sum(f.contribution for f in contributions)
    if not math.isfinite(raw) or not all(math.isfinite(f.contribution) for f in contributions):
        raise RiskModelError('Модель вернула неконечный прогноз или вклад')
    # Две ветви сохраняют устойчивость sigmoid при больших по модулю log odds.
    probability = 1 / (1 + math.exp(-raw)) if raw >= 0 else math.exp(raw) / (1 + math.exp(raw))
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise RiskModelError('Модель вернула неверную вероятность')
    increasing = tuple(sorted((f for f in contributions if f.contribution > 0),
                              key=lambda f: -f.contribution)[:3])
    decreasing = tuple(sorted((f for f in contributions if f.contribution < 0),
                              key=lambda f: f.contribution)[:3])
    return RiskPrediction(model_version, _SCHEMA, 'loan_90dpd_12m', 12, 'synthetic', probability,
                          'linear_contributions', 'raw_log_odds', model.intercept, raw,
                          contributions, increasing, decreasing)
