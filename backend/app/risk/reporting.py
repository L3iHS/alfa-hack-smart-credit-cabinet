"""Отчёт по зафиксированным результатам без fit, нового выбора или оценки модели на test."""

import time
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, roc_curve

from app.risk.artifacts import (DATA_VERSIONS, FAMILIES, _check_predictions, _plain_file,
                                atomic_directory, ensure_new, load_run, read_json, resources,
                                sha256, source_hashes, write_json)
from app.risk.explanations import explain_catboost, explain_logistic
from app.risk.labels import TARGET_EVENT
from app.risk.metrics import calibration_bins, probability_metrics

FEATURE_LABELS = dict(business_age_months='Возраст бизнеса, месяцы', monthly_revenue_rub='Выручка, ₽/мес.',
    operating_margin_ratio='Операционная маржа', existing_debt_to_revenue_ratio='Старые платежи / выручка',
    coverage_ratio='Покрытие платежей', overdue_days='Текущая просрочка, дни', product_code='Кредитный продукт',
    requested_amount_rub='Запрошенная сумма, ₽', term_months='Срок, месяцы')
MODEL_LABELS = dict(constant='Постоянный прогноз', logistic='LogisticRegression', catboost='CatBoost')


def feature_label(name):
    if '__' in name:
        prefix, name = name.split('__', 1)
        if prefix == 'product':
            return 'Продукт: ' + {'product_code_equipment': 'оборудование',
                                  'product_code_working_capital': 'оборотный кредит'}.get(name, name)
        label = feature_label(name)
        return label + (' (после заполнения и стандартизации)' if prefix == 'numeric' else '')
    if name.endswith('_missing'):
        return 'Пропуск: ' + FEATURE_LABELS[name.removesuffix('_missing')].lower()
    return FEATURE_LABELS[name]


def _evaluation(run_dir, run_manifest, selection):
    directory = run_dir / 'evaluation'
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Нужна сохранённая итоговая evaluation')
    _plain_file(directory / 'manifest.json', directory)
    manifest = read_json(directory / 'manifest.json')
    keys = ('protocol_version', 'dataset_manifest_sha256', 'model_features', 'libraries', 'python', *DATA_VERSIONS)
    if (not isinstance(manifest, dict)
            or any(manifest.get(key) != run_manifest.get(key) for key in keys)
            or manifest.get('parent_manifest_sha256') != sha256(run_dir / 'manifest.json')
            or manifest.get('selected_candidate_id') != selection.get('selected_candidate_id')
            or not isinstance(manifest.get('sha256'), dict)
            or set(manifest['sha256']) != {'metrics.json', 'predictions.csv'}):
        raise ValueError('Evaluation manifest не соответствует сохранённому run и выбору')
    for name, digest in manifest['sha256'].items():
        _plain_file(directory / name, directory)
        if sha256(directory / name) != digest:
            raise ValueError(f'Evaluation {name}: sha256 не совпадает')
    report = read_json(directory / 'metrics.json')
    ids = [selection['family_winners'][family] for family in FAMILIES]
    if (not isinstance(report, dict) or report.get('split') != 'test'
            or report.get('selected_candidate_id') != selection['selected_candidate_id']
            or not isinstance(report.get('models'), dict) or set(report['models']) != set(ids)):
        raise ValueError('Итоговые метрики не соответствуют выбору')
    _check_predictions(directory / 'predictions.csv', ids)
    predictions = pd.read_csv(directory / 'predictions.csv')
    if predictions[['company_id', 'application_id']].isna().any().any() or predictions.application_id.duplicated().any():
        raise ValueError('Неверные идентификаторы сохранённых прогнозов')
    # Проверка согласованности сохранённых файлов не вызывает predict или fit.
    for family, candidate_id in zip(FAMILIES, ids):
        record = report['models'][candidate_id]
        if record.get('family') != family or record.get('params') != next(
                score['params'] for score in selection['scores'] if score['candidate_id'] == candidate_id):
            raise ValueError('Семейство или параметры evaluation не соответствуют выбору')
        expected = probability_metrics(predictions[TARGET_EVENT], predictions[candidate_id])
        actual = record.get('metrics', {})
        for key, value in expected.items():
            saved = actual.get(key)
            if (value is None and saved is not None) or (isinstance(value, dict) and value != saved):
                raise ValueError('Метрики не соответствуют сохранённым прогнозам')
            if isinstance(value, (int, float)) and (type(saved) not in (int, float)
                    or not np.isfinite(saved) or not np.isclose(value, saved, rtol=0, atol=1e-12)):
                raise ValueError('Метрики не соответствуют сохранённым прогнозам')
        expected_bins = calibration_bins(predictions[TARGET_EVENT], predictions[candidate_id])
        saved_bins = record.get('calibration')
        if not isinstance(saved_bins, list) or len(saved_bins) != 10:
            raise ValueError('Нужны 10 сохранённых интервалов калибровки')
        for actual_bin, expected_bin in zip(saved_bins, expected_bins):
            for key, value in expected_bin.items():
                saved = actual_bin.get(key)
                if ((value is None and saved is not None) or (value is not None and
                        (type(saved) not in (int, float) or not np.isfinite(saved)
                         or not np.isclose(value, saved, atol=1e-12, rtol=0)))):
                    raise ValueError('Калибровка не соответствует сохранённым прогнозам')
    return report, predictions


