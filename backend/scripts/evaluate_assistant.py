#!/usr/bin/env python3
"""Фиксированная оценка реального провайдера на синтетических снимках."""
import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.assistant.answers import validate_answer
from app.assistant.chat import generate_chat_response
from app.assistant.context import ApplicationContext, application_sources_for_question
from app.assistant.intake import extract_intake
from app.assistant.knowledge import build_knowledge
from app.assistant.provider import LLMProvider
from app.assistant.retrieval import retrieve
from app.assistant.schemas import IntakeInput, Source
from app.assistant.summary import generate_summary_response
from app.core.config import Settings

# CLI принимает конфигурацию только из окружения, без автоматической загрузки .env.
settings = Settings(_env_file=None)

IDS = [f'I{i:02}' for i in range(1, 9)] + [f'R{i:02}' for i in range(1, 11)] + [f'S{i:02}' for i in range(1, 7)]


def load_dataset(path):
    dataset = json.loads(path.read_text())
    if [case['id'] for case in dataset['cases']] != IDS:
        raise ValueError('Ожидались ровно 24 фиксированных случая I01–S06 в заданном порядке')
    for case in dataset['cases']:
        catalog = {source.id for source in build_knowledge(case['catalog_version'])}
        snapshots = case['sources_snapshot'] or (case.get('application_context') or {}).get('sources', [])
        for source in snapshots:
            Source.model_validate(source)
        allowed = catalog | {source['id'] for source in snapshots}
        if not set(case['allowed_citations']) <= allowed:
            raise ValueError('Неизвестная ссылка в наборе')
        if case['operation'] == 'summary':
            context = case['application_context']
            for field in ('application_id', 'revision_id', 'processing_run_id'):
                uuid.UUID(context[field])
            if case['snapshot_kind'] != 'synthetic_materialized_sources':
                raise ValueError('Ожидался синтетический снимок')
    return dataset


def latencies(values):
    ordered = sorted(values)
    return {'p50_seconds': ordered[math.ceil(len(ordered) * .5) - 1] if ordered else None,
            'p95_seconds': ordered[math.ceil(len(ordered) * .95) - 1] if ordered else None,
            'method': 'nearest-rank', 'provider_calls': len(ordered)}


def check_intake(case, output):
    fields = {key: output['suggested_fields'].get(key) == value for key, value in case['expected_fields'].items()}
    fields['unsupported_need'] = output['unsupported_need'] == case['expected_unsupported_need']
    return {'field_checks': fields, 'exact_fields_pass': all(fields.values()), 'semantic_status': 'pending_review'}


def should_stop_provider(error):
    return getattr(error, 'diagnostic_category', 'unavailable') != 'invalid_response'


class MeasuredProvider:
    def __init__(self, provider):
        self.provider, self.model = provider, provider.model
        self.calls = []
        self.raw = None
        self.failed = False

    def generate_json(self, **kwargs):
        started = time.perf_counter()
        try:
            self.raw = self.provider.generate_json(**kwargs)
            return self.raw
        except Exception:
            self.failed = True
            raise
        finally:
            self.calls.append(round(time.perf_counter() - started, 4))


def evaluate_case(case, db, provider):
    result = {'id': case['id'], 'operation': case['operation'], 'semantic_status': 'pending_review',
              'retrieved_sources': [], 'cited_sources': [], 'structural_status': 'not_run',
              'knowledge_version': case['catalog_version'],
              'application_version': (case['application_context'] or {}).get('version')}
    if case['operation'] == 'intake':
        output = extract_intake(IntakeInput(text=case['input'], catalog_version=case['catalog_version']), provider).model_dump(mode='json')
        result.update(check_intake(case, output))
    else:
        if case['operation'] == 'chat':
            sources = retrieve(db, case['input'], case['catalog_version'])
            result['retrieved_sources'] = [{'id': source.id, 'version': source.version} for source in sources]
            context = case['application_context']
            if context:
                materialized = ApplicationContext(uuid.UUID(context['application_id']), context['version'], context['catalog_version'],
                    [Source.model_validate(source) for source in context['sources']], context['product_code'], context['status'])
                sources += application_sources_for_question(materialized, case['input'])
            db.rollback()
            if not sources:
                result.update(structural_status='no_context', output={'status': 'insufficient_context', 'sources': [], 'model': None},
                              semantic_status='pending_review')
                return result
            raw = generate_chat_response(case['input'], sources, provider)
        else:
            result['snapshot_revision_id'] = case['application_context']['revision_id']
            result['snapshot_processing_run_id'] = case['application_context']['processing_run_id']
            result['snapshot_references_are_api_verified'] = False
            sources = [Source.model_validate(source) for source in case['sources_snapshot']]
            raw = generate_summary_response(sources, provider)
        generated, cited = validate_answer(raw, sources)
        output = {'status': 'answered', 'answer': generated.answer, 'source_ids': generated.source_ids, 'model': provider.model}
        result['cited_sources'] = [{'id': source.id, 'version': source.version} for source in cited]
        result['allowed_citations_pass'] = set(generated.source_ids) <= set(case['allowed_citations'])
        result['forbidden_marker_matches'] = [marker for marker in case.get('forbidden', []) if marker in generated.answer]
    result.update(structural_status='valid', output=output)
    return result


