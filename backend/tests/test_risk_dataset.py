import csv
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from app.risk.features import FEATURE_NAMES
from app.risk.synthetic import generate_loans


def dataset():
    from app.risk import dataset as module
    return module


def files(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def csv_rows(path):
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def test_split_groups_multiple_loans_per_company_and_ignores_input_order():
    loans = generate_loans(100)
    loans += [replace(loan, application_id=f'extra-{index}') for index, loan in enumerate(loans[:15])]
    before = random.getstate()
    split = dataset().split_by_company(loans, 17)
    assert random.getstate() == before
    assert split == dataset().split_by_company(list(reversed(loans)), 17)
    companies = {name: {loan.company_id for loan in part} for name, part in split.items()}
    assert {name: len(part) for name, part in companies.items()} == {'train': 70, 'validation': 15, 'test': 15}
    assert not companies['train'] & companies['validation']
    assert not companies['train'] & companies['test']
    assert not companies['validation'] & companies['test']
    assert sum(map(len, split.values())) == 115
    for part in split.values():
        assert part == sorted(part, key=lambda loan: (loan.company_id, loan.application_id))
    assert split != dataset().split_by_company(loans, 18)


def test_split_ten_thousand_companies_and_rejects_small_or_duplicate_inputs():
    loans = generate_loans(10000)
    split = dataset().split_by_company(loans, 20261021)
    assert {name: len(part) for name, part in split.items()} == {'train': 7000, 'validation': 1500, 'test': 1500}
    with pytest.raises(ValueError, match='20'):
        dataset().split_by_company(loans[:19], 1)
    with pytest.raises(ValueError, match='application_id'):
        dataset().split_by_company(loans[:20] + [loans[0]], 1)
    with pytest.raises(ValueError, match='seed'):
        dataset().split_by_company(loans[:20], True)


def test_export_has_whitelisted_columns_missing_masks_and_separate_audit(tmp_path):
    output = tmp_path / 'data'
    manifest = dataset().build_dataset(output, count=2000)
    assert set(files(output)) == {'train.csv', 'validation.csv', 'test.csv', 'observations.jsonl',
                                 'schema.json', 'report.json', 'manifest.json'}
    columns = ['company_id', 'application_id', *FEATURE_NAMES,
               *(f'{name}_missing' for name in FEATURE_NAMES), 'loan_90dpd_12m']
    missing_seen = False
    split_ids = {}
    for name, count in [('train', 1400), ('validation', 300), ('test', 300)]:
        names, rows = csv_rows(output / f'{name}.csv')
        assert names == columns
        assert len(rows) == count
        assert {row['product_code'] for row in rows} == {'working_capital', 'equipment'}
        assert {row['loan_90dpd_12m'] for row in rows} == {'0', '1'}
        split_ids[name] = {row['company_id'] for row in rows}
        for row in rows:
            for feature in FEATURE_NAMES:
                assert row[f'{feature}_missing'] == str(int(row[feature] == ''))
                missing_seen |= row[feature] == ''
                if feature != 'product_code' and row[feature]:
                    assert math.isfinite(float(row[feature]))
    assert missing_seen
    schema = json.loads((output / 'schema.json').read_text())
    assert schema['feature_columns'] == columns[2:-1]
    assert schema['metadata_columns'] == columns[:2]
    assert schema['target_column'] == 'loan_90dpd_12m'
    assert schema['data_kind'] == 'synthetic'
    audit = [json.loads(line) for line in (output / 'observations.jsonl').read_text().splitlines()]
    assert len(audit) == 2000
    assert audit[0]['data_kind'] == 'synthetic diagnostic'
    assert {'company_id', 'application_id', 'application', 'outcome', 'true_probability',
            'submitted_at', 'registered_at', 'overdue_days'} <= audit[0].keys()
    assert 'first_90dpd_date' in audit[0]['outcome']
    assert isinstance(audit[0]['application']['amount_kopecks'], int)
    report = json.loads((output / 'report.json').read_text())
    assert report['company_overlap_counts'] == {'train_validation': 0, 'train_test': 0, 'validation_test': 0}
    assert report['all_numeric_values_finite'] is True
    for name in split_ids:
        part = report['splits'][name]
        assert part['rows'] == part['unique_companies'] == len(split_ids[name])
        assert part['events'] > 0
        assert 0 < part['event_rate'] < 1
        assert sum(part['products'].values()) == part['rows']
        assert sum(part['term_months'].values()) == part['rows']
        assert set(part['missing']) == set(FEATURE_NAMES)
    assert manifest == json.loads((output / 'manifest.json').read_text())
    assert manifest['count'] == 2000
    assert manifest['seed'] == 20261021
    assert manifest['catalog_version'] == 'demo-v1'
    assert manifest['horizon']['months'] == 12
    assert set(manifest['sha256']) == set(files(output)) - {'manifest.json'}
    for name, digest in manifest['sha256'].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


def test_same_seed_is_byte_identical_and_different_seed_changes_data(tmp_path):
    for name, seed in [('first', 1), ('second', 1), ('third', 2)]:
        dataset().build_dataset(tmp_path / name, count=100, seed=seed)
    assert files(tmp_path / 'first') == files(tmp_path / 'second')
    assert files(tmp_path / 'first')['train.csv'] != files(tmp_path / 'third')['train.csv']


@pytest.mark.parametrize('kind', ['directory', 'file', 'symlink'])
def test_existing_destination_is_untouched_before_generation(tmp_path, monkeypatch, kind):
    output = tmp_path / 'data'
    if kind == 'directory':
        output.mkdir()
        (output / 'sentinel').write_bytes(b'preserve')
    elif kind == 'file':
        output.write_bytes(b'preserve')
    else:
        output.symlink_to(tmp_path / 'absent')
    def forbidden(*args, **kwargs):
        pytest.fail('Генерация при существующем пути запрещена')
    monkeypatch.setattr(dataset(), 'generate_loans', forbidden)
    with pytest.raises(FileExistsError):
        dataset().build_dataset(output)
    assert output.is_symlink() if kind == 'symlink' else (
        (output / 'sentinel').read_bytes() == b'preserve' if kind == 'directory' else output.read_bytes() == b'preserve')
    assert sorted(path.name for path in tmp_path.iterdir()) == ['data']


@pytest.mark.parametrize('invalid', ['censored', 'nonfinite', 'mask'])
def test_invalid_observation_aborts_without_publishing_or_leaving_temporary_files(tmp_path, monkeypatch, invalid):
    loans = generate_loans(20)
    loan = loans[0]
    if invalid == 'censored':
        loan = replace(loan, outcome=replace(loan.outcome, first_90dpd_date=None, fully_repaid_date=None,
                                           observed_through=loan.submitted_at + timedelta(days=30)))
    else:
        values = dict(loan.features.values)
        masks = dict(loan.features.missing_mask)
        if invalid == 'nonfinite':
            values['monthly_revenue_rub'] = math.inf
        else:
            masks['monthly_revenue_rub'] = True
        loan = replace(loan, features=replace(loan.features, values=values, missing_mask=masks))
    loans[0] = loan
    monkeypatch.setattr(dataset(), 'generate_loans', lambda *args, **kwargs: loans)
    with pytest.raises(ValueError):
        dataset().build_dataset(tmp_path / 'data', count=20)
    assert list(tmp_path.iterdir()) == []


def test_whitelist_does_not_export_extra_feature_fields(tmp_path, monkeypatch):
    loans = generate_loans(20)
    loan = loans[0]
    loans[0] = replace(loan, features=replace(loan.features, values={**loan.features.values, 'decision': 'approved'}))
    monkeypatch.setattr(dataset(), 'generate_loans', lambda *args, **kwargs: loans)
    dataset().build_dataset(tmp_path / 'data', count=20)
    for name in ('train', 'validation', 'test'):
        header, _ = csv_rows(tmp_path / 'data' / f'{name}.csv')
        assert 'decision' not in header


def test_small_sample_reports_absent_classes_without_regeneration(tmp_path, monkeypatch):
    loans = generate_loans(20)
    loans = [replace(loan, outcome=replace(loan.outcome, first_90dpd_date=None)) for loan in loans]
    monkeypatch.setattr(dataset(), 'generate_loans', lambda *args, **kwargs: loans)
    dataset().build_dataset(tmp_path / 'data', count=20)
    report = json.loads((tmp_path / 'data' / 'report.json').read_text())
    assert all(part['events'] == 0 and part['event_rate'] == 0 for part in report['splits'].values())
    assert all(part['class_counts']['1'] == 0 for part in report['splits'].values())


def test_write_failure_removes_only_own_temporary_directory(tmp_path, monkeypatch):
    unrelated = tmp_path / '.data-unrelated'
    unrelated.mkdir()
    (unrelated / 'keep').write_text('keep')
    original = Path.open
    def fail_report(path, *args, **kwargs):
        if path.name == 'report.json':
            raise OSError('Нет места')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail_report)
    with pytest.raises(OSError, match='Нет места'):
        dataset().build_dataset(tmp_path / 'data', count=20)
    assert list(tmp_path.iterdir()) == [unrelated]
    assert (unrelated / 'keep').read_text() == 'keep'


