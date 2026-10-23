"""Проверки границы между экспортом данных и входами обучения."""

import csv
import hashlib
import importlib
import json

import pytest

np = pytest.importorskip('numpy')
pd = pytest.importorskip('pandas')
pytest.importorskip('sklearn')
pytest.importorskip('catboost')

from app.risk.dataset import build_dataset
from app.risk.features import FEATURE_NAMES
from app.risk.labels import TARGET_EVENT


@pytest.fixture
def dataset_dir(tmp_path):
    path = tmp_path / 'data'
    build_dataset(path, count=40, seed=20261021)
    return path


def rewrite_json(path, update):
    value = json.loads(path.read_text())
    update(value)
    path.write_text(json.dumps(value))


def rehash(path, name):
    rewrite_json(path / 'manifest.json', lambda value: value['sha256'].update(
        {name: hashlib.sha256((path / name).read_bytes()).hexdigest()}))


def rewrite_csv(path, name, update):
    file = path / f'{name}.csv'
    with file.open(newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    update(fields, rows)
    with file.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    rehash(path, file.name)


def test_reader_exposes_only_features_and_masks_and_separate_metadata(dataset_dir):
    api = importlib.import_module('app.risk.training_data')
    reader = api.DatasetReader(dataset_dir)
    train = reader.split('train')
    assert train.name == 'train'
    assert tuple(train.X.columns) == (*FEATURE_NAMES, *(f'{n}_missing' for n in FEATURE_NAMES))
    assert tuple(train.metadata.columns) == ('company_id', 'application_id')
    assert train.y.shape == (28,)
    assert set(train.y) == {0, 1}
    assert reader.fingerprint == hashlib.sha256((dataset_dir / 'manifest.json').read_bytes()).hexdigest()
    assert reader.manifest['dataset_version'] == 'risk-dataset-v1'
    assert reader.manifest['catalog_version'] == 'demo-v1'
    assert reader.schema['target'] == TARGET_EVENT
    assert 'true_probability' not in train.X
    assert 'company_id' not in train.X
    with pytest.raises(ValueError):
        reader.split('../observations')


@pytest.mark.parametrize('kind', ['hash', 'schema', 'version', 'path', 'extra_file'])
def test_reader_rejects_broken_contract_at_initialization(dataset_dir, kind):
    api = importlib.import_module('app.risk.training_data')
    if kind == 'hash':
        with (dataset_dir / 'train.csv').open('a') as stream:
            stream.write('\n')
    elif kind == 'schema':
        rewrite_json(dataset_dir / 'schema.json', lambda v: v['feature_columns'].append('future'))
        rehash(dataset_dir, 'schema.json')
    elif kind == 'version':
        rewrite_json(dataset_dir / 'manifest.json', lambda v: v.update(target_version='unknown'))
    elif kind == 'path':
        rewrite_json(dataset_dir / 'manifest.json', lambda v: v['sha256'].update({'../secret': '0' * 64}))
    else:
        rewrite_csv(dataset_dir, 'train', lambda f, rows: (f.append('future'), rows[0].update(future=1)))
    with pytest.raises(ValueError):
        api.DatasetReader(dataset_dir)


@pytest.mark.parametrize('column,value', [
    ('operating_margin_ratio_missing', '1'), ('overdue_days_missing', '2'),
    ('overdue_days', 'inf'), ('term_months', '1.5'), ('product_code', 'unknown'),
    (TARGET_EVENT, '2'), ('business_age_months', ''),
])
def test_reader_rejects_invalid_feature_mask_or_target(dataset_dir, column, value):
    api = importlib.import_module('app.risk.training_data')
    def corrupt(fields, rows):
        if column == 'operating_margin_ratio_missing':
            rows[0]['operating_margin_ratio'] = '0.5'
        rows[0][column] = value
    rewrite_csv(dataset_dir, 'train', corrupt)
    reader = api.DatasetReader(dataset_dir)
    with pytest.raises(ValueError):
        reader.split('train')


def test_missing_ratios_are_nan_with_fixed_mask(dataset_dir):
    api = importlib.import_module('app.risk.training_data')
    rewrite_csv(dataset_dir, 'train', lambda f, rows: rows[0].update(
        monthly_revenue_rub='0', operating_margin_ratio='', operating_margin_ratio_missing='1',
        existing_debt_to_revenue_ratio='', existing_debt_to_revenue_ratio_missing='1'))
    train = api.DatasetReader(dataset_dir).split('train')
    assert np.isnan(train.X.iloc[0]['operating_margin_ratio'])
    assert train.X.iloc[0]['operating_margin_ratio_missing'] == 1


@pytest.mark.parametrize('column', ['company_id', 'application_id'])
def test_reader_rejects_overlap_or_duplicate_application(dataset_dir, column):
    api = importlib.import_module('app.risk.training_data')
    with (dataset_dir / 'train.csv').open() as stream:
        first = next(csv.DictReader(stream))[column]
    rewrite_csv(dataset_dir, 'validation', lambda f, rows: rows[0].update({column: first}))
    with pytest.raises(ValueError):
        api.DatasetReader(dataset_dir)


def test_development_reader_does_not_parse_test_target_or_future_diagnostics(dataset_dir):
    api = importlib.import_module('app.risk.training_data')
    rewrite_csv(dataset_dir, 'test', lambda f, rows: rows[0].update({TARGET_EVENT: 'not-opened'}))
    (dataset_dir / 'observations.jsonl').write_text('audit content, not a model table')
    rehash(dataset_dir, 'observations.jsonl')
    reader = api.DatasetReader(dataset_dir)
    assert len(reader.split('train').y) == 28
    with pytest.raises(ValueError):
        reader.split('test')


def test_multiple_applications_for_same_company_remain_valid_within_split(dataset_dir):
    api = importlib.import_module('app.risk.training_data')
    rewrite_csv(dataset_dir, 'train', lambda f, rows: rows[0].update(company_id=rows[1]['company_id']))
    reader = api.DatasetReader(dataset_dir)
    assert len(reader.split('train').X) == 28
