"""Проверки доверенного offline-экспорта без обучения или обращения к test."""

import hashlib
import os
from pathlib import Path

import pytest

from app.risk import export_runtime


def test_untrusted_manifest_is_rejected_before_any_deserialization(tmp_path):
    data, run = tmp_path / 'data', tmp_path / 'run'
    data.mkdir()
    run.mkdir()
    (data / 'manifest.json').write_text('{}')
    (run / 'manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='SHA256'):
        export_runtime.export_runtime(data, run, tmp_path / 'output.json')
    assert not (tmp_path / 'output.json').exists()


def test_symlink_run_is_rejected(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        export_runtime.export_runtime(target, link, tmp_path / 'output.json')


def test_saved_validation_export_matches_accepted_pipeline_without_fit_or_test(tmp_path, monkeypatch):
    data_dir, run_dir = os.environ.get('RISK_RUNTIME_DATA'), os.environ.get('RISK_RUNTIME_RUN')
    if not data_dir or not run_dir:
        pytest.skip('Нужны readonly принятые артефакты RISK_RUNTIME_DATA/RISK_RUNTIME_RUN и extra ml')
    pytest.importorskip('sklearn', reason='Offline parity требует extra ml')
    from sklearn.pipeline import Pipeline
    from app.risk.training_data import DatasetReader

    def forbidden_fit(*args, **kwargs):
        raise AssertionError('Экспорт не должен обучать модель')

    original_split = DatasetReader.split

    def validation_only(self, name):
        assert name == 'validation', 'Экспорт не должен открывать train/test как модельную таблицу'
        return original_split(self, name)

    monkeypatch.setattr(Pipeline, 'fit', forbidden_fit)
    monkeypatch.setattr(DatasetReader, 'split', validation_only)
    paths = [Path(data_dir) / 'manifest.json', Path(run_dir) / 'manifest.json',
             Path(run_dir) / 'models/lr_c1.joblib']
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    output = tmp_path / 'logistic-risk-v1.json'
    result = export_runtime.export_runtime(Path(data_dir), Path(run_dir), output)
    assert result['rows'] == 1500
    assert result['probability_max_abs_error'] <= 1e-10
    assert result['contribution_max_abs_error'] <= 1e-8
    assert result['raw_max_abs_error'] <= 1e-8
    assert result['test_used'] is False
    delivered = Path(export_runtime.runtime.__file__).with_name('models') / 'logistic-risk-v1.json'
    assert output.read_bytes() == delivered.read_bytes()
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths] == before
    with pytest.raises(ValueError, match='уже существует'):
        export_runtime.export_runtime(Path(data_dir), Path(run_dir), output)