def test_cli_runs_without_application_environment_and_rejects_overwrite(tmp_path):
    env = {key: value for key, value in os.environ.items() if key not in ('DATABASE_URL', 'DEMO_PASSWORD')}
    command = [sys.executable, '-m', 'app.risk', 'build-data', '--output', str(tmp_path / 'data'),
               '--rows', '20', '--seed', '20261021']
    run = subprocess.run(command, capture_output=True, text=True, env=env)
    assert run.returncode == 0, run.stderr
    assert str(tmp_path / 'data') in run.stdout
    assert '20' in run.stdout and 'train=14' in run.stdout and 'validation=3' in run.stdout and 'test=3' in run.stdout
    before = files(tmp_path / 'data')
    repeat = subprocess.run(command, capture_output=True, text=True, env=env)
    assert repeat.returncode != 0
    assert 'Ошибка' in repeat.stderr and 'Traceback' not in repeat.stderr
    assert files(tmp_path / 'data') == before
    invalid_output = tmp_path / 'invalid-size'
    invalid_command = [sys.executable, '-m', 'app.risk', 'build-data', '--output', str(invalid_output),
                       '--rows', '0', '--seed', '20261021']
    invalid = subprocess.run(invalid_command, capture_output=True, text=True, env=env)
    assert invalid.returncode != 0
    assert 'count' in invalid.stderr and 'положительное целое число' in invalid.stderr
    assert not invalid_output.exists()
