"""Контракты поставки LR: ручная арифметика, область входов и целостность."""

import hashlib
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from app.risk.features import FEATURE_NAMES, FeatureVector
from app.risk import runtime


def vector(**changes):
    values = dict(business_age_months=24, monthly_revenue_rub=100000,
                  operating_margin_ratio=.2, existing_debt_to_revenue_ratio=.1,
                  coverage_ratio=2, overdue_days=0, product_code='equipment',
                  requested_amount_rub=300000, term_months=12)
    values.update(changes)
    return FeatureVector(values, {name: value is None for name, value in values.items()})


def simple_bundle():
    numeric = [name for name in FEATURE_NAMES if name != 'product_code']
    masks = [f'{name}_missing' for name in FEATURE_NAMES]
    # При возрасте 24 вклад (24 - 20) / 2 * .5 = 1; equipment даёт -2.
    return dict(bundle_schema_version=1, model_version='logistic-risk-v1',
                feature_schema_version='risk-features-v1', target_event='loan_90dpd_12m',
                horizon_months=12, data_kind='synthetic', numeric_features=numeric,
                categorical_feature='product_code', categories=['equipment', 'working_capital'],
                mask_features=masks,
                transformed_features=[*[f'numeric__{n}' for n in numeric],
                                      'product__product_code_equipment',
                                      'product__product_code_working_capital',
                                      *[f'masks__{n}' for n in masks]],
                imputation_medians=[22, 100000, .2, .1, 2, 0, 300000, 12],
                scaling_means=[20, 100000, .2, .1, 2, 0, 300000, 12],
                scaling_scales=[2, 1, 1, 1, 1, 1, 1, 1],
                coefficients=[.5, 0, 0, 0, 0, 0, 0, 0, -2, 3, *([0] * 9)],
                intercept=.5, provenance={'candidate_id': 'lr_c1'})


@pytest.fixture
def install_bundle(tmp_path, monkeypatch):
    def install(payload=None, *, raw=None, digest=None):
        path = tmp_path / 'model.json'
        contents = raw if raw is not None else json.dumps(payload or simple_bundle()).encode()
        path.write_bytes(contents)
        monkeypatch.setattr(runtime, '_MODEL_REGISTRY', {
            runtime.MODEL_VERSION: (path, digest or hashlib.sha256(contents).hexdigest())})
        runtime._load_model.cache_clear()
        return path
    yield install
    runtime._load_model.cache_clear()


def test_hand_computed_lr_additivity_and_signed_top_three(install_bundle):
    install_bundle()
    prediction = runtime.score_features(vector())
    assert prediction.raw_prediction == -.5
    assert prediction.probability == pytest.approx(.3775406687981454, abs=1e-15)
    assert prediction.base_value == .5
    assert prediction.base_value + sum(f.contribution for f in prediction.contributions) == -.5
    assert [(f.feature_name, f.contribution) for f in prediction.top_increasing_factors] == [
        ('numeric__business_age_months', 1)]
    assert [(f.feature_name, f.contribution) for f in prediction.top_decreasing_factors] == [
        ('product__product_code_equipment', -2)]
    assert all(any('а' <= c <= 'я' for c in f.label.lower()) for f in prediction.contributions)
    assert prediction.explanation_method == 'linear_contributions'
    assert prediction.explanation_scale == 'raw_log_odds'
    assert prediction.target_event == 'loan_90dpd_12m'
    with pytest.raises(FrozenInstanceError):
        prediction.probability = 0
    with pytest.raises(FrozenInstanceError):
        prediction.contributions[0].contribution = 0


def test_missing_nullable_value_uses_train_median_and_its_mask(install_bundle):
    bundle = simple_bundle()
    bundle['imputation_medians'][2] = .6
    bundle['coefficients'][2] = 5
    bundle['coefficients'][12] = 3
    install_bundle(bundle)
    result = runtime.score_features(vector(operating_margin_ratio=None))
    assert result.raw_prediction == pytest.approx(4.5)
    assert result.contributions[2].contribution == pytest.approx(2)
    assert result.contributions[12].contribution == 3


@pytest.mark.parametrize('changes', [
    {'product_code': 'unknown'}, {'monthly_revenue_rub': float('nan')},
    {'coverage_ratio': float('inf')}, {'overdue_days': 90}, {'business_age_months': -1},
    {'term_months': 12.5}, {'monthly_revenue_rub': -1}, {'requested_amount_rub': 0},
    {'existing_debt_to_revenue_ratio': -1}, {'operating_margin_ratio': 1.1},
    {'product_code': None}, {'business_age_months': None}, {'coverage_ratio': None},
    {'monthly_revenue_rub': True}, {'term_months': 3}, {'requested_amount_rub': 100000},
])
def test_rejects_invalid_or_out_of_domain_inputs(install_bundle, changes):
    install_bundle()
    with pytest.raises(runtime.RiskModelError):
        runtime.score_features(vector(**changes))


