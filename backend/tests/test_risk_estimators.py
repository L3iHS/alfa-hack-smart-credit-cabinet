"""Обучение на небольших таблицах без принятого набора 10000 компаний."""

import importlib
import json

import pytest

np = pytest.importorskip('numpy')
pd = pytest.importorskip('pandas')
pytest.importorskip('sklearn')
pytest.importorskip('catboost')

from app.products.catalog import PRODUCTS
from app.risk.features import FEATURE_NAMES


def small_train():
    data = importlib.import_module('app.risk.training_data')
    rows = []
    for index in range(24):
        row = {name: float(index + 1) for name in FEATURE_NAMES}
        row['product_code'] = sorted(PRODUCTS)[index % 2]
        row.update({f'{name}_missing': 0 for name in FEATURE_NAMES})
        row['operating_margin_ratio'] = np.nan if index % 3 == 0 else float(index)
        row['operating_margin_ratio_missing'] = int(index % 3 == 0)
        row['existing_debt_to_revenue_ratio'] = np.nan
        row['existing_debt_to_revenue_ratio_missing'] = 1
        rows.append(row)
    return data.DataSplit('train', pd.DataFrame(rows, columns=data.MODEL_FEATURES),
                          np.array([0] * 12 + [1] * 12), pd.DataFrame())


def spec_for(family):
    api = importlib.import_module('app.risk.estimators')
    if family == 'catboost':
        return api.CandidateSpec('tiny_cat', 'catboost', dict(depth=2, iterations=12,
            learning_rate=0.05, l2_leaf_reg=5, loss_function='Logloss'))
    return next(c for c in api.default_candidates() if c.family == family)


def test_default_candidates_match_fixed_protocol():
    api = importlib.import_module('app.risk.estimators')
    candidates = api.default_candidates()
    assert [c.candidate_id for c in candidates] == ['baseline', 'lr_c01', 'lr_c1', 'lr_c10', 'cat_d4', 'cat_d6']
    assert [c.params['C'] for c in candidates if c.family == 'logistic'] == [0.1, 1, 10]
    assert [c.params['depth'] for c in candidates if c.family == 'catboost'] == [4, 6]
    assert all(c.params['iterations'] == 400 for c in candidates if c.family == 'catboost')
    for candidate in candidates:
        assert candidate.params.get('class_weight') is None
    assert candidates[1].params == dict(C=0.1, solver='lbfgs', max_iter=2000, tol=1e-6)


@pytest.mark.parametrize('family', ['constant', 'logistic', 'catboost'])
def test_fit_predict_repeatability_and_roundtrip(family, tmp_path):
    api = importlib.import_module('app.risk.estimators')
    train = small_train()
    spec = spec_for(family)
    first = api.fit_candidate(spec, train)
    second = api.fit_candidate(spec, train)
    p = api.predict_probability(first, train.X)
    assert p.shape == (24,)
    assert np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()
    np.testing.assert_allclose(p, api.predict_probability(second, train.X), atol=1e-10, rtol=0)
    if family == 'constant':
        np.testing.assert_array_equal(p, np.full(24, .5))
    if family == 'catboost':
        assert first.estimator.tree_count_ == 12
        assert tuple(first.estimator.feature_names_) == tuple(train.X.columns)
        assert first.estimator.get_all_params()['task_type'] == 'CPU'
    record = api.save_candidate(first, tmp_path)
    assert record['candidate_id'] == spec.candidate_id
    loaded = api.load_candidate(tmp_path, record)
    np.testing.assert_allclose(p, api.predict_probability(loaded, train.X), atol=1e-10, rtol=0)
    with pytest.raises(FileExistsError):
        api.save_candidate(first, tmp_path)


