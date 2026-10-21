"""Проверка собственных локальных артефактов до десериализации моделей."""

import csv
import ctypes
import errno
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import resource
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app.risk.estimators import default_candidates, load_candidate
from app.risk.labels import TARGET_EVENT
from app.risk.training_data import MODEL_FEATURES, DatasetReader

PROTOCOL_VERSION = 'risk-training-v1'
FAMILIES = ('constant', 'logistic', 'catboost')
SEED = 20261021
THREADS = 2
TOLERANCE = .001
LIBRARIES = ('numpy', 'pandas', 'scikit-learn', 'catboost', 'matplotlib', 'joblib', 'threadpoolctl')
DATA_VERSIONS = ('dataset_version', 'target_version', 'feature_schema_version', 'generator_version',
                 'catalog_version', 'target', 'horizon', 'data_kind')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload) -> None:
    # Сначала сериализуем целиком, чтобы NaN не оставлял частичный файл.
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n'
    Path(path).write_text(text, encoding='utf-8')


def read_json(path: Path):
    def invalid(value):
        raise ValueError(f'Недопустимое JSON число: {value}')
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Не удалось прочитать JSON: {path.name}') from error


def source_hashes() -> dict:
    return {file.name: sha256(file) for file in sorted(Path(__file__).parent.glob('*.py'))}


def versions() -> dict:
    return {name: importlib.metadata.version(name) for name in LIBRARIES}


def source_revision():
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parent,
                              check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _cpu_quota():
    try:
        return Path('/sys/fs/cgroup/cpu.max').read_text().strip()
    except OSError:
        return None


def resources(start: float, end: float) -> dict:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(runtime_seconds=end - start,
                max_rss_bytes=int(rss if platform.system() == 'Darwin' else rss * 1024),
                rss_method='resource.getrusage(RUSAGE_SELF).ru_maxrss; пик процесса, включая импорты',
                runtime_method='time.perf_counter; от входа функции до записи manifest',
                platform=platform.platform(), machine=platform.machine(),
                logical_cpu_count=os.cpu_count(), cpu_quota=_cpu_quota(), threads=THREADS)


def ensure_new(path: Path) -> None:
    if os.path.lexists(path):
        raise FileExistsError(f'Каталог результата уже существует: {path}')


def _publish(staging: Path, output: Path) -> None:
    """Атомарный rename без замены даже при появлении чужого каталога в гонке."""
    libc = ctypes.CDLL(None, use_errno=True)
    if platform.system() == 'Linux':
        rename = libc.renameat2
        rename.restype = ctypes.c_int
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(staging), -100, os.fsencode(output), 1)
    elif platform.system() == 'Darwin':
        rename = libc.renamex_np
        rename.restype = ctypes.c_int
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(staging), os.fsencode(output), 4)
    else:
        raise OSError('Атомарная публикация поддерживается на Linux и macOS')
    if result:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(f'Каталог результата уже существует: {output}')
        raise OSError(code, os.strerror(code), str(output))


