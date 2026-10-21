"""Границы эксперимента проверяются на отдельном наборе из 120 компаний."""

import csv
import importlib
import json
import shutil
from pathlib import Path

import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('catboost')

from app.risk.dataset import build_dataset
from app.risk.labels import TARGET_EVENT
from app.risk.training_data import MODEL_FEATURES


def api():
    return importlib.import_module('app.risk.experiment')


def artifacts():
    return importlib.import_module('app.risk.artifacts')


@pytest.fixture(scope='module')
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp('experiment')
    data = root / 'data'
    build_dataset(data, count=120, seed=20261021)
    api().train_experiment(data, root / 'run')
    return root


@pytest.fixture
def local_run(trained, tmp_path):
    shutil.copytree(trained / 'data', tmp_path / 'data')
    shutil.copytree(trained / 'run', tmp_path / 'run')
    return tmp_path / 'data', tmp_path / 'run'


def test_training_reads_only_train_validation_and_fits_only_train(tmp_path, monkeypatch):
    experiment = api()
    data = tmp_path / 'data'
    build_dataset(data, count=120, seed=20261021)
    split = experiment.DatasetReader.split
    fit = experiment.fit_candidate
    calls = []

    def guarded_split(self, name):
        assert name != 'test'
        calls.append(name)
        return split(self, name)

    def guarded_fit(spec, train, **kwargs):
        assert train.name == 'train' and len(train.y) == 84
        assert tuple(train.X.columns) == MODEL_FEATURES
        assert not {'company_id', 'application_id', TARGET_EVENT, 'true_probability'} & set(train.X.columns)
        assert kwargs == dict(seed=20261021, threads=2)
        return fit(spec, train, **kwargs)

    monkeypatch.setattr(experiment.DatasetReader, 'split', guarded_split)
    monkeypatch.setattr(experiment, 'fit_candidate', guarded_fit)
    result = experiment.train_experiment(data, tmp_path / 'run')
    assert calls == ['train', 'validation']
    assert len(result['scores']) == 6
    assert result['test_used'] is False and result['selected_on'] == 'validation'


def test_selection_global_min_tolerance_and_exact_ties():
    experiment = api()
    scores = [dict(candidate_id=spec.candidate_id, family=spec.family, params=spec.params,
                   brier=brier) for spec, brier in zip(experiment.default_candidates(),
                                                      [.1015, .1009, .1008, .1008, .1005, .1])]
    selection = experiment.select_candidates(scores)
    assert selection['family_winners'] == dict(constant='baseline', logistic='lr_c1', catboost='cat_d6')
    assert selection['selected_candidate_id'] == 'lr_c1'
    scores[0]['brier'] = .101
    assert experiment.select_candidates(scores)['selected_candidate_id'] == 'baseline'
    scores[4]['brier'] = .1
    assert experiment.select_candidates(scores)['family_winners']['catboost'] == 'cat_d4'


def test_test_changes_cannot_affect_selection(trained, tmp_path):
    shutil.copytree(trained / 'data', tmp_path / 'data')
    path = tmp_path / 'data' / 'test.csv'
    rows = list(csv.DictReader(path.open()))
    for row in rows:
        row[TARGET_EVENT] = 'invalid-unused-label'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads((tmp_path / 'data' / 'manifest.json').read_text())
    manifest['sha256']['test.csv'] = artifacts().sha256(path)
    artifacts().write_json(tmp_path / 'data' / 'manifest.json', manifest)
    new = api().train_experiment(tmp_path / 'data', tmp_path / 'run')
    assert new == json.loads((trained / 'run' / 'selection.json').read_text())
    first = np.genfromtxt(trained / 'run' / 'validation-predictions.csv', delimiter=',', names=True, dtype=None, encoding='utf8')
    second = np.genfromtxt(tmp_path / 'run' / 'validation-predictions.csv', delimiter=',', names=True, dtype=None, encoding='utf8')
    for column in new['family_winners'].values():
        np.testing.assert_allclose(first[column], second[column], atol=1e-10, rtol=0)


def test_manifest_and_load_run_preserve_provenance_without_current_source_equality(local_run, monkeypatch):
    data, run = local_run
    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['source_sha256'] and manifest['libraries'] and manifest['python']
    assert manifest['model_features'] == list(MODEL_FEATURES)
    assert len(manifest['sha256']) == 6
    assert manifest['resources']['max_rss_bytes'] > 0
    monkeypatch.setattr(artifacts(), 'source_hashes', lambda: {'new_reporting.py': 'changed'})
    reader, selection, models = artifacts().load_run(data, run)
    assert set(models) == set(selection['family_winners'].values())
    assert reader.fingerprint == manifest['dataset_manifest_sha256']
    validation = json.loads((run / 'validation.json').read_text())
    assert all(record['fit_seconds'] >= 0 and record['predict_seconds'] >= 0 and record['size_bytes'] > 0
               for record in validation['models'].values())


