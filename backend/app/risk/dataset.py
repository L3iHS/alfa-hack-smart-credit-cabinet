"""Воспроизводимый экспорт синтетических данных, без обучения и доступа к БД."""

import csv
import hashlib
import json
import math
import platform
import shutil
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from random import Random

from app.products.catalog import CATALOG_VERSION, PRODUCTS
from app.risk.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from app.risk.labels import HORIZON_MONTHS, TARGET_EVENT, label_loan_90dpd_12m
from app.risk.synthetic import DEFAULT_SEED, GENERATOR_VERSION, SyntheticLoan, generate_loans

DATASET_VERSION = 'risk-dataset-v1'
TARGET_VERSION = 'loan-90dpd-12m-v1'
_METADATA_COLUMNS = ('company_id', 'application_id')
_MASK_COLUMNS = tuple(f'{name}_missing' for name in FEATURE_NAMES)
_CSV_COLUMNS = (*_METADATA_COLUMNS, *FEATURE_NAMES, *_MASK_COLUMNS, TARGET_EVENT)
_HORIZON = {'months': HORIZON_MONTHS, 'calendar': True, 'end_inclusive': True,
            'event': '90 days past due on the considered loan'}
_FEATURE_SPECS = {
    'business_age_months': {'type': 'integer', 'nullable': False, 'unit': 'completed months'},
    'monthly_revenue_rub': {'type': 'number', 'nullable': False, 'unit': 'RUB per month'},
    'operating_margin_ratio': {'type': 'number', 'nullable': True, 'unit': '(revenue - expenses) / revenue'},
    'existing_debt_to_revenue_ratio': {'type': 'number', 'nullable': True, 'unit': 'existing debt payments / revenue'},
    'coverage_ratio': {'type': 'number', 'nullable': False, 'unit': '(revenue - expenses) / (debt payments + new payment)'},
    'overdue_days': {'type': 'integer', 'nullable': False, 'unit': 'days on existing obligations at submission'},
    'product_code': {'type': 'string', 'nullable': False, 'unit': 'catalog code', 'values': sorted(PRODUCTS)},
    'requested_amount_rub': {'type': 'number', 'nullable': False, 'unit': 'RUB'},
    'term_months': {'type': 'integer', 'nullable': False, 'unit': 'contract months'},
}


def split_by_company(loans: Sequence[SyntheticLoan], seed: int) -> dict[str, list[SyntheticLoan]]:
    """Разделяет компании 70/15/15, сохраняя все их заявки в одной части."""
    if type(seed) is not int:
        raise ValueError('seed: нужно целое число')
    application_ids = [loan.application_id for loan in loans]
    if len(application_ids) != len(set(application_ids)):
        raise ValueError('application_id: повторяющаяся заявка')
    companies = sorted({loan.company_id for loan in loans})
    if len(companies) < 20:
        raise ValueError('Нужно не менее 20 уникальных компаний')
    Random(seed).shuffle(companies)
    train_end = len(companies) * 70 // 100
    validation_end = train_end + len(companies) * 15 // 100
    membership = {company: name for name, part in (
        ('train', companies[:train_end]), ('validation', companies[train_end:validation_end]),
        ('test', companies[validation_end:])) for company in part}
    result = {'train': [], 'validation': [], 'test': []}
    for loan in sorted(loans, key=lambda item: (item.company_id, item.application_id)):
        result[membership[loan.company_id]].append(loan)
    return result


def _row(loan: SyntheticLoan) -> dict:
    """Проверяет метку и значения, затем выпускает только разрешённые столбцы."""
    label = label_loan_90dpd_12m(loan.outcome)
    if label is None:
        raise ValueError(f'{loan.application_id}: цензурированное наблюдение, метка неизвестна')
    if loan.features.schema_version != FEATURE_SCHEMA_VERSION:
        raise ValueError('Неизвестная версия схемы признаков')
    row = {'company_id': loan.company_id, 'application_id': loan.application_id}
    for name in FEATURE_NAMES:
        try:
            value = loan.features.values[name]
            missing = loan.features.missing_mask[name]
        except KeyError as error:
            raise ValueError(f'Отсутствует признак или маска: {name}') from error
        spec = _FEATURE_SPECS[name]
        if type(missing) is not bool or missing != (value is None):
            raise ValueError(f'{name}: маска не совпадает с пропуском')
        if value is None:
            if not spec['nullable']:
                raise ValueError(f'{name}: пропуск недопустим')
        elif spec['type'] == 'string':
            if type(value) is not str or value not in PRODUCTS:
                raise ValueError(f'{name}: неизвестный продукт')
        elif (type(value) not in (int, float) or not math.isfinite(value)
              or (spec['type'] == 'integer' and type(value) is not int)):
            raise ValueError(f'{name}: нужно конечное число допустимого типа')
        row[name] = value
        row[f'{name}_missing'] = int(missing)
    if (type(loan.true_probability) not in (int, float)
            or not math.isfinite(loan.true_probability) or not 0 <= loan.true_probability <= 1):
        raise ValueError('true_probability: нужна конечная вероятность от 0 до 1')
    row[TARGET_EVENT] = label
    return row


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f'Неподдерживаемый тип JSON: {type(value).__name__}')


