"""Ручные примеры вероятностных метрик и парного bootstrap компаний."""

import importlib
import math

import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('pandas')
pytest.importorskip('sklearn')
pytest.importorskip('catboost')


def test_probability_metrics_match_hand_computed_example():
    api = importlib.import_module('app.risk.metrics')
    result = api.probability_metrics([0, 1, 0, 1], [.1, .9, .4, .6])
    assert result['n'] == 4
    assert result['events'] == 2
    assert result['prevalence'] == .5
    assert result['brier'] == pytest.approx(.085)
    assert result['log_loss'] == pytest.approx((-math.log(.9) - math.log(.6)) / 2)
    assert result['roc_auc'] == 1
    assert result['average_precision'] == 1
    assert result['unavailable'] == {}


def test_one_class_metrics_have_explicit_unavailable_reason():
    api = importlib.import_module('app.risk.metrics')
    result = api.probability_metrics([0, 0], [0, 1])
    assert result['brier'] == .5
    assert math.isfinite(result['log_loss'])
    assert result['roc_auc'] is None
    assert result['average_precision'] is None
    assert set(result['unavailable']) == {'roc_auc', 'average_precision'}
    assert all(result['unavailable'].values())


def test_perfect_extreme_probabilities_are_valid():
    api = importlib.import_module('app.risk.metrics')
    result = api.probability_metrics([0, 1], [0, 1])
    assert result['brier'] == 0
    assert result['log_loss'] < 1e-12


def test_calibration_includes_empty_bins_and_p_one_in_last():
    api = importlib.import_module('app.risk.metrics')
    bins = api.calibration_bins([0, 1, 0, 1], [0, .1, .8, 1], n_bins=10)
    assert len(bins) == 10
    assert [b['count'] for b in bins] == [1, 1, 0, 0, 0, 0, 0, 0, 1, 1]
    assert bins[0] == dict(lower=0, upper=.1, count=1, mean_probability=0, event_rate=0)
    assert bins[2]['mean_probability'] is None and bins[2]['event_rate'] is None
    assert bins[-1]['upper'] == 1 and bins[-1]['event_rate'] == 1


def test_paired_company_bootstrap_uses_group_draws_not_individual_rows():
    api = importlib.import_module('app.risk.metrics')
    result = api.paired_brier_interval([0, 0, 1], [0, 0, 1], [.5, .5, 0],
                                      ['a', 'a', 'b'], seed=20261022, resamples=1000)
    assert result['difference'] == pytest.approx(-.5)
    assert result['lower'] == -1
    assert result['upper'] == -.25
    assert result['groups'] == 2
    assert result['resamples'] == 1000
    assert result == api.paired_brier_interval([0, 0, 1], [0, 0, 1], [.5, .5, 0],
                                             ['a', 'a', 'b'], seed=20261022)


@pytest.mark.parametrize('y,p', [([], []), ([0, 2], [.1, .2]), ([0], [float('nan')]),
                                ([0], [1.1]), ([0, 1], [.5]), ([[0]], [[.2]])])
def test_metric_boundaries_reject_invalid_inputs(y, p):
    api = importlib.import_module('app.risk.metrics')
    with pytest.raises(ValueError):
        api.probability_metrics(y, p)


def test_bootstrap_rejects_bad_groups_and_resample_count():
    api = importlib.import_module('app.risk.metrics')
    with pytest.raises(ValueError):
        api.paired_brier_interval([0, 1], [.2, .8], [.5, .5], ['one'])
    with pytest.raises(ValueError):
        api.paired_brier_interval([0, 1], [.2, .8], [.5, .5], ['a', 'b'], resamples=0)
    with pytest.raises(ValueError):
        api.calibration_bins([0], [.2], n_bins=0)
