"""Фиксированные кандидаты первого сравнения и локальные доверенные артефакты."""

import json
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.compose import ColumnTransformer
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

from app.risk.catalog import ML_PRODUCTS as PRODUCTS
from app.risk.features import FEATURE_NAMES
from app.risk.training_data import MASK_FEATURES, MODEL_FEATURES, DataSplit

_NUMERIC = tuple(name for name in FEATURE_NAMES if name != 'product_code')
_EXTENSIONS = {'constant': 'json', 'logistic': 'joblib', 'catboost': 'cbm'}


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    family: str
    params: dict


@dataclass
class FittedCandidate:
    spec: CandidateSpec
    estimator: object


class _Constant:
    def __init__(self, prevalence):
        self.prevalence = float(prevalence)
        self.feature_names_in_ = np.array(MODEL_FEATURES)
        self.classes_ = np.array([0, 1])

    def predict_proba(self, X):
        return np.tile([1 - self.prevalence, self.prevalence], (len(X), 1))


def default_candidates() -> tuple[CandidateSpec, ...]:
    logistic = dict(solver='lbfgs', max_iter=2000, tol=1e-6)
    catboost = dict(iterations=400, learning_rate=.05, l2_leaf_reg=5, loss_function='Logloss')
    return (
        CandidateSpec('baseline', 'constant', {}),
        *(CandidateSpec(name, 'logistic', dict(C=c, **logistic))
          for name, c in (('lr_c01', .1), ('lr_c1', 1), ('lr_c10', 10))),
        *(CandidateSpec(f'cat_d{depth}', 'catboost', dict(depth=depth, **catboost)) for depth in (4, 6)),
    )


def _check_columns(X):
    if not isinstance(X, pd.DataFrame) or tuple(X.columns) != MODEL_FEATURES:
        raise ValueError('Нужны все 18 входов в зафиксированном порядке')


def _check_estimator_features(candidate):
    estimator = candidate.estimator
    names = (getattr(estimator, 'feature_names_', None) if candidate.spec.family == 'catboost'
             else getattr(estimator, 'feature_names_in_', None))
    if names is None or tuple(names) != MODEL_FEATURES:
        raise ValueError('Порядок входов сохранённой модели несовместим')


def fit_candidate(spec: CandidateSpec, train: DataSplit, *, seed=20261021, threads=2) -> FittedCandidate:
    if train.name != 'train':
        raise ValueError('Обучение разрешено только на части train')
    _check_columns(train.X)
    y = np.asarray(train.y)
    if y.ndim != 1 or len(y) != len(train.X) or set(y.tolist()) != {0, 1}:
        raise ValueError('Train должен содержать оба класса 0 и 1')
    if type(seed) is not int or type(threads) is not int or threads < 1:
        raise ValueError('Нужны целый seed и положительное число threads')
    if spec.family == 'constant':
        estimator = _Constant(y.mean())
    elif spec.family == 'logistic':
        numeric = Pipeline([('imputer', SimpleImputer(strategy='median', keep_empty_features=True)),
                            ('scaler', StandardScaler())])
        preprocessor = ColumnTransformer([
            ('numeric', numeric, list(_NUMERIC)),
            ('product', OneHotEncoder(categories=[sorted(PRODUCTS)], handle_unknown='error',
                                      sparse_output=False), ['product_code']),
            ('masks', 'passthrough', list(MASK_FEATURES)),
        ], remainder='drop')
        estimator = Pipeline([('preprocessor', preprocessor),
                              ('model', LogisticRegression(**spec.params, random_state=seed))])
        try:
            with warnings.catch_warnings(), threadpool_limits(limits=threads):
                warnings.simplefilter('error', ConvergenceWarning)
                estimator.fit(train.X, y)
        except ConvergenceWarning as error:
            raise RuntimeError('LogisticRegression: не достигнута сходимость') from error
    elif spec.family == 'catboost':
        estimator = CatBoostClassifier(**spec.params, task_type='CPU', random_seed=seed,
                                       thread_count=threads, allow_writing_files=False,
                                       verbose=False, use_best_model=False)
        with threadpool_limits(limits=threads):
            estimator.fit(train.X, y, cat_features=['product_code'])
    else:
        raise ValueError(f'Неизвестное семейство модели: {spec.family}')
    fitted = FittedCandidate(spec, estimator)
    _check_estimator_features(fitted)
    return fitted