def markdown_report(report):
    lines = ['# Оценка помощника на фиксированных синтетических случаях', '',
             f"Модель: `{report['model']}`. Статус: `{report['status']}`.",
             'Режим: настоящий PostgreSQL retrieval и синтетические материализованные Source-снимки.',
             'Это отдельная проверка качества. Авторизация API, выбор текущего ORM-контекста и конкурентные изменения проверяются отдельными тестами.',
             'Содержательная оценка ожидает ревью; корректная схема и допустимые ссылки не доказывают верность ответа.', '',
             f"Вызовы провайдера: {report['latency']['provider_calls']}; p50={report['latency']['p50_seconds']} с; p95={report['latency']['p95_seconds']} с (nearest-rank).",
             f"Весь pipeline: {report['elapsed_seconds']} с.", '',
             '| Случай | Структура | Поля/ссылки | Семантика | Время, с |', '|---|---|---|---|---|']
    for row in report['cases']:
        check = row.get('exact_fields_pass', row.get('allowed_citations_pass'))
        lines.append(f"| {row['id']} | {row['structural_status']} | {check} | {row['semantic_status']} | {row['elapsed_seconds']} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path(__file__).resolve().parents[1] / 'tests/fixtures/assistant_eval.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--include-synthetic-responses', action='store_true', help='Сохранить ответы только фиксированных синтетических случаев для ревью')
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    if settings.llm_provider == 'disabled':
        parser.error('incomplete_provider_unavailable: настройте настоящий провайдер через environment')
    engine = create_engine(settings.database_url)
    if engine.dialect.name != 'postgresql':
        parser.error('Требуется отдельная PostgreSQL-база; поиск не подменяется SQLite')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        code_version = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True))
    except (OSError, subprocess.CalledProcessError):
        code_version, dirty = 'unavailable', None
    report = dict(dataset_version=dataset['dataset_version'], dataset_sha256=hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                  code_version=code_version, working_tree_dirty=dirty, date=datetime.now(timezone.utc).isoformat(),
                  provider=settings.llm_provider, model=settings.llm_model, json_mode=settings.llm_json_mode,
                  reasoning_enabled=settings.llm_reasoning_enabled, real_provider=True, reviewer_kind=None,
                  pipeline_mode='postgres_retrieval_with_synthetic_source_snapshots', context_builder_exercised=False,
                  api_authorization_exercised=False, semantic_status='pending_review', status='completed_pending_semantic_review', cases=[])
    provider = MeasuredProvider(LLMProvider(settings))
    started = time.perf_counter()
    stopped = False
    with Session(engine) as db:
        for case in dataset['cases']:
            case_started = time.perf_counter()
            provider.raw, provider.failed = None, False
            if stopped:
                result = dict(id=case['id'], operation=case['operation'], structural_status='not_run_provider_unavailable', semantic_status='not_run')
            else:
                try:
                    result = evaluate_case(case, db, provider)
                except Exception as error:
                    db.rollback()
                    result = dict(id=case['id'], operation=case['operation'], structural_status='provider_error' if provider.failed else 'validation_or_pipeline_error',
                                  error_type=type(error).__name__, semantic_status='not_evaluable')
                    if provider.failed:
                        result['diagnostic_category'] = getattr(error, 'diagnostic_category', 'unavailable')
                        if should_stop_provider(error):
                            stopped = True
                            report['status'] = 'incomplete_provider_unavailable'
            result['elapsed_seconds'] = round(time.perf_counter() - case_started, 4)
            result['expected'] = case['expected']
            if args.include_synthetic_responses:
                result['synthetic_response'] = provider.raw
            else:
                result.pop('output', None)
            report['cases'].append(result)
            report['elapsed_seconds'] = round(time.perf_counter() - started, 4)
            report['latency'] = latencies(provider.calls)
            report['no_context_count'] = sum(row['structural_status'] == 'no_context' for row in report['cases'])
            report['technical_error_count'] = sum(row['structural_status'] in ('provider_error', 'validation_or_pipeline_error') for row in report['cases'])
            report['not_run_count'] = sum(row['structural_status'] == 'not_run_provider_unavailable' for row in report['cases'])
            (args.output_dir / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            (args.output_dir / 'results.md').write_text(markdown_report(report))
            print(f"{case['id']}: {result['structural_status']}; semantic={result['semantic_status']}", flush=True)
    engine.dispose()
    print(f"{report['status']}; calls={len(provider.calls)}; semantic review pending", flush=True)
    return 2 if stopped else 0


if __name__ == '__main__':
    raise SystemExit(main())