def report_figures(evaluation: dict, predictions: pd.DataFrame):
    """Рисует только сохранённые test-прогнозы и проверенные интервалы калибровки."""
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'svg.fonttype': 'none'})
    calibration, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    axes[0].plot([0, 1], [0, 1], '--', color='#777777', label='Идеальная калибровка')
    ranking, ranking_axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    ranking_axes[0].plot([0, 1], [0, 1], '--', color='#777777', label='Случайное ранжирование')
    colors = ['#777777', '#2563a6', '#c45135']
    y = predictions[TARGET_EVENT].to_numpy()
    for index, (candidate_id, record) in enumerate(evaluation['models'].items()):
        color = colors[index]
        label = f'{MODEL_LABELS[record["family"]]} ({candidate_id})'
        bins = record['calibration']
        nonempty = [point for point in bins if point['count']]
        axes[0].plot([point['mean_probability'] for point in nonempty],
                     [point['event_rate'] for point in nonempty], 'o-', color=color, label=label)
        axes[1].bar(np.arange(10) / 10 + .05 + (index - 1) * .025,
                    [point['count'] for point in bins], width=.024, color=color, label=label)
        probability = predictions[candidate_id].to_numpy()
        metrics = record['metrics']
        if metrics['roc_auc'] is not None:
            fpr, tpr, _ = roc_curve(y, probability)
            ranking_axes[0].plot(fpr, tpr, color=color, label=f'{label}; AUC={metrics["roc_auc"]:.3f}')
        if record['family'] == 'constant':
            ranking_axes[1].axhline(y.mean(), color=color, linestyle='--',
                label=f'{label}; prevalence=AP={y.mean():.3f}')
        elif metrics['average_precision'] is not None:
            precision, recall, _ = precision_recall_curve(y, probability)
            ranking_axes[1].step(recall, precision, where='post', color=color,
                label=f'{label}; AP={metrics["average_precision"]:.3f}')
    for axis in (axes[0], *ranking_axes):
        axis.set(xlim=(0, 1), ylim=(0, 1))
    axes[0].set(title='Калибровка: 10 равных интервалов', xlabel='Средняя вероятность модели', ylabel='Наблюдаемая доля событий')
    axes[1].set(title='Число заявок в каждом интервале', xlabel='Вероятность модели', ylabel='Заявок', xlim=(0, 1), xticks=np.arange(0, 1.01, .1))
    ranking_axes[0].set(title='ROC', xlabel='Доля ложноположительных (FPR)', ylabel='Полнота (TPR)')
    ranking_axes[1].set(title='Precision–Recall', xlabel='Полнота (Recall)', ylabel='Точность (Precision)')
    for figure in (calibration, ranking):
        figure.suptitle('Фиксированная test-оценка · синтетические данные', fontsize=13)
        for axis in figure.axes:
            axis.grid(alpha=.2)
            axis.legend(fontsize=8, loc='best')
    return calibration, ranking


def _number(value):
    return 'недоступно' if value is None else f'{value:.6f}'


def _top_factors(explanation, row, positive):
    pairs = [(feature_label(name), value) for name, value in
             zip(explanation['feature_names'], explanation['contributions'][row])
             if (value > 1e-12 if positive else value < -1e-12)]
    pairs.sort(key=lambda pair: abs(pair[1]), reverse=True)
    return '; '.join(f'{label}: {value:+.4f}' for label, value in pairs[:3]) or 'нет ненулевых вкладов'