@pytest.mark.parametrize('kind', ['model', 'missing_hash', 'extra_hash', 'protocol', 'features', 'libraries',
                                 'dataset', 'family', 'selection', 'symlink'])
def test_damage_rejected_before_deserialization(local_run, monkeypatch, kind):
    data, run = local_run
    module = artifacts()
    manifest = json.loads((run / 'manifest.json').read_text())
    if kind == 'model':
        next((run / 'models').glob('*.joblib')).write_bytes(b'broken')
    elif kind == 'missing_hash':
        manifest['sha256'].pop('selection.json')
    elif kind == 'extra_hash':
        manifest['sha256']['../secret'] = '0' * 64
    elif kind == 'protocol':
        manifest['protocol_version'] = 'unknown'
    elif kind == 'features':
        manifest['model_features'].reverse()
    elif kind == 'libraries':
        manifest['libraries']['scikit-learn'] = '0.0'
    elif kind == 'dataset':
        manifest['dataset_manifest_sha256'] = '0' * 64
    elif kind in ('family', 'selection'):
        file = run / ('validation.json' if kind == 'family' else 'selection.json')
        payload = json.loads(file.read_text())
        if kind == 'family':
            next(iter(payload['models'].values()))['family'] = 'logistic'
        else:
            payload['selected_candidate_id'] = 'not-a-winner'
        module.write_json(file, payload)
        manifest['sha256'][file.name] = module.sha256(file)
    else:
        model_dir = run / 'models'
        model_dir.rename(run / 'moved-models')
        model_dir.symlink_to(run / 'moved-models', target_is_directory=True)
    module.write_json(run / 'manifest.json', manifest)
    monkeypatch.setattr(module, 'load_candidate', lambda *a, **k: pytest.fail('Нельзя десериализовать повреждённый run'))
    with pytest.raises(ValueError):
        module.load_run(data, run)


def test_evaluation_opens_test_after_selection_never_refits_and_cannot_repeat(local_run, monkeypatch):
    data, run = local_run
    experiment = api()
    original = (run / 'selection.json').read_bytes()
    parent = {name: artifacts().sha256(run / name) for name in json.loads((run / 'manifest.json').read_text())['sha256']}
    split = experiment.DatasetReader.split
    calls = []

    def guarded_split(self, name):
        assert json.loads((run / 'selection.json').read_text())['test_used'] is False
        calls.append(name)
        return split(self, name)

    monkeypatch.setattr(experiment.DatasetReader, 'split', guarded_split)
    monkeypatch.setattr(experiment, 'fit_candidate', lambda *a, **k: pytest.fail('Оценка не обучает модели'))
    result = experiment.evaluate_experiment(data, run)
    assert calls == ['test']
    assert result['selected_candidate_id'] == json.loads(original)['selected_candidate_id']
    assert result['split'] == 'test' and len(result['models']) == 3
    assert result['paired_brier_interval']['resamples'] == 1000
    assert result['limitations']
    assert (run / 'selection.json').read_bytes() == original
    assert all(artifacts().sha256(run / name) == digest for name, digest in parent.items())
    evaluation = run / 'evaluation'
    before = {p.name: p.read_bytes() for p in evaluation.iterdir()}
    manifest = json.loads((evaluation / 'manifest.json').read_text())
    assert manifest['parent_manifest_sha256'] == artifacts().sha256(run / 'manifest.json')
    with pytest.raises(FileExistsError):
        experiment.evaluate_experiment(data, run)
    assert before == {p.name: p.read_bytes() for p in evaluation.iterdir()}
    assert calls == ['test']


@pytest.mark.parametrize('kind', ['directory', 'file', 'symlink', 'dangling'])
def test_existing_output_is_never_modified(trained, tmp_path, kind):
    output = tmp_path / 'run'
    if kind == 'directory':
        output.mkdir()
    elif kind == 'file':
        output.write_text('keep')
    else:
        output.symlink_to(tmp_path / ('target' if kind == 'dangling' else 'file'))
        if kind == 'symlink':
            (tmp_path / 'file').write_text('keep')
    with pytest.raises(FileExistsError):
        api().train_experiment(trained / 'data', output)
    assert output.is_symlink() if kind in ('symlink', 'dangling') else output.exists()
    if kind == 'file':
        assert output.read_text() == 'keep'


