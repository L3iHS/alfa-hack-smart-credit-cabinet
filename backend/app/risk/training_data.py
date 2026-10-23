"""Проверка опубликованного набора и выделение разрешённых входов модели."""

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app.risk.catalog import ML_CATALOG_VERSION as CATALOG_VERSION, ML_PRODUCTS as PRODUCTS
from app.risk.dataset import DATASET_VERSION, TARGET_VERSION, _HORIZON, _schema
from app.risk.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from app.risk.labels import TARGET_EVENT
from app.risk.synthetic import GENERATOR_VERSION

MASK_FEATURES = tuple(f'{name}_missing' for name in FEATURE_NAMES)
MODEL_FEATURES = (*FEATURE_NAMES, *MASK_FEATURES)
_SPLITS = ('train', 'validation', 'test')
_METADATA = ('company_id', 'application_id')
_FILES = ('train.csv', 'validation.csv', 'test.csv', 'observations.jsonl', 'schema.json', 'report.json')


@dataclass
class DataSplit:
    name: str
    X: pd.DataFrame
    y: np.ndarray
    metadata: pd.DataFrame


class DatasetReader:
    """Проверяет целостность всех файлов, а значения читает только по явному split."""

    def __init__(self, path: Path):
        self.path = Path(path)
        manifest_path = self.path / 'manifest.json'
        if manifest_path.is_symlink():
            raise ValueError('Манифест не должен быть символической ссылкой')
        manifest_bytes = manifest_path.read_bytes()
        self.fingerprint = hashlib.sha256(manifest_bytes).hexdigest()
        self.manifest = json.loads(manifest_bytes)
        expected = dict(dataset_version=DATASET_VERSION, target_version=TARGET_VERSION,
                        feature_schema_version=FEATURE_SCHEMA_VERSION, generator_version=GENERATOR_VERSION,
                        catalog_version=CATALOG_VERSION, target=TARGET_EVENT,
                        horizon=_HORIZON, data_kind='synthetic')
        if not isinstance(self.manifest, dict) or any(self.manifest.get(k) != v for k, v in expected.items()):
            raise ValueError('Несовместимые версии или определение цели в manifest')
        hashes = self.manifest.get('sha256')
        if not isinstance(hashes, dict) or set(hashes) != set(_FILES):
            raise ValueError('Нужен точный список файлов sha256 без произвольных путей')
        for name in _FILES:
            file = self.path / name
            if file.is_symlink() or not file.is_file():
                raise ValueError(f'{name}: нужен обычный файл набора')
            if hashlib.sha256(file.read_bytes()).hexdigest() != hashes[name]:
                raise ValueError(f'{name}: sha256 не совпадает')
        self.schema = json.loads((self.path / 'schema.json').read_text(encoding='utf-8'))
        if self.schema != _schema():
            raise ValueError('Схема не соответствует разрешённым столбцам и типам')
        companies = {}
        applications = set()
        count = 0
        for name in _SPLITS:
            companies[name] = set()
            # При инициализации не преобразуем признаки и метки, включая test.
            for row in self._rows(name):
                company, application = (row[key] for key in _METADATA)
                if not company or not application or application in applications:
                    raise ValueError('Пустой ID или повторяющийся application_id')
                companies[name].add(company)
                applications.add(application)
                count += 1
        if any(companies[left] & companies[right] for left, right in
               (('train', 'validation'), ('train', 'test'), ('validation', 'test'))):
            raise ValueError('Компании пересекаются между частями')
        if type(self.manifest.get('count')) is not int or self.manifest['count'] != count:
            raise ValueError('Число строк не совпадает с manifest')

    def _rows(self, name):
        with (self.path / f'{name}.csv').open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != self.schema['csv_columns']:
                raise ValueError(f'{name}: нарушен состав или порядок CSV столбцов')
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f'{name}: нарушена длина строки CSV')
                yield row

    def split(self, name: str) -> DataSplit:
        if name not in _SPLITS:
            raise ValueError('Разрешены только train, validation и test')
        features, targets, metadata = [], [], []
        for row in self._rows(name):
            values = {}
            for feature in FEATURE_NAMES:
                raw = row[feature]
                mask = row[f'{feature}_missing']
                spec = self.schema['columns'][feature]
                if mask not in ('0', '1') or (mask == '1') != (raw == ''):
                    raise ValueError(f'{feature}: неверная маска пропуска')
                if raw == '':
                    if not spec['nullable']:
                        raise ValueError(f'{feature}: пропуск недопустим')
                    value = np.nan
                elif spec['type'] == 'string':
                    if raw not in PRODUCTS:
                        raise ValueError('product_code: неизвестный продукт')
                    value = raw
                else:
                    try:
                        value = float(raw)
                    except ValueError as error:
                        raise ValueError(f'{feature}: нужно число') from error
                    if not math.isfinite(value) or (spec['type'] == 'integer' and not value.is_integer()):
                        raise ValueError(f'{feature}: нужно конечное число допустимого типа')
                values[feature] = value
                values[f'{feature}_missing'] = int(mask)
            if row[TARGET_EVENT] not in ('0', '1'):
                raise ValueError('Целевая метка должна быть 0 или 1')
            features.append(values)
            targets.append(int(row[TARGET_EVENT]))
            metadata.append({key: row[key] for key in _METADATA})
        if not features:
            raise ValueError(f'{name}: пустая часть набора')
        return DataSplit(name, pd.DataFrame(features, columns=MODEL_FEATURES),
                         np.array(targets, dtype=np.int64), pd.DataFrame(metadata, columns=_METADATA))