def _comparison(selection, validation, evaluation, explanations, run_manifest):
    selected = selection['selected_candidate_id']
    family = next(family for family, name in selection['family_winners'].items() if name == selected)
    minimum = min(score['brier'] for score in selection['scores'])
    selected_brier = validation['models'][selected]['metrics']['brier']
    lines = [f'# Сравнение моделей: выбрана {MODEL_LABELS[family]} ({selected})', '',
        f'Выбор зафиксирован на validation (selected_on=validation): Brier {_number(selected_brier)}, минимум {_number(minimum)}. '
        f'Правило min + {selection["brier_tolerance"]} предпочитает простоту: constant → logistic → catboost. '
        'Test не меняет этот выбор; допуск не доказывает статистическое равенство.', '',
        'Результат относится к синтетическим компаниям и цели loan_90dpd_12m: 90 дней просрочки '
        'по рассматриваемому кредиту в первые 12 календарных месяцев. Качество реального банковского риска не проверено.', '',
        '## Качество вероятностей и ранжирования', '',
        '| Часть | Модель | Brier ↓ | ROC-AUC ↑ | Average Precision ↑ | Log loss ↓ |',
        '| --- | --- | ---: | ---: | ---: | ---: |']
    for split, report in [('validation', validation), ('test', evaluation)]:
        for family in FAMILIES:
            name = selection['family_winners'][family]
            metrics = report['models'][name]['metrics']
            lines.append(f'| {split} | {MODEL_LABELS[family]} ({name}) | ' + ' | '.join(
                _number(metrics[key]) for key in ('brier', 'roc_auc', 'average_precision', 'log_loss')) + ' |')
    test = evaluation['models'][selected]['metrics']
    baseline = evaluation['models'][selection['family_winners']['constant']]['metrics']
    improvement = (baseline['brier'] - test['brier']) / baseline['brier'] * 100 if baseline['brier'] else 0
    interval = evaluation['paired_brier_interval']
    if test['roc_auc'] is not None and test['average_precision'] is not None:
        lines.extend(['', f'ROC-AUC {test["roc_auc"]:.4f}: в {test["roc_auc"]:.1%} случайных пар '
            '«событие / отсутствие события» прогноз риска выше у заявки с событием (с половинным весом совпадений). '
            f'AP {test["average_precision"]:.4f} против prevalence {test["prevalence"]:.4f}. '
            'Это оценка ранжирования на синтетике; она не задаёт точность при выбранном кредитном пороге.'])
    lines.extend(['', f'На test Brier выбранной модели лучше постоянного прогноза на {improvement:.2f}%. '
        f'Парный 95% bootstrap-интервал разности Brier (выбранная − baseline): '
        f'[{interval["lower"]:.6f}; {interval["upper"]:.6f}], компаний {interval["groups"]}. '
        'Он описывает вариативность этого test, не смену источника данных или повторное обучение.', '',
        f'Test: {test["n"]} заявок, {test["events"]} событий ({test["prevalence"]:.2%}). '
        'Это полезная первая точка сравнения: вероятность и ранжирование оцениваются отдельно. '
        'Brier — средний квадрат ошибки вероятности; меньше лучше. AUC характеризует порядок риска, '
        'AP — качество поиска редких событий по precision/recall (average_precision_score, не трапецеидальная площадь). '
        'Даже accuracy постоянного ответа «события нет» была бы высокой из-за редкости события; '
        'она не проверяет полезность вероятностей.', '',
        'Калибровка сопоставляет средний прогноз с долей событий. Пустые интервалы не рисуются; '
        'распределение и счётчики показаны отдельно. Малочисленные верхние интервалы нестабильны. '
        'Отдельная калибровочная модель не обучалась.', '',
        '![Калибровка и распределение](calibration.png)', '', '![ROC и PR](ranking.png)', '',
        '## Ресурсы сохранённых моделей', '',
        '| Модель | Fit, с | Predict validation, с | Predict test, с | Файл, КБ |',
        '| --- | ---: | ---: | ---: | ---: |'])
    for family in FAMILIES:
        name = selection['family_winners'][family]
        record = validation['models'][name]
        lines.append(f'| {name} | {record["fit_seconds"]:.6f} | {record["predict_seconds"]:.6f} | '
            f'{evaluation["models"][name]["predict_seconds"]:.6f} | {record["size_bytes"] / 1000:.3f} |')
    measured = run_manifest['resources']
    lines.extend(['', f'Среда: Python {run_manifest["python"]}, {measured["platform"]}; '
        f'CPU quota {measured["cpu_quota"]}, threads={measured["threads"]}. '
        f'Функция train/validation без импортов и запуска Docker: {measured["runtime_seconds"]:.6f} с; '
        f'пик RSS процесса {measured["max_rss_bytes"] / 1e6:.2f} МБ (включая импорты). '
        'Fit не включает запуск Docker. КБ = 1000 байт, МБ = 1 000 000 байт. Значения относятся к одному замеру на этой платформе.', '',
        '## Объяснения пяти фиксированных validation-заявок', '',
        'Строки взяты по первым пяти application_id, без отбора по прогнозам или test. '
        'Полные исходные входы, преобразованные значения Logistic и вклады сохранены в explanations.json. '
        'Все вклады ниже — raw log odds, не процентные пункты. '
        'SHAP описывает прогноз CatBoost; линейные вклады Logistic не являются SHAP. '
        'Это не причины отказа и не эффект вмешательства: коррелирующие признаки могут делить вклад.', ''])
    for name, explanation in explanations['models'].items():
        role = 'выбранная модель' if name == selected else 'альтернативная модель'
        method = 'SHAP' if explanation['method'] == 'native_shap' else 'точные линейные вклады'
        lines.extend([f'### {name}: {role}, {method}', '',
            f'Расчёт {len(explanations["examples"])} строк: {explanation["latency_seconds"]:.6f} с '
            '(отдельно от fit, загрузки моделей и Docker startup).', '',
            '| Заявка | P(событие) | База → raw | Повышают raw log odds (до 3) | Снижают raw log odds (до 3) |',
            '| --- | ---: | ---: | --- | --- |'])
        for index, example in enumerate(explanations['examples']):
            lines.append(f'| {example["application_id"]} | {explanation["probabilities"][index]:.4%} | '
                f'{explanation["base_values"][index]:.4f} → {explanation["raw_predictions"][index]:.4f} | '
                f'{_top_factors(explanation, index, True)} | {_top_factors(explanation, index, False)} |')
    lines.extend(['', 'API, кредитная политика и интерфейс пока не используют эту модель. '
        'Другую цель и горизонт следует оценивать отдельным экспериментом: AUC разных целей напрямую несопоставимы.', ''])
    return '\n'.join(lines)