def test_failed_save_cleans_only_own_staging(trained, tmp_path, monkeypatch):
    unrelated = tmp_path / '.run-unrelated'
    unrelated.mkdir()
    (unrelated / 'keep').write_text('keep')
    monkeypatch.setattr(api(), 'save_candidate', lambda *a: (_ for _ in ()).throw(OSError('save failed')))
    with pytest.raises(OSError, match='save failed'):
        api().train_experiment(trained / 'data', tmp_path / 'run')
    assert list(tmp_path.iterdir()) == [unrelated]


def test_json_rejects_nonfinite_values(tmp_path):
    with pytest.raises(ValueError):
        artifacts().write_json(tmp_path / 'bad.json', {'metric': float('nan')})


def test_atomic_publication_does_not_replace_racing_output(tmp_path):
    output = tmp_path / 'run'
    with pytest.raises(FileExistsError):
        with artifacts().atomic_directory(output) as staging:
            (staging / 'own-file').write_text('own')
            output.mkdir()
            (output / 'other-file').write_text('other')
    assert {p.name for p in output.iterdir()} == {'other-file'}
    assert {p.name for p in tmp_path.iterdir()} == {'run'}


def test_failed_evaluation_keeps_parent_and_removes_staging(local_run, monkeypatch):
    data, run = local_run
    before = {p.relative_to(run).as_posix(): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    monkeypatch.setattr(api(), '_write_predictions', lambda *a: (_ for _ in ()).throw(OSError('disk failed')))
    with pytest.raises(OSError, match='disk failed'):
        api().evaluate_experiment(data, run)
    assert before == {p.relative_to(run).as_posix(): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    assert not list(run.glob('.evaluation-*'))


def test_load_rejects_prediction_column_order_before_deserialization(local_run, monkeypatch):
    data, run = local_run
    path = run / 'validation-predictions.csv'
    lines = path.read_text().splitlines()
    columns = lines[0].split(',')
    columns[-1], columns[-2] = columns[-2], columns[-1]
    lines[0] = ','.join(columns)
    path.write_text('\n'.join(lines) + '\n')
    manifest = json.loads((run / 'manifest.json').read_text())
    manifest['sha256'][path.name] = artifacts().sha256(path)
    artifacts().write_json(run / 'manifest.json', manifest)
    monkeypatch.setattr(artifacts(), 'load_candidate', lambda *a: pytest.fail('Нельзя загружать при неверном порядке колонок'))
    with pytest.raises(ValueError, match='порядок колонок'):
        artifacts().load_run(data, run)


def test_evaluation_bad_selection_never_opens_test(local_run, monkeypatch):
    data, run = local_run
    (run / 'selection.json').write_text('{}')
    monkeypatch.setattr(api().DatasetReader, 'split', lambda *a: pytest.fail('Нельзя читать test до проверки выбора'))
    with pytest.raises(ValueError):
        api().evaluate_experiment(data, run)


@pytest.mark.parametrize('kind', ['provenance', 'metrics', 'size'])
def test_malformed_metadata_rejected_as_value_error_before_load(local_run, monkeypatch, kind):
    data, run = local_run
    manifest = json.loads((run / 'manifest.json').read_text())
    if kind == 'provenance':
        manifest.pop('source_sha256')
    else:
        path = run / 'validation.json'
        report = json.loads(path.read_text())
        record = next(iter(report['models'].values()))
        record['metrics' if kind == 'metrics' else 'size_bytes'] = [] if kind == 'metrics' else 0
        artifacts().write_json(path, report)
        manifest['sha256'][path.name] = artifacts().sha256(path)
    artifacts().write_json(run / 'manifest.json', manifest)
    monkeypatch.setattr(artifacts(), 'load_candidate', lambda *a: pytest.fail('Нельзя загружать при неполном manifest'))
    with pytest.raises(ValueError):
        artifacts().load_run(data, run)


def test_validation_report_keeps_metrics_and_calibration_for_all_six(trained):
    report = json.loads((trained / 'run' / 'validation.json').read_text())
    assert set(report['candidate_metrics']) == {s.candidate_id for s in api().default_candidates()}
    for result in report['candidate_metrics'].values():
        assert set(result['metrics']) == {'n', 'events', 'prevalence', 'brier', 'log_loss',
                                          'roc_auc', 'average_precision', 'unavailable'}
        assert len(result['calibration']) == 10
        assert sum(b['count'] for b in result['calibration']) == result['metrics']['n']