def test_rejects_mask_schema_and_field_mismatch(install_bundle):
    install_bundle()
    for features in (
        FeatureVector(vector().values, {**vector().missing_mask, 'overdue_days': 1}),
        FeatureVector(vector().values, {**vector().missing_mask, 'overdue_days': True}),
        FeatureVector({**vector().values, 'extra': 1}, vector().missing_mask),
        FeatureVector(vector().values, {}, schema_version='other'),
    ):
        with pytest.raises(runtime.RiskModelError):
            runtime.score_features(features)


@pytest.mark.parametrize('change', [
    {'model_version': 'other'}, {'feature_schema_version': 'other'},
    {'target_event': 'other'}, {'horizon_months': 24}, {'data_kind': 'real'},
    {'bundle_schema_version': 2}, {'coefficients': [1]},
    {'scaling_scales': [0] * 8}, {'numeric_features': []},
    {'intercept': float('inf')}, {'transformed_features': []},
])
def test_rejects_incompatible_bundle(install_bundle, change):
    install_bundle({**simple_bundle(), **change})
    with pytest.raises(runtime.RiskModelError):
        runtime.score_features(vector())


def test_rejects_unknown_version_hash_corruption_and_missing_file(install_bundle):
    path = install_bundle()
    with pytest.raises(runtime.RiskModelError):
        runtime.score_features(vector(), model_version='../../untrusted.json')
    path.write_text('{}')
    with pytest.raises(runtime.RiskModelError):
        runtime.score_features(vector())
    path.unlink()
    with pytest.raises(runtime.RiskModelError):
        runtime.score_features(vector())
    install_bundle(raw=b'{invalid')
    with pytest.raises(runtime.RiskModelError):
        runtime.score_features(vector())


def test_rejects_nonfinite_raw_prediction(install_bundle):
    bundle = simple_bundle()
    bundle['coefficients'][1] = 1e308
    bundle['scaling_means'][1] = 0
    install_bundle(bundle)
    with pytest.raises(runtime.RiskModelError):
        runtime.score_features(vector())


def test_successful_load_is_cached_by_version(install_bundle):
    path = install_bundle()
    first = runtime.score_features(vector())
    path.unlink()
    assert runtime.score_features(vector()) == first


def test_real_bundle_loads_without_site_packages_database_or_network():
    script = '''
import sys
from types import SimpleNamespace
from app.risk.runtime import score_features
values = dict(business_age_months=24, monthly_revenue_rub=100000,
 operating_margin_ratio=.2, existing_debt_to_revenue_ratio=.1, coverage_ratio=2,
 overdue_days=0, product_code='equipment', requested_amount_rub=300000, term_months=12)
p = score_features(SimpleNamespace(values=values, missing_mask={k: False for k in values},
 schema_version='risk-features-v1'))
assert 0 <= p.probability <= 1
assert not any(n.split('.')[0] in {'numpy', 'pandas', 'sklearn', 'catboost', 'joblib',
 'sqlalchemy', 'pydantic'} for n in sys.modules)
'''
    result = subprocess.run([sys.executable, '-S', '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_top_factors_keep_three_per_sign_in_contribution_order(install_bundle):
    bundle = simple_bundle()
    bundle['scaling_means'] = [23, 99999, -.8, -.9, 1, -1, 299999, 11]
    bundle['scaling_scales'] = [1] * 8
    bundle['coefficients'] = [1, 4, 3, 2, -1, -4, -3, -2, *([0] * 11)]
    install_bundle(bundle)
    result = runtime.score_features(vector())
    assert [f.contribution for f in result.top_increasing_factors] == [4, 3, 2]
    assert [f.contribution for f in result.top_decreasing_factors] == [-4, -3, -2]


@pytest.mark.parametrize('raw, probability', [(1000000, 1), (-1000000, 0)])
def test_sigmoid_is_stable_for_extreme_finite_log_odds(install_bundle, raw, probability):
    bundle = simple_bundle()
    bundle['intercept'] = raw
    bundle['coefficients'] = [0] * 19
    install_bundle(bundle)
    assert runtime.score_features(vector()).probability == probability


@pytest.mark.parametrize('version', [None, [], {}, 42])
def test_nonstring_version_is_a_model_error(install_bundle, version):
    install_bundle()
    with pytest.raises(runtime.RiskModelError):
        runtime.score_features(vector(), model_version=version)


def test_failed_load_is_not_cached(install_bundle):
    path = install_bundle()
    contents = path.read_bytes()
    path.write_text('{}')
    with pytest.raises(runtime.RiskModelError):
        runtime.score_features(vector())
    path.write_bytes(contents)
    assert runtime.score_features(vector()).probability == pytest.approx(.3775406687981454)