def build_report(data_dir: Path, run_dir: Path) -> dict:
    """Создаёт новый analysis из доверенных run/evaluation, не изменяя источники."""
    start = time.perf_counter()
    run_dir = Path(run_dir)
    ensure_new(run_dir / 'analysis')
    if run_dir.is_symlink():
        raise ValueError('Нужен обычный каталог run')
    for name in ('manifest.json', 'selection.json'):
        _plain_file(run_dir / name, run_dir)
    manifest = read_json(run_dir / 'manifest.json')
    selection = read_json(run_dir / 'selection.json')
    evaluation, predictions = _evaluation(run_dir, manifest, selection)
    reader, selection, models = load_run(data_dir, run_dir)
    validation = read_json(run_dir / 'validation.json')
    sources = {'dataset_manifest_sha256': reader.fingerprint,
        'run_manifest_sha256': sha256(run_dir / 'manifest.json'),
        'evaluation_manifest_sha256': sha256(run_dir / 'evaluation/manifest.json')}
    unchanged = {run_dir / name: digest for name, digest in manifest['sha256'].items()}
    unchanged.update({run_dir / 'evaluation' / name: digest for name, digest in
                      read_json(run_dir / 'evaluation/manifest.json')['sha256'].items()})
    unchanged.update({run_dir / 'manifest.json': sources['run_manifest_sha256'],
                      run_dir / 'evaluation/manifest.json': sources['evaluation_manifest_sha256']})
    validation_split = reader.split('validation')
    indices = validation_split.metadata.sort_values('application_id').index[:5]
    X = validation_split.X.loc[indices]
    explanations = dict(split='validation', selection='Первые пять application_id по возрастанию',
        selected_candidate_id=selection['selected_candidate_id'], examples=[], models={})
    for index in indices:
        inputs = {name: None if pd.isna(value) else value.item() if isinstance(value, np.generic) else value
                  for name, value in validation_split.X.loc[index].items()}
        explanations['examples'].append(dict(**validation_split.metadata.loc[index].to_dict(), inputs=inputs))
    for family, explain in [('logistic', explain_logistic), ('catboost', explain_catboost)]:
        name = selection['family_winners'][family]
        before = time.perf_counter()
        explanation = explain(models[name], X)
        explanation['latency_seconds'] = time.perf_counter() - before
        explanation['selected'] = name == selection['selected_candidate_id']
        explanation['feature_labels'] = [feature_label(name) for name in explanation['feature_names']]
        explanations['models'][name] = explanation
    with atomic_directory(run_dir / 'analysis') as staging:
        write_json(staging / 'explanations.json', explanations)
        (staging / 'comparison.md').write_text(_comparison(selection, validation, evaluation, explanations, manifest), encoding='utf-8')
        figures = report_figures(evaluation, predictions)
        try:
            for name, figure in zip(('calibration', 'ranking'), figures):
                for extension in ('png', 'svg'):
                    figure.savefig(staging / f'{name}.{extension}', dpi=160)
        finally:
            for figure in figures:
                plt.close(figure)
        if any(sha256(path) != digest for path, digest in unchanged.items()):
            raise ValueError('Источники run/evaluation изменились во время построения отчёта')
        write_json(staging / 'manifest.json', dict(selected_candidate_id=selection['selected_candidate_id'],
            sources=sources, source_sha256=source_hashes(), resources=resources(start, time.perf_counter()),
            sha256={path.name: sha256(path) for path in sorted(staging.iterdir())}))
    return dict(selected_candidate_id=selection['selected_candidate_id'], validation=validation, test=evaluation,
                analysis_dir=str(run_dir / 'analysis'))
