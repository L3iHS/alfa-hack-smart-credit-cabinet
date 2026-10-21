"""Offline сравнение на validation и отдельная однократная оценка на test."""

import csv
import time
from pathlib import Path

from app.risk.artifacts import (FAMILIES, SEED, THREADS, atomic_directory, build_manifest,
                                ensure_new, load_run, resources, select_candidates, sha256, write_json)
from app.risk.estimators import default_candidates, fit_candidate, predict_probability, save_candidate
from app.risk.labels import TARGET_EVENT
from app.risk.metrics import calibration_bins, paired_brier_interval, probability_metrics
from app.risk.training_data import DatasetReader

LIMITATIONS = ('Результаты относятся только к синтетическим данным и не подтверждают качество '
               'оценки риска реальных заёмщиков. Допуск выбора означает предпочтение простоты, '
               'а не статистическое равенство. Интервал парного bootstrap компаний описывает '
               'вариативность этого test и не учитывает переобучение или смену источника данных.')


def _write_predictions(path, split, predictions):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['company_id', 'application_id', TARGET_EVENT, *predictions])
        for index, row in enumerate(split.metadata.itertuples(index=False)):
            writer.writerow([row.company_id, row.application_id, int(split.y[index]),
                             *(float(values[index]) for values in predictions.values())])


def train_experiment(data_dir: Path, output_dir: Path) -> dict:
    start = time.perf_counter()
    with atomic_directory(output_dir) as staging:
        reader = DatasetReader(data_dir)
        train, validation = reader.split('train'), reader.split('validation')
        fitted, predictions, measured, scores, all_metrics = {}, {}, {}, [], {}
        for spec in default_candidates():
            fit_start = time.perf_counter()
            candidate = fit_candidate(spec, train, seed=SEED, threads=THREADS)
            fit_end = time.perf_counter()
            probability = predict_probability(candidate, validation.X)
            predict_end = time.perf_counter()
            metrics = probability_metrics(validation.y, probability)
            all_metrics[spec.candidate_id] = dict(metrics=metrics,
                calibration=calibration_bins(validation.y, probability))
            fitted[spec.candidate_id] = candidate
            predictions[spec.candidate_id] = probability
            measured[spec.candidate_id] = dict(fit_seconds=fit_end - fit_start,
                                              predict_seconds=predict_end - fit_end)
            scores.append(dict(candidate_id=spec.candidate_id, family=spec.family,
                               params=dict(spec.params), brier=metrics['brier']))
        selection = select_candidates(scores)
        # Выбор фиксируется до какой-либо возможности открыть test.
        write_json(staging / 'selection.json', selection)
        winners = [selection['family_winners'][family] for family in FAMILIES]
        models = {}
        for candidate_id in winners:
            record = save_candidate(fitted[candidate_id], staging / 'models')
            models[candidate_id] = dict(**record, **measured[candidate_id],
                size_bytes=(staging / 'models' / record['filename']).stat().st_size,
                **all_metrics[candidate_id])
        report = dict(split='validation', selected_candidate_id=selection['selected_candidate_id'],
                      models=models, candidate_metrics=all_metrics, candidate_timings=measured, limitations=LIMITATIONS)
        write_json(staging / 'validation.json', report)
        _write_predictions(staging / 'validation-predictions.csv', validation,
                           {name: predictions[name] for name in winners})
        manifest = build_manifest(staging, reader, resources(start, time.perf_counter()))
        write_json(staging / 'manifest.json', manifest)
    return selection


def evaluate_experiment(data_dir: Path, run_dir: Path) -> dict:
    start = time.perf_counter()
    run_dir = Path(run_dir)
    ensure_new(run_dir / 'evaluation')
    reader, selection, models = load_run(data_dir, run_dir)
    with atomic_directory(run_dir / 'evaluation') as staging:
        test = reader.split('test')
        predictions, reports = {}, {}
        for candidate_id, candidate in models.items():
            predict_start = time.perf_counter()
            predictions[candidate_id] = predict_probability(candidate, test.X)
            predict_end = time.perf_counter()
            reports[candidate_id] = dict(family=candidate.spec.family, params=candidate.spec.params,
                predict_seconds=predict_end - predict_start,
                metrics=probability_metrics(test.y, predictions[candidate_id]),
                calibration=calibration_bins(test.y, predictions[candidate_id]))
        selected = selection['selected_candidate_id']
        baseline = selection['family_winners']['constant']
        report = dict(split='test', selected_candidate_id=selected, models=reports,
            paired_brier_interval=paired_brier_interval(test.y, predictions[selected], predictions[baseline],
                                                       test.metadata['company_id'], seed=20261022, resamples=1000),
            limitations=LIMITATIONS)
        write_json(staging / 'metrics.json', report)
        _write_predictions(staging / 'predictions.csv', test, predictions)
        manifest = build_manifest(staging, reader, resources(start, time.perf_counter()))
        manifest['parent_manifest_sha256'] = sha256(run_dir / 'manifest.json')
        manifest['selected_candidate_id'] = selected
        write_json(staging / 'manifest.json', manifest)
    return report
