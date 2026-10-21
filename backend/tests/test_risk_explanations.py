"""Объяснения восстанавливают прогноз положительного класса после загрузки модели."""

import importlib

import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('catboost')

from app.risk.dataset import build_dataset
from app.risk.estimators import default_candidates, fit_candidate, load_candidate, predict_probability, save_candidate
from app.risk.training_data import DatasetReader, MODEL_FEATURES


@pytest.fixture(scope='module')
def examples(tmp_path_factory):
    root = tmp_path_factory.mktemp('explanations')
    build_dataset(root / 'data', count=120, seed=20261021)
    reader = DatasetReader(root / 'data')
    train, validation = reader.split('train'), reader.split('validation')
    return root, train, validation.X.iloc[:5]


@pytest.mark.parametrize('family,width,method', [('catboost', 18, 'native_shap'), ('logistic', 19, 'linear_contributions')])
def test_explanations_additivity_positive_class_and_roundtrip(examples, family, width, method):
    module = importlib.import_module('app.risk.explanations')
    root, train, X = examples
    spec = next(spec for spec in default_candidates() if spec.family == family)
    candidate = fit_candidate(spec, train)
    explain = getattr(module, f'explain_{family}')
    result = explain(candidate, X)
    assert result['method'] == method and result['scale'] == 'raw_log_odds'
    assert result['candidate_id'] == spec.candidate_id
    assert len(result['feature_names']) == width
    if family == 'catboost':
        assert result['feature_names'] == list(MODEL_FEATURES)
    else:
        assert 'product__product_code_equipment' in result['feature_names']
    contribution = np.asarray(result['contributions'])
    base = np.asarray(result['base_values'])
    raw = np.asarray(result['raw_predictions'])
    assert contribution.shape == (5, width) and base.shape == raw.shape == (5,)
    assert np.isfinite(contribution).all() and np.isfinite(base).all() and np.isfinite(raw).all()
    np.testing.assert_allclose(base + contribution.sum(axis=1), raw, rtol=0, atol=1e-8)
    np.testing.assert_allclose(1 / (1 + np.exp(-raw)), result['probabilities'], rtol=0, atol=1e-8)
    np.testing.assert_allclose(result['probabilities'], predict_probability(candidate, X), rtol=0, atol=1e-8)
    record = save_candidate(candidate, root / family)
    restored = explain(load_candidate(root / family, record), X)
    for key in ('base_values', 'contributions', 'raw_predictions', 'probabilities'):
        np.testing.assert_allclose(restored[key], result[key], rtol=0, atol=1e-10)


def test_wrong_family_and_column_order_are_rejected(examples):
    module = importlib.import_module('app.risk.explanations')
    _, train, X = examples
    candidate = fit_candidate(default_candidates()[1], train)
    with pytest.raises(ValueError):
        module.explain_catboost(candidate, X)
    with pytest.raises(ValueError):
        module.explain_logistic(candidate, X[X.columns[::-1]])


def test_broken_linear_values_fail_instead_of_exporting_nonfinite(examples):
    module = importlib.import_module('app.risk.explanations')
    _, train, X = examples
    candidate = fit_candidate(default_candidates()[1], train)
    candidate.estimator.named_steps['model'].coef_[0, 0] = np.nan
    with pytest.raises(ValueError):
        module.explain_logistic(candidate, X)


def test_inconsistent_shap_is_rejected(examples, monkeypatch):
    module = importlib.import_module('app.risk.explanations')
    _, train, X = examples
    candidate = fit_candidate(next(spec for spec in default_candidates() if spec.family == 'catboost'), train)
    native = candidate.estimator.get_feature_importance

    def inconsistent(*args, **kwargs):
        values = native(*args, **kwargs)
        values[:, 0] += 1
        return values

    monkeypatch.setattr(candidate.estimator, 'get_feature_importance', inconsistent)
    with pytest.raises(ValueError, match='не восстанавливают'):
        module.explain_catboost(candidate, X)


def test_catboost_native_explanations_limit_threads_and_preserve_probability(examples, monkeypatch):
    module = importlib.import_module('app.risk.explanations')
    _, train, X = examples
    candidate = fit_candidate(next(spec for spec in default_candidates() if spec.family == 'catboost'), train)
    native_shap = candidate.estimator.get_feature_importance
    native_raw = candidate.estimator.predict
    native_probability = candidate.estimator.predict_proba
    expected = native_probability(X)[:, list(candidate.estimator.classes_).index(1)]

    def bounded_shap(*args, **kwargs):
        assert kwargs.get('thread_count') == 2, 'Нужен явный лимит native SHAP'
        return native_shap(*args, **kwargs)

    def bounded_raw(*args, **kwargs):
        assert kwargs.get('thread_count') == 2, 'Нужен явный лимит native raw predict'
        return native_raw(*args, **kwargs)

    def bounded_probability(*args, **kwargs):
        assert kwargs.get('thread_count') == 2, 'Нужен явный лимит native probability predict'
        return native_probability(*args, **kwargs)

    monkeypatch.setattr(candidate.estimator, 'get_feature_importance', bounded_shap)
    monkeypatch.setattr(candidate.estimator, 'predict', bounded_raw)
    monkeypatch.setattr(candidate.estimator, 'predict_proba', bounded_probability)
    result = module.explain_catboost(candidate, X)
    np.testing.assert_allclose(result['probabilities'], expected, rtol=0, atol=1e-10)
    np.testing.assert_allclose(np.asarray(result['base_values']) + np.asarray(result['contributions']).sum(axis=1),
                               result['raw_predictions'], rtol=0, atol=1e-8)
    np.testing.assert_allclose(1 / (1 + np.exp(-np.asarray(result['raw_predictions']))),
                               result['probabilities'], rtol=0, atol=1e-8)