def _write_json(path: Path, value: dict) -> None:
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2,
                  allow_nan=False, default=_json_default)
        stream.write('\n')


def _statistics(loans: Sequence[SyntheticLoan], rows: list[dict]) -> dict:
    count = len(rows)
    events = sum(row[TARGET_EVENT] for row in rows)
    products = Counter(row['product_code'] for row in rows)
    terms = Counter(row['term_months'] for row in rows)
    missing_counts = {name: sum(row[f'{name}_missing'] for row in rows) for name in FEATURE_NAMES}
    return {
        'rows': count, 'unique_companies': len({loan.company_id for loan in loans}),
        'events': events, 'event_rate': events / count if count else None,
        'class_counts': {'0': count - events, '1': events},
        'products': {name: products[name] for name in sorted(PRODUCTS)},
        'term_months': {str(term): terms[term] for term in sorted(terms)},
        'missing': {name: {'count': number, 'rate': number / count if count else None}
                    for name, number in missing_counts.items()},
    }


def _schema() -> dict:
    return {
        'feature_schema_version': FEATURE_SCHEMA_VERSION, 'target': TARGET_EVENT,
        'horizon': _HORIZON, 'data_kind': 'synthetic',
        'feature_columns': [*FEATURE_NAMES, *_MASK_COLUMNS],
        'metadata_columns': list(_METADATA_COLUMNS), 'target_column': TARGET_EVENT,
        'csv_columns': list(_CSV_COLUMNS), 'missing_value': '',
        'columns': {
            **{name: {'type': 'string', 'nullable': False, 'role': 'metadata'} for name in _METADATA_COLUMNS},
            **_FEATURE_SPECS,
            **{name: {'type': 'integer', 'nullable': False, 'values': [0, 1],
                      'unit': '1 means missing, 0 means present'} for name in _MASK_COLUMNS},
            TARGET_EVENT: {'type': 'integer', 'nullable': False, 'values': [0, 1],
                           'unit': '90dpd event within the inclusive calendar horizon'},
        },
    }


def build_dataset(output_dir: Path, *, count: int = 10000, seed: int = DEFAULT_SEED) -> dict:
    """Собирает новый каталог во временной соседней папке, сохраняя существующий."""
    output_dir = Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f'Путь уже существует: {output_dir}')
    loans = generate_loans(count, seed)
    splits = split_by_company(loans, seed)
    rows = {name: [_row(loan) for loan in part] for name, part in splits.items()}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{output_dir.name}-', dir=output_dir.parent))
    try:
        for name, part in rows.items():
            with (temporary / f'{name}.csv').open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=_CSV_COLUMNS, lineterminator='\n')
                writer.writeheader()
                writer.writerows(part)
        with (temporary / 'observations.jsonl').open('w', encoding='utf-8', newline='\n') as stream:
            for loan in sorted(loans, key=lambda item: (item.company_id, item.application_id)):
                diagnostic = {
                    'data_kind': 'synthetic diagnostic', 'usage': 'audit only; not model inputs',
                    'company_id': loan.company_id, 'application_id': loan.application_id,
                    'application': loan.application, 'submitted_at': loan.submitted_at,
                    'registered_at': loan.registered_at, 'overdue_days': loan.overdue_days,
                    'outcome': asdict(loan.outcome), 'true_probability': loan.true_probability,
                }
                stream.write(json.dumps(diagnostic, ensure_ascii=False, sort_keys=True,
                                        allow_nan=False, default=_json_default) + '\n')
        _write_json(temporary / 'schema.json', _schema())
        company_sets = {name: {loan.company_id for loan in part} for name, part in splits.items()}
        report = {
            'data_kind': 'synthetic', 'target': TARGET_EVENT,
            'overall': _statistics(loans, [row for part in rows.values() for row in part]),
            'splits': {name: _statistics(splits[name], part) for name, part in rows.items()},
            'company_overlap_counts': {
                f'{left}_{right}': len(company_sets[left] & company_sets[right])
                for left, right in (('train', 'validation'), ('train', 'test'), ('validation', 'test'))},
            'all_numeric_values_finite': True,
            'limitations': ['Данные и зависимости генератора синтетические.',
                            'Обучение не выполнялось; качество модели и банковский риск не измерялись.',
                            'Test не предназначен для выбора генератора, признаков или порогов.'],
        }
        _write_json(temporary / 'report.json', report)
        manifest = {
            'dataset_version': DATASET_VERSION, 'feature_schema_version': FEATURE_SCHEMA_VERSION,
            'generator_version': GENERATOR_VERSION, 'target_version': TARGET_VERSION,
            'catalog_version': CATALOG_VERSION, 'target': TARGET_EVENT, 'horizon': _HORIZON,
            'data_kind': 'synthetic', 'seed': seed, 'count': count,
            'python_version': platform.python_version(),
            'sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in sorted(temporary.iterdir())},
        }
        _write_json(temporary / 'manifest.json', manifest)
        if output_dir.exists() or output_dir.is_symlink():
            raise FileExistsError(f'Путь уже существует: {output_dir}')
        temporary.rename(output_dir)
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