@contextmanager
def atomic_directory(output: Path):
    output = Path(output)
    ensure_new(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{output.name}-', dir=output.parent))
    try:
        yield staging
        _publish(staging, output)
    finally:
        # Удаляется только уникальный собственный staging; готовый результат не трогаем.
        if staging.exists():
            shutil.rmtree(staging)


def select_candidates(scores: list[dict]) -> dict:
    expected = {spec.candidate_id: spec for spec in default_candidates()}
    if not isinstance(scores, list) or len(scores) != len(expected):
        raise ValueError('Нужны scores шести фиксированных кандидатов')
    found = {}
    for score in scores:
        if not isinstance(score, dict):
            raise ValueError('Неверное описание score')
        spec = expected.get(score.get('candidate_id'))
        value = score.get('brier')
        if (spec is None or spec.candidate_id in found or score.get('family') != spec.family
                or score.get('params') != spec.params or type(value) not in (float, int)
                or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError('Score не соответствует фиксированному протоколу')
        found[spec.candidate_id] = score
    winners = {}
    for family in FAMILIES:
        members = [score for score in scores if score['family'] == family]
        winner = min(members, key=lambda s: (s['brier'], s['params'].get('C', s['params'].get('depth', 0))))
        winners[family] = winner['candidate_id']
    minimum = min(found[candidate]['brier'] for candidate in winners.values())
    selected = next(winners[family] for family in FAMILIES
                    if found[winners[family]]['brier'] <= minimum + TOLERANCE)
    return dict(scores=scores, family_winners=winners, selected_candidate_id=selected,
                selected_on='validation', test_used=False, protocol_version=PROTOCOL_VERSION,
                seed=SEED, threads=THREADS, brier_tolerance=TOLERANCE,
                rule='Минимум Brier внутри семьи, точный tie: меньший C/depth; '
                     'глобальный min+0.001, затем constant → logistic → catboost',
                tolerance_interpretation='Заданное предпочтение простоты, не статистическое равенство')


def build_manifest(directory: Path, reader: DatasetReader, measured: dict) -> dict:
    return dict(protocol_version=PROTOCOL_VERSION,
                **{key: reader.manifest[key] for key in DATA_VERSIONS},
                dataset_manifest_sha256=reader.fingerprint, model_features=list(MODEL_FEATURES),
                libraries=versions(), python=platform.python_version(), source_revision=source_revision(),
                source_sha256=source_hashes(), resources=measured,
                sha256={file.relative_to(directory).as_posix(): sha256(file)
                        for file in sorted(directory.rglob('*')) if file.is_file()})


def _plain_file(path: Path, root: Path) -> None:
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError('Символические ссылки в run запрещены')
        current = current.parent
    if not path.is_file():
        raise ValueError(f'Нужен обычный файл: {path.name}')


def _check_predictions(path, candidate_ids):
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['company_id', 'application_id', TARGET_EVENT, *candidate_ids]:
            raise ValueError('Несовместимый порядок колонок прогнозов')
        count = 0
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('Неверная длина строки прогнозов')
            if row[TARGET_EVENT] not in ('0', '1') or not row['company_id'] or not row['application_id']:
                raise ValueError('Неверные метки или ID в прогнозах')
            for candidate in candidate_ids:
                try:
                    probability = float(row[candidate])
                except ValueError as error:
                    raise ValueError('Неверная вероятность в прогнозах') from error
                if not math.isfinite(probability) or not 0 <= probability <= 1:
                    raise ValueError('Неверная вероятность в прогнозах')
            count += 1
        if not count:
            raise ValueError('Пустые прогнозы validation')


def _nonnegative(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def load_run(data_dir: Path, run_dir: Path) -> tuple[DatasetReader, dict, dict]:
    """Проверяет совместимость и целостность всего run, не создавая DataSplit test."""
    run_dir = Path(run_dir)
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError('Нужен обычный каталог run')
    _plain_file(run_dir / 'manifest.json', run_dir)
    manifest = read_json(run_dir / 'manifest.json')
    required = {'protocol_version', *DATA_VERSIONS, 'dataset_manifest_sha256', 'model_features',
                'libraries', 'python', 'source_revision', 'source_sha256', 'resources', 'sha256'}
    if not isinstance(manifest, dict) or not required <= manifest.keys():
        raise ValueError('Неполный run manifest')
    source = manifest['source_sha256']
    if (not isinstance(source, dict) or not source
            or any(not isinstance(name, str) or re.fullmatch(r'[A-Za-z0-9_]+\.py', name) is None
                   or not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None
                   for name, digest in source.items())):
        raise ValueError('Неверные контрольные суммы исходников')
    if manifest['source_revision'] is not None and (not isinstance(manifest['source_revision'], str)
            or re.fullmatch(r'[0-9a-f]{40,64}', manifest['source_revision']) is None):
        raise ValueError('Неверная ревизия исходников')
    measured = manifest['resources']
    if (not isinstance(measured, dict) or type(measured.get('max_rss_bytes')) is not int
            or measured['max_rss_bytes'] <= 0 or not _nonnegative(measured.get('runtime_seconds'))):
        raise ValueError('Неверные измерения ресурсов')
    if (manifest.get('protocol_version') != PROTOCOL_VERSION
            or manifest.get('model_features') != list(MODEL_FEATURES)
            or manifest.get('libraries') != versions()
            or manifest.get('python') != platform.python_version()):
        raise ValueError('Несовместимые версии протокола, признаков, Python или библиотек')
    # DatasetReader проверяет fingerprint и metadata всех частей, но не читает test как модельную таблицу.
    reader = DatasetReader(data_dir)
    if (manifest.get('dataset_manifest_sha256') != reader.fingerprint
            or any(manifest.get(key) != reader.manifest[key] for key in DATA_VERSIONS)):
        raise ValueError('Run создан на другом или несовместимом наборе данных')
    hashes = manifest.get('sha256')
    if not isinstance(hashes, dict):
        raise ValueError('Нужны sha256 выходных файлов')
    # До чтения selection разрешаем только безопасные фиксированные имена выходов.
    fixed = {'selection.json', 'validation.json', 'validation-predictions.csv'}
    specs = {spec.candidate_id: spec for spec in default_candidates()}
    allowed = fixed | {f'models/{spec.candidate_id}.{dict(constant="json", logistic="joblib", catboost="cbm")[spec.family]}'
                       for spec in specs.values()}
    if not fixed <= hashes.keys() or not set(hashes) <= allowed or len(hashes) != 6:
        raise ValueError('Неверный список файлов run manifest')
    for name, digest in hashes.items():
        file = run_dir / name
        _plain_file(file, run_dir)
        if not isinstance(digest, str) or sha256(file) != digest:
            raise ValueError(f'{name}: sha256 не совпадает')
    selection = read_json(run_dir / 'selection.json')
    if not isinstance(selection, dict) or select_candidates(selection.get('scores')) != selection:
        raise ValueError('Неверный зафиксированный выбор')
    validation = read_json(run_dir / 'validation.json')
    if not isinstance(validation, dict) or not isinstance(validation.get('models'), dict):
        raise ValueError('Неверный validation report')
    candidate_ids = [selection['family_winners'][family] for family in FAMILIES]
    if set(validation['models']) != set(candidate_ids) or validation.get('split') != 'validation':
        raise ValueError('Неверный состав семейств validation')
    expected_files = set(fixed)
    records = {}
    for candidate in candidate_ids:
        spec, record = specs[candidate], validation['models'][candidate]
        extension = dict(constant='json', logistic='joblib', catboost='cbm')[spec.family]
        expected = dict(candidate_id=candidate, family=spec.family, params=spec.params,
                        filename=f'{candidate}.{extension}')
        if not isinstance(record, dict) or any(record.get(key) != value for key, value in expected.items()):
            raise ValueError('Метаданные сохранённой модели несовместимы с выбором')
        if (not isinstance(record.get('metrics'), dict)
                or not _nonnegative(record.get('fit_seconds'))
                or not _nonnegative(record.get('predict_seconds'))
                or type(record.get('size_bytes')) is not int
                or record['size_bytes'] != (run_dir / 'models' / expected['filename']).stat().st_size):
            raise ValueError('Неверные измерения или метрики сохранённой модели')
        if record['metrics'].get('brier') != next(s['brier'] for s in selection['scores'] if s['candidate_id'] == candidate):
            raise ValueError('Brier модели не соответствует выбору')
        expected_files.add(f'models/{expected["filename"]}')
        records[candidate] = expected
    if set(hashes) != expected_files:
        raise ValueError('Модели manifest не соответствуют победителям семейств')
    if {path.name for path in (run_dir / 'models').iterdir()} != {r['filename'] for r in records.values()}:
        raise ValueError('В models должны быть только три выбранных артефакта')
    _check_predictions(run_dir / 'validation-predictions.csv', candidate_ids)
    # Хеши исходников являются происхождением, а не запретом на новые reporting/CLI модули.
    models = {candidate: load_candidate(run_dir / 'models', record) for candidate, record in records.items()}
    return reader, selection, models