def test_logistic_uses_train_median_scaling_known_products_and_all_masks():
    api = importlib.import_module('app.risk.estimators')
    train = small_train()
    fitted = api.fit_candidate(spec_for('logistic'), train)
    preprocessor = fitted.estimator.named_steps['preprocessor']
    numeric = preprocessor.named_transformers_['numeric']
    imputer = numeric.named_steps['imputer']
    scaler = numeric.named_steps['scaler']
    assert imputer.statistics_[2] == 12
    assert scaler.mean_[0] == 12.5
    assert len(imputer.statistics_) == 8
    assert imputer.keep_empty_features
    assert preprocessor.transform(train.X).shape == (24, 19)
    names = list(preprocessor.get_feature_names_out())
    assert len([n for n in names if n.startswith('masks__')]) == 9
    validation = train.X.copy()
    validation['business_age_months'] = 10000
    before = scaler.mean_.copy()
    api.predict_probability(fitted, validation)
    np.testing.assert_array_equal(scaler.mean_, before)
    np.testing.assert_array_equal(preprocessor.named_transformers_['product'].categories_[0], sorted(PRODUCTS))


@pytest.mark.parametrize('family', ['constant', 'logistic', 'catboost'])
def test_all_families_reject_wrong_column_order_and_single_class(family):
    api = importlib.import_module('app.risk.estimators')
    train = small_train()
    fitted = api.fit_candidate(spec_for(family), train)
    with pytest.raises(ValueError):
        api.predict_probability(fitted, train.X[train.X.columns[::-1]])
    train.y[:] = 0
    with pytest.raises(ValueError):
        api.fit_candidate(spec_for(family), train)


def test_positive_class_is_found_by_class_label_and_invalid_outputs_rejected():
    api = importlib.import_module('app.risk.estimators')
    train = small_train()

    class ReversedClasses:
        classes_ = np.array([1, 0])

        def predict_proba(self, X):
            return np.tile([.7, .3], (len(X), 1))

    fitted = api.FittedCandidate(spec_for('logistic'), ReversedClasses())
    np.testing.assert_array_equal(api.predict_probability(fitted, train.X), np.full(24, .7))
    fitted.estimator.classes_ = np.array([2, 0])
    with pytest.raises(ValueError):
        api.predict_probability(fitted, train.X)
    fitted.estimator.classes_ = np.array([1, 0])
    fitted.estimator.predict_proba = lambda X: np.tile([np.nan, .3], (len(X), 1))
    with pytest.raises(ValueError):
        api.predict_probability(fitted, train.X)


def test_convergence_warning_is_a_failure():
    api = importlib.import_module('app.risk.estimators')
    train = small_train()
    spec = api.CandidateSpec('short_lr', 'logistic', dict(C=1, solver='lbfgs', max_iter=1, tol=1e-12))
    with pytest.raises((ValueError, RuntimeError), match='сходим|Converg|converg'):
        api.fit_candidate(spec, train)


@pytest.mark.parametrize('kind', ['traversal', 'order'])
def test_load_rejects_arbitrary_paths_and_wrong_feature_order(tmp_path, kind):
    api = importlib.import_module('app.risk.estimators')
    train = small_train()
    candidate = api.fit_candidate(spec_for('constant'), train)
    record = api.save_candidate(candidate, tmp_path)
    if kind == 'traversal':
        record['filename'] = '../secret.json'
    else:
        file = tmp_path / record['filename']
        payload = json.loads(file.read_text())
        payload['feature_names'] = list(reversed(train.X.columns))
        file.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        api.load_candidate(tmp_path, record)


def test_constant_uses_only_training_prevalence():
    api = importlib.import_module('app.risk.estimators')
    train = small_train()
    train.y[:6] = 1
    candidate = api.fit_candidate(spec_for('constant'), train)
    validation = train.X.copy()
    validation['monthly_revenue_rub'] = 100000000
    np.testing.assert_array_equal(api.predict_probability(candidate, validation), np.full(24, .75))


def test_catboost_does_not_create_training_files(tmp_path, monkeypatch):
    api = importlib.import_module('app.risk.estimators')
    monkeypatch.chdir(tmp_path)
    api.fit_candidate(spec_for('catboost'), small_train())
    assert not (tmp_path / 'catboost_info').exists()
