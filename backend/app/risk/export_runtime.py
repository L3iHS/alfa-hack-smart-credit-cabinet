"""Offline-экспорт только принятой LR; обучение и чтение test-признаков запрещены."""

import argparse
import hashlib
import json
from pathlib import Path

from app.risk import runtime

# Эти SHA принадлежат принятому запуску и задают границу доверия до joblib.load.
_ACCEPTED_RUN_SHA256 = 'a1d80cb08ceae8f4d7d614af28df946ebf512915f695a869fed8fcc71c898f12'
_ACCEPTED_DATA_SHA256 = '6ee85a3c9de3ec3a5fc19f2448e81b00151c05f2be9f113b11b569b5b8849bd0'
_ACCEPTED_MODEL_SHA256 = 'd3a1ea133df94da0b3ef6d12d3e26db3c594ac2583eb70aba0c56ca8a4258a1a'


def _verified_bytes(path, digest):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Нужен обычный файл принятого запуска')
    contents = path.read_bytes()
    if hashlib.sha256(contents).hexdigest() != digest:
        raise ValueError(f'{path.name}: SHA256 не соответствует принятому запуску')
    return contents


def _verify_source(data, run):
    if data.is_symlink() or run.is_symlink() or not data.is_dir() or not run.is_dir():
        raise ValueError('Нужны обычные каталоги принятого набора и запуска')
    manifest = json.loads(_verified_bytes(run / 'manifest.json', _ACCEPTED_RUN_SHA256))
    _verified_bytes(data / 'manifest.json', _ACCEPTED_DATA_SHA256)
    if (manifest['sha256']['models/lr_c1.joblib'] != _ACCEPTED_MODEL_SHA256
            or manifest['dataset_manifest_sha256'] != _ACCEPTED_DATA_SHA256
            or manifest['feature_schema_version'] != 'risk-features-v1'
            or manifest['target'] != 'loan_90dpd_12m' or manifest['data_kind'] != 'synthetic'
            or manifest['horizon']['months'] != 12):
        raise ValueError('Несовместимые метаданные принятого запуска')
    if (run / 'models').is_symlink():
        raise ValueError('Каталог моделей не должен быть символической ссылкой')
    _verified_bytes(run / 'models/lr_c1.joblib', _ACCEPTED_MODEL_SHA256)
    return manifest


def export_runtime(data: Path, run: Path, output: Path) -> dict:
    """Экспортирует принятую модель и проверяет все 1500 validation без fit/evaluate."""
    data, run, output = Path(data), Path(run), Path(output)
    manifest = _verify_source(data, run)
    if output.exists():
        raise ValueError('Выходной файл уже существует')
    # Тяжёлые зависимости и десериализация доступны только после проверки доверенных SHA.
    from app.risk.artifacts import load_run
    from app.risk.explanations import explain_logistic
    from app.risk.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, FeatureVector
    from app.risk.training_data import MASK_FEATURES

    reader, selection, models = load_run(data, run)
    if selection['selected_candidate_id'] != 'lr_c1':
        raise ValueError('В принятом запуске должна быть выбрана lr_c1')
    estimator = models['lr_c1'].estimator
    preprocessor = estimator.named_steps['preprocessor']
    numeric = preprocessor.named_transformers_['numeric']
    model = estimator.named_steps['model']
    if list(model.classes_) != [0, 1] or model.coef_.shape != (1, 19):
        raise ValueError('Нужна бинарная LogisticRegression принятой формы')
    bundle = dict(
        bundle_schema_version=1, model_version=runtime.MODEL_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION, target_event=manifest['target'],
        horizon_months=manifest['horizon']['months'], data_kind=manifest['data_kind'],
        numeric_features=[name for name in FEATURE_NAMES if name != 'product_code'],
        categorical_feature='product_code',
        categories=preprocessor.named_transformers_['product'].categories_[0].tolist(),
        mask_features=list(MASK_FEATURES),
        transformed_features=preprocessor.get_feature_names_out().tolist(),
        imputation_medians=numeric.named_steps['imputer'].statistics_.tolist(),
        scaling_means=numeric.named_steps['scaler'].mean_.tolist(),
        scaling_scales=numeric.named_steps['scaler'].scale_.tolist(),
        coefficients=model.coef_[0].tolist(), intercept=float(model.intercept_[0]),
        provenance=dict(candidate_id='lr_c1', model_sha256=_ACCEPTED_MODEL_SHA256,
                        run_manifest_sha256=_ACCEPTED_RUN_SHA256,
                        dataset_manifest_sha256=_ACCEPTED_DATA_SHA256,
                        protocol_version=manifest['protocol_version'],
                        source_revision=manifest['source_revision'],
                        source_sha256=manifest['source_sha256'], libraries=manifest['libraries'],
                        python=manifest['python'],
                        dataset_version=manifest['dataset_version'],
                        target_version=manifest['target_version'],
                        generator_version=manifest['generator_version'],
                        catalog_version=manifest['catalog_version']),
    )
    frozen = runtime._decode_model(bundle, runtime.MODEL_VERSION)
    validation = reader.split('validation')
    if len(validation.X) != 1500:
        raise ValueError('Ожидаются все 1500 принятых validation строк')
    reference = explain_logistic(models['lr_c1'], validation.X)
    probability_error = contribution_error = raw_error = 0.0
    for index, row in enumerate(validation.X.to_dict('records')):
        masks = {name: bool(row[f'{name}_missing']) for name in FEATURE_NAMES}
        values = {name: None if masks[name] else row[name] for name in FEATURE_NAMES}
        result = runtime._predict(FeatureVector(values, masks), frozen, runtime.MODEL_VERSION)
        probability_error = max(probability_error, abs(result.probability - reference['probabilities'][index]))
        contribution_error = max(contribution_error, *(abs(f.contribution - wanted)
            for f, wanted in zip(result.contributions, reference['contributions'][index])))
        raw_error = max(raw_error, abs(result.raw_prediction - reference['raw_predictions'][index]))
        if result.base_value != reference['base_values'][index]:
            raise ValueError('Базовый log odds не совпадает с принятой LR')
    if probability_error > 1e-10 or contribution_error > 1e-8 or raw_error > 1e-8:
        raise ValueError('Экспорт не прошёл проверку эквивалентности validation')
    bundle['provenance']['validation_parity'] = dict(
        rows=1500, probability_max_abs_error=probability_error,
        contribution_max_abs_error=contribution_error, raw_max_abs_error=raw_error,
        probability_atol=1e-10, explanation_atol=1e-8, split='validation', test_used=False)
    contents = (json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(contents)
    return dict(output=str(output), sha256=hashlib.sha256(contents).hexdigest(),
                **bundle['provenance']['validation_parity'])


def main():
    parser = argparse.ArgumentParser(description='Экспорт принятой LR без обучения и оценки test')
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_runtime(args.data, args.run, args.output), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
