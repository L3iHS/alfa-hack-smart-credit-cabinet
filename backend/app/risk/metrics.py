"""Вероятностные метрики; результаты на синтетике не доказывают банковское качество."""

import numpy as np
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score


def _validated(y, p):
    try:
        y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError('Нужны численные метки и вероятности') from error
    if (y.ndim != 1 or p.ndim != 1 or len(y) == 0 or y.shape != p.shape
            or not np.isin(y, [0, 1]).all() or not np.isfinite(p).all()
            or not ((p >= 0) & (p <= 1)).all()):
        raise ValueError('Нужны непустые равные векторы меток 0/1 и конечных вероятностей 0..1')
    return y, p


def probability_metrics(y, p) -> dict:
    y, p = _validated(y, p)
    single_class = len(np.unique(y)) < 2
    unavailable = ({name: 'Нужны оба класса: в этой части присутствует только один'
                    for name in ('roc_auc', 'average_precision')} if single_class else {})
    return dict(n=len(y), events=int(y.sum()), prevalence=float(y.mean()),
                brier=float(np.mean((p - y) ** 2)), log_loss=float(log_loss(y, p, labels=[0, 1])),
                roc_auc=None if single_class else float(roc_auc_score(y, p)),
                average_precision=None if single_class else float(average_precision_score(y, p)),
                unavailable=unavailable)


def calibration_bins(y, p, n_bins=10) -> list[dict]:
    y, p = _validated(y, p)
    if type(n_bins) is not int or n_bins < 1:
        raise ValueError('n_bins должно быть положительным целым числом')
    membership = np.minimum((p * n_bins).astype(int), n_bins - 1)
    bins = []
    for index in range(n_bins):
        selected = membership == index
        count = int(selected.sum())
        bins.append(dict(lower=index / n_bins, upper=(index + 1) / n_bins, count=count,
                         mean_probability=float(p[selected].mean()) if count else None,
                         event_rate=float(y[selected].mean()) if count else None))
    return bins


def paired_brier_interval(y, p_model, p_baseline, groups, *, seed=20261022, resamples=1000) -> dict:
    """Перевыбирает компании вместе с их строками и сохраняет парность прогнозов."""
    y, model = _validated(y, p_model)
    _, baseline = _validated(y, p_baseline)
    groups = np.asarray(groups, dtype=object)
    if groups.ndim != 1 or len(groups) != len(y):
        raise ValueError('Нужна группа компании для каждой строки')
    if type(seed) is not int or type(resamples) is not int or resamples < 1:
        raise ValueError('Нужны целый seed и положительное число resamples')
    indices = {}
    for index, group in enumerate(groups):
        if group is None or (isinstance(group, (float, np.floating)) and not np.isfinite(group)):
            raise ValueError('Группы компаний не должны содержать пропуски')
        try:
            indices.setdefault(group, []).append(index)
        except TypeError as error:
            raise ValueError('Группа компании должна быть скалярным идентификатором') from error
    differences = (model - y) ** 2 - (baseline - y) ** 2
    sums = np.array([differences[rows].sum() for rows in indices.values()])
    counts = np.array([len(rows) for rows in indices.values()])
    generator = np.random.default_rng(seed)
    bootstrapped = np.empty(resamples)
    for index in range(resamples):
        draw = generator.integers(0, len(counts), size=len(counts))
        bootstrapped[index] = sums[draw].sum() / counts[draw].sum()
    lower, upper = np.quantile(bootstrapped, [.025, .975])
    return dict(difference=float(differences.mean()), lower=float(lower), upper=float(upper),
                groups=len(indices), resamples=resamples, seed=seed)