def predict_probability(candidate: FittedCandidate, X: pd.DataFrame) -> np.ndarray:
    _check_columns(X)
    classes = np.asarray(candidate.estimator.classes_)
    positive = np.flatnonzero(classes == 1)
    if classes.ndim != 1 or len(positive) != 1:
        raise ValueError('Модель должна предоставлять вероятность класса 1')
    with threadpool_limits(limits=2):
        prediction = (candidate.estimator.predict_proba(X, thread_count=2)
                      if candidate.spec.family == 'catboost' else candidate.estimator.predict_proba(X))
        probabilities = np.asarray(prediction, dtype=float)
    if probabilities.ndim != 2 or probabilities.shape != (len(X), len(classes)):
        raise ValueError('Модель вернула неверную форму вероятностей')
    probability = probabilities[:, positive[0]]
    if not np.isfinite(probability).all() or not ((probability >= 0) & (probability <= 1)).all():
        raise ValueError('Модель вернула не конечную вероятность от 0 до 1')
    return probability


def _filename(spec):
    if (spec.family not in _EXTENSIONS or not isinstance(spec.candidate_id, str)
            or re.fullmatch(r'[A-Za-z0-9_-]+', spec.candidate_id) is None
            or not isinstance(spec.params, dict)):
        raise ValueError('Некорректное описание кандидата')
    return f'{spec.candidate_id}.{_EXTENSIONS[spec.family]}'


def save_candidate(candidate: FittedCandidate, directory: Path) -> dict:
    """Сохраняет собственную модель; существующие файлы не перезаписываются."""
    filename = _filename(candidate.spec)
    _check_estimator_features(candidate)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / filename
    # Резервирование через x защищает от случайного повторного сохранения.
    with file.open('xb'):
        pass
    try:
        if candidate.spec.family == 'constant':
            payload = dict(prevalence=candidate.estimator.prevalence, feature_names=list(MODEL_FEATURES))
            file.write_text(json.dumps(payload, allow_nan=False) + '\n', encoding='utf-8')
        elif candidate.spec.family == 'logistic':
            joblib.dump(candidate.estimator, file)
        else:
            candidate.estimator.save_model(str(file), format='cbm')
    except Exception:
        file.unlink(missing_ok=True)
        raise
    return dict(candidate_id=candidate.spec.candidate_id, family=candidate.spec.family,
                params=dict(candidate.spec.params), filename=filename)


def load_candidate(directory: Path, record: dict) -> FittedCandidate:
    """Загружает только доверенный локальный артефакт после внешней проверки manifest."""
    try:
        spec = CandidateSpec(record['candidate_id'], record['family'], record['params'])
        filename = _filename(spec)
    except (KeyError, TypeError) as error:
        raise ValueError('Некорректная запись модели') from error
    if record.get('filename') != filename:
        raise ValueError('Имя артефакта не соответствует кандидату')
    file = Path(directory) / filename
    if file.is_symlink() or not file.is_file():
        raise ValueError('Нужен обычный локальный файл артефакта')
    if spec.family == 'constant':
        payload = json.loads(file.read_text(encoding='utf-8'))
        if payload.get('feature_names') != list(MODEL_FEATURES):
            raise ValueError('Порядок входов baseline несовместим')
        prevalence = payload.get('prevalence')
        if type(prevalence) not in (int, float) or not np.isfinite(prevalence) or not 0 <= prevalence <= 1:
            raise ValueError('Неверная вероятность baseline')
        estimator = _Constant(prevalence)
    elif spec.family == 'logistic':
        estimator = joblib.load(file)
    else:
        estimator = CatBoostClassifier()
        estimator.load_model(str(file), format='cbm')
    candidate = FittedCandidate(spec, estimator)
    _check_estimator_features(candidate)
    return candidate
