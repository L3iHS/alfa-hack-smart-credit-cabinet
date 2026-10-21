"""Командная сборка синтетических данных без запуска приложения."""

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
    args = parser.parse_args()
    try:
        manifest = build_dataset(args.output, count=args.rows, seed=args.seed)
    except (ValueError, OSError) as error:
        parser.exit(1, f'Ошибка: {error}\n')
    report = json.loads((args.output / 'report.json').read_text(encoding='utf-8'))
    parts = ', '.join(f'{name}={part["rows"]}' for name, part in report['splits'].items())
    print(f'Синтетические данные: {args.output}; строк: {manifest["count"]}; {parts}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
