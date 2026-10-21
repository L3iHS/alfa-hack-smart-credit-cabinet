"""Offline команды данных, обучения и оценки без запуска приложения."""

import argparse
import json
from pathlib import Path

from app.risk.dataset import build_dataset
from app.risk.synthetic import DEFAULT_SEED


def main() -> int:
    parser = argparse.ArgumentParser(description='Синтетические данные кредитного риска')
    subparsers = parser.add_subparsers(dest='command', required=True)
    build = subparsers.add_parser('build-data', help='Собрать новый каталог данных без обучения')
    build.add_argument('--output', type=Path, default=Path('artifacts/risk-data'), help='Новый каталог результата')
    build.add_argument('--rows', type=int, default=10000, help='Число заявок, не менее 20')
    build.add_argument('--seed', type=int, default=DEFAULT_SEED, help='Целочисленный seed')
    train = subparsers.add_parser('train-models', help='Сравнить модели только на train и validation')
    train.add_argument('--data', type=Path, default=Path('artifacts/risk-data'), help='Проверенный набор данных')
    train.add_argument('--output', type=Path, default=Path('artifacts/risk-models'), help='Новый каталог моделей')
    evaluate = subparsers.add_parser('evaluate-models', help='Один раз оценить сохранённый выбор на test')
    evaluate.add_argument('--data', type=Path, default=Path('artifacts/risk-data'), help='Исходный набор данных')
    evaluate.add_argument('--run', type=Path, default=Path('artifacts/risk-models'), help='Сохранённый эксперимент')
    args = parser.parse_args()
    try:
        if args.command != 'build-data':
            try:
                from app.risk.experiment import evaluate_experiment, train_experiment
            except ImportError:
                parser.exit(1, 'Ошибка: нужны ML-зависимости; выполните uv sync --extra ml\n')
            if args.command == 'train-models':
                result = train_experiment(args.data, args.output)
                print(f'Сравнение на validation: {args.output}; выбран {result["selected_candidate_id"]}; test не использован')
            else:
                result = evaluate_experiment(args.data, args.run)
                print(f'Оценка на test: {args.run / "evaluation"}; выбранная модель {result["selected_candidate_id"]}')
            return 0
        manifest = build_dataset(args.output, count=args.rows, seed=args.seed)
    except (ValueError, OSError) as error:
        parser.exit(1, f'Ошибка: {error}\n')
    report = json.loads((args.output / 'report.json').read_text(encoding='utf-8'))
    parts = ', '.join(f'{name}={part["rows"]}' for name, part in report['splits'].items())
    print(f'Синтетические данные: {args.output}; строк: {manifest["count"]}; {parts}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
