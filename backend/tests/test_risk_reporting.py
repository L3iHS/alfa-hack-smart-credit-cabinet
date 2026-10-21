"""Отчёт читает сохранённую оценку и не переобучает и не меняет выбор."""

import importlib
import json
import shutil

import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('catboost')

from app.risk.artifacts import sha256, write_json
from app.risk.dataset import build_dataset
from app.risk.experiment import train_experiment, evaluate_experiment
from app.risk.training_data import DatasetReader


@pytest.fixture(scope='module')
def evaluated(tmp_path_factory):
    root = tmp_path_factory.mktemp('reporting')
    build_dataset(root / 'data', count=120, seed=20261021)
    train_experiment(root / 'data', root / 'run')
    evaluate_experiment(root / 'data', root / 'run')
    return root


@pytest.fixture
def local_run(evaluated, tmp_path):
    shutil.copytree(evaluated / 'data', tmp_path / 'data')
    shutil.copytree(evaluated / 'run', tmp_path / 'run')
    return tmp_path / 'data', tmp_path / 'run'


def snapshot(root):
    return {p.relative_to(root).as_posix(): sha256(p) for p in root.rglob('*') if p.is_file()}


def test_report_preserves_selection_uses_saved_metrics_and_fixed_validation_examples(local_run, monkeypatch):
    module = importlib.import_module('app.risk.reporting')
    data, run = local_run
    before = snapshot(run)
    original_split = DatasetReader.split

    def validation_only(self, name):
        assert name == 'validation', 'Отчёт не открывает test как модельную таблицу'
        return original_split(self, name)

    monkeypatch.setattr(DatasetReader, 'split', validation_only)
    import app.risk.estimators as estimators
    monkeypatch.setattr(estimators, 'fit_candidate', lambda *a, **k: pytest.fail('Отчёт не обучает'))
    result = module.build_report(data, run)
    assert all(sha256(run / name) == digest for name, digest in before.items())
    selection = json.loads((run / 'selection.json').read_text())
    assert result['selected_candidate_id'] == selection['selected_candidate_id']
    assert result['validation'] == json.loads((run / 'validation.json').read_text())
    assert result['test'] == json.loads((run / 'evaluation/metrics.json').read_text())
    analysis = run / 'analysis'
    assert {p.name for p in analysis.iterdir()} == {'comparison.md', 'explanations.json', 'calibration.png',
        'calibration.svg', 'ranking.png', 'ranking.svg', 'manifest.json'}
    payload = json.loads((analysis / 'explanations.json').read_text())
    expected = sorted(original_split(DatasetReader(data), 'validation').metadata.application_id)[:5]
    assert [row['application_id'] for row in payload['examples']] == expected
    assert all(len(row['inputs']) == 18 for row in payload['examples'])
    assert set(payload['models']) == {selection['family_winners']['logistic'], selection['family_winners']['catboost']}
    assert all(record['latency_seconds'] >= 0 for record in payload['models'].values())
    manifest = json.loads((analysis / 'manifest.json').read_text())
    assert manifest['sources']['run_manifest_sha256'] == sha256(run / 'manifest.json')
    assert manifest['sources']['evaluation_manifest_sha256'] == sha256(run / 'evaluation/manifest.json')
    assert all(sha256(analysis / name) == digest for name, digest in manifest['sha256'].items())
    # Числа в таблице взяты из сохранённых двух частей, даже если победил baseline.
    text = (analysis / 'comparison.md').read_text()
    for split in (result['validation'], result['test']):
        for record in split['models'].values():
            assert f"{record['metrics']['brier']:.6f}" in text
    assert selection['selected_candidate_id'] in text
    saved = snapshot(analysis)
    with pytest.raises(FileExistsError):
        module.build_report(data, run)
    assert snapshot(analysis) == saved


@pytest.mark.parametrize('damage', ['prediction', 'parent', 'selection', 'extra_hash', 'symlink', 'metrics'])
def test_report_rejects_damaged_evaluation_without_analysis(local_run, damage):
    module = importlib.import_module('app.risk.reporting')
    data, run = local_run
    evaluation = run / 'evaluation'
    manifest = json.loads((evaluation / 'manifest.json').read_text())
    if damage == 'prediction':
        (evaluation / 'predictions.csv').write_text('broken')
    elif damage == 'parent':
        manifest['parent_manifest_sha256'] = '0' * 64
    elif damage == 'selection':
        manifest['selected_candidate_id'] = 'not-selected'
    elif damage == 'extra_hash':
        manifest['sha256']['../selection.json'] = sha256(run / 'selection.json')
    elif damage == 'symlink':
        (evaluation / 'predictions.csv').rename(evaluation / 'moved.csv')
        (evaluation / 'predictions.csv').symlink_to(evaluation / 'moved.csv')
    else:
        metrics = json.loads((evaluation / 'metrics.json').read_text())
        next(iter(metrics['models'].values()))['metrics']['brier'] = .999
        write_json(evaluation / 'metrics.json', metrics)
        manifest['sha256']['metrics.json'] = sha256(evaluation / 'metrics.json')
    write_json(evaluation / 'manifest.json', manifest)
    with pytest.raises(ValueError):
        module.build_report(data, run)
    assert not (run / 'analysis').exists()


def test_plot_data_keeps_empty_bins_out_and_constant_pr_horizontal(local_run):
    module = importlib.import_module('app.risk.reporting')
    _, run = local_run
    evaluation = json.loads((run / 'evaluation/metrics.json').read_text())
    import pandas as pd
    predictions = pd.read_csv(run / 'evaluation/predictions.csv')
    figures = module.report_figures(evaluation, predictions)
    calibration, ranking = figures
    # Baseline: единственная непустая точка; счётчики отдельно от калибровки.
    assert len(calibration.axes) == 2
    assert len(calibration.axes[0].lines[1].get_xdata()) == 1
    baseline = next(line for line in ranking.axes[1].lines if 'baseline' in line.get_label())
    np.testing.assert_allclose(baseline.get_ydata(), predictions['loan_90dpd_12m'].mean())
    import matplotlib.pyplot as plt
    for figure in figures:
        plt.close(figure)


def test_top_factors_do_not_invent_an_empty_direction():
    module = importlib.import_module('app.risk.reporting')
    explanation = dict(feature_names=['overdue_days', 'term_months'], contributions=[[.5, 0]])
    assert 'Текущая просрочка' in module._top_factors(explanation, 0, True)
    assert module._top_factors(explanation, 0, False) == 'нет ненулевых вкладов'
