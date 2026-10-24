import importlib.util
from pathlib import Path

import pytest


def evaluator():
    path = Path(__file__).parents[1] / 'scripts/evaluate_assistant.py'
    spec = importlib.util.spec_from_file_location('evaluate_assistant', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixed_dataset_has_all_cases_and_only_synthetic_snapshots():
    module = evaluator()
    dataset = module.load_dataset(Path(__file__).parent / 'fixtures/assistant_eval.json')
    assert len(dataset['cases']) == 24
    assert dataset['cases'][-1]['id'] == 'S06'
    assert all(case['snapshot_kind'] == 'synthetic_materialized_sources' for case in dataset['cases'] if case['operation'] == 'summary')


def test_modified_case_count_is_rejected(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{"cases": []}')
    with pytest.raises(ValueError, match='24'):
        evaluator().load_dataset(path)


def test_nearest_rank_latency_uses_provider_calls_only():
    assert evaluator().latencies([1, 2, 3, 4, 20]) == {'p50_seconds': 3, 'p95_seconds': 20, 'method': 'nearest-rank', 'provider_calls': 5}


def test_intake_fields_do_not_self_certify_semantic_answer():
    module = evaluator()
    result = module.check_intake({'expected_fields': {'product_code': 'equipment', 'amount_kopecks': None, 'term_months': None}, 'expected_unsupported_need': False},
                                 {'suggested_fields': {'product_code': 'equipment', 'amount_kopecks': None, 'term_months': None}, 'unsupported_need': False})
    assert result['exact_fields_pass'] is True
    assert result['semantic_status'] == 'pending_review'


def test_evaluator_uses_shared_generation_and_validates_unknown_citation(db):
    module = evaluator()
    case = module.load_dataset(Path(__file__).parent / 'fixtures/assistant_eval.json')['cases'][18]
    class Provider:
        model = 'deterministic-test-only'
        def generate_json(self, **kwargs):
            return {'answer': 'fact', 'source_ids': ['unknown']}
    from app.assistant.provider import AssistantUnavailable
    with pytest.raises(AssistantUnavailable):
        module.evaluate_case(case, db, Provider())


def test_only_invalid_response_can_continue_without_retry():
    module = evaluator()
    from app.assistant.provider import AssistantUnavailable
    assert module.should_stop_provider(AssistantUnavailable('invalid_response')) is False
    for category in ('authentication', 'rate_limit', 'transport', 'unavailable'):
        assert module.should_stop_provider(AssistantUnavailable(category)) is True
