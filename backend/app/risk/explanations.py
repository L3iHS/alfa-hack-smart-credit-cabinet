"""Математические вклады в прогноз; они не являются причинами кредитного решения."""

import numpy as np
import pandas as pd
from catboost import Pool

from app.risk.estimators import FittedCandidate, _check_columns, predict_probability
from app.risk.training_data import MODEL_FEATURES


def _result(candidate, X, names, base, contributions, raw, method, **extra):
    probability = predict_probability(candidate, X)
    base, contributions, raw = (np.asarray(value, dtype=float) for value in (base, contributions, raw))
    if (base.shape != (len(X),) or raw.shape != (len(X),)
            or contributions.shape != (len(X), len(names))
            or any(not np.isfinite(value).all() for value in (base, contributions, raw))):
        raise ValueError('Объяснение должно содержать конечные вклады правильной формы')
    sigmoid = np.exp(-np.logaddexp(0, -raw))
    if (not np.allclose(base + contributions.sum(axis=1), raw, atol=1e-8, rtol=0)
            or not np.allclose(sigmoid, probability, atol=1e-8, rtol=0)):
        raise ValueError('Вклады не восстанавливают raw log odds и вероятность класса 1')
    return dict(candidate_id=candidate.spec.candidate_id, feature_names=list(names),
                base_values=base.tolist(), contributions=contributions.tolist(),
                raw_predictions=raw.tolist(), probabilities=probability.tolist(),
                scale='raw_log_odds', method=method, **extra)


def _check(candidate, X, family):
    if candidate.spec.family != family:
        raise ValueError(f'Объяснение требует семейство {family}')
    _check_columns(X)
    if X.empty or list(candidate.estimator.classes_) != [0, 1]:
        raise ValueError('Нужны непустые входы и бинарная модель с классами 0, 1')


def explain_catboost(candidate: FittedCandidate, X: pd.DataFrame) -> dict:
    """Нативные SHAP CatBoost в шкале log odds положительного класса."""
    _check(candidate, X, 'catboost')
    pool = Pool(X, cat_features=['product_code'], feature_names=list(MODEL_FEATURES))
    values = np.asarray(candidate.estimator.get_feature_importance(pool, type='ShapValues', thread_count=2))
    raw = candidate.estimator.predict(pool, prediction_type='RawFormulaVal', thread_count=2)
    if values.shape != (len(X), len(MODEL_FEATURES) + 1):
        raise ValueError('CatBoost вернул несовместимую форму SHAP')
    return _result(candidate, X, MODEL_FEATURES, values[:, -1], values[:, :-1], raw, 'native_shap')


def explain_logistic(candidate: FittedCandidate, X: pd.DataFrame) -> dict:
    """Точные линейные вклады после train-преобразований; это не SHAP."""
    _check(candidate, X, 'logistic')
    preprocessor = candidate.estimator.named_steps['preprocessor']
    model = candidate.estimator.named_steps['model']
    transformed = np.asarray(preprocessor.transform(X), dtype=float)
    names = preprocessor.get_feature_names_out()
    contributions = transformed * model.coef_[0]
    base = np.full(len(X), model.intercept_[0])
    raw = candidate.estimator.decision_function(X)
    return _result(candidate, X, names, base, contributions, raw, 'linear_contributions',
                   transformed_values=transformed.tolist())
