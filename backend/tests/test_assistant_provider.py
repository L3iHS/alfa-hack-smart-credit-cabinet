import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings, settings


def configured(**kwargs):
    return Settings(_env_file=None, database_url=settings.database_url,
                    demo_password=settings.demo_password, llm_provider='openai',
                    llm_base_url='https://openrouter.ai/api/v1', llm_model='vendor/model:free',
                    llm_api_key=SecretStr('private-key'), **kwargs)


def provider(monkeypatch, handler, config=None):
    from app.assistant.provider import LLMProvider

    real_client = httpx.Client

    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, 'Client', client)
    return LLMProvider(config or configured())


def completion(content='{"ok": true}'):
    return httpx.Response(200, json={'choices': [{'message': {'content': content}}]})


def test_openrouter_uses_explicit_free_model_and_zero_price(monkeypatch):
    captured = []

    def handler(request):
        captured.append(request)
        return completion()

    actual = provider(monkeypatch, handler).generate_json(system='rules', user='data', schema={'type': 'object'})
    assert actual == {'ok': True}
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == 'https://openrouter.ai/api/v1/chat/completions'
    body = json.loads(request.content)
    assert body['model'] == 'vendor/model:free'
    assert body['provider'] == {'allow_fallbacks': False, 'max_price': {'prompt': 0, 'completion': 0, 'request': 0}, 'data_collection': 'deny'}
    assert body['response_format'] == {'type': 'json_object'}
    assert body['messages'][0]['role'] == 'system'
    assert body['messages'][0]['content'].startswith('rules')
    assert body['messages'][1] == {'role': 'user', 'content': 'data'}
    assert request.headers['authorization'] == 'Bearer private-key'


@pytest.mark.parametrize('model,url', [
    ('vendor/paid', 'https://openrouter.ai/api/v1'), ('openrouter/free', 'https://openrouter.ai/api/v1'),
    ('vendor/model:free', 'http://openrouter.ai/api/v1'),
    ('vendor/model:free', 'https://openrouter.ai/other'),
    ('vendor/model:free', 'https://user:pass@host.test/v1'),
    ('vendor/model:free', 'file:///tmp/model'),
])
def test_unsafe_configuration_never_sends_http(monkeypatch, model, url):
    from app.assistant.provider import AssistantUnavailable

    config = configured()
    config.llm_model, config.llm_base_url = model, url

    def forbidden(request):
        pytest.fail('Небезопасный запрос не должен отправляться')

    with pytest.raises(AssistantUnavailable):
        provider(monkeypatch, forbidden, config).generate_json(system='s', user='u', schema={})


@pytest.mark.parametrize('response', [
    httpx.Response(302, headers={'Location': 'https://paid.test'}),
    httpx.Response(429, text='private provider details'), httpx.Response(500),
    completion('not JSON'), completion('[]'), completion('{"ok": NaN}'),
    httpx.Response(200, content=b'x' * (128 * 1024 + 1)),
    completion(' {"nested": ' + '[' * 2000 + '0' + ']' * 2000 + '}'),
])
def test_transport_and_json_failures_are_safe_without_retry(monkeypatch, response):
    from app.assistant.provider import AssistantUnavailable
    calls = []

    def handler(request):
        calls.append(request)
        return response

    with pytest.raises(AssistantUnavailable) as exc:
        provider(monkeypatch, handler).generate_json(system='s', user='u', schema={})
    assert 'private' not in str(exc.value)
    assert len(calls) == 1


def test_timeout_is_safe(monkeypatch):
    from app.assistant.provider import AssistantUnavailable

    def handler(request):
        raise httpx.ReadTimeout('private message')

    with pytest.raises(AssistantUnavailable):
        provider(monkeypatch, handler).generate_json(system='s', user='u', schema={})


@pytest.mark.parametrize('kind', ['ollama', 'schema'])
def test_supported_protocol_modes(monkeypatch, kind):
    config = configured()
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}
    if kind == 'ollama':
        config.llm_provider, config.llm_base_url, config.llm_model = 'ollama', 'http://localhost:11434', 'qwen:8b'
    else:
        config.llm_json_mode = 'json_schema'

    def handler(request):
        body = json.loads(request.content)
        if kind == 'ollama':
            assert str(request.url) == 'http://localhost:11434/api/chat'
            assert body['format'] == schema and body['stream'] is False
            assert 'authorization' not in request.headers
            return httpx.Response(200, json={'message': {'content': '{"ok": true}'}})
        assert body['response_format']['json_schema']['schema'] == schema
        assert body['response_format']['json_schema']['strict'] is True
        return completion()

    assert provider(monkeypatch, handler, config).generate_json(system='s', user='u', schema=schema) == {'ok': True}


def test_third_simultaneous_call_is_busy_and_slots_are_released(monkeypatch):
    from app.assistant.provider import AssistantBusy
    entered = [Event(), Event()]
    release = Event()
    count = []

    def handler(request):
        index = len(count)
        count.append(request)
        if index < 2:
            entered[index].set()
            assert release.wait(5)
        return completion()

    instance = provider(monkeypatch, handler)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(instance.generate_json, system='s', user='u', schema={}) for _ in range(2)]
        try:
            assert all(event.wait(5) for event in entered)
            with pytest.raises(AssistantBusy):
                instance.generate_json(system='s', user='u', schema={})
        finally:
            release.set()
        assert [future.result() for future in pending] == [{'ok': True}, {'ok': True}]
    assert instance.generate_json(system='s', user='u', schema={}) == {'ok': True}


def test_json_object_mode_supplies_the_shape_to_the_model(monkeypatch):
    schema = {'type': 'object', 'properties': {'facts': {'type': 'array'}}}

    def handler(request):
        body = json.loads(request.content)
        system = body['messages'][0]['content']
        assert system.startswith('rules')
        assert json.dumps(schema, ensure_ascii=False) in system
        return completion()

    assert provider(monkeypatch, handler).generate_json(system='rules', user='data', schema=schema) == {'ok': True}


def test_actual_intake_schema_is_accepted_by_a_strict_transport(monkeypatch):
    from app.assistant.intake import extract_intake
    from app.assistant.schemas import IntakeInput

    config = configured()
    config.llm_json_mode = 'json_schema'

    def check_objects(node):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                assert node.get('additionalProperties') is False
                assert set(node.get('required', [])) == set(node.get('properties', {}))
            assert 'default' not in node
            for child in node.values():
                check_objects(child)
        elif isinstance(node, list):
            for child in node:
                check_objects(child)

    def handler(request):
        body = json.loads(request.content)
        structured = body['response_format']['json_schema']
        assert structured['strict'] is True
        schema = structured['schema']
        check_objects(schema)
        evidence_ref = schema['properties']['evidence']['$ref'].rsplit('/', 1)[-1]
        evidence = schema['$defs'][evidence_ref]
        assert set(evidence['properties']) == {'product_code', 'amount_kopecks', 'term_months', 'purpose'}
        assert all({'type': 'null'} in value['anyOf'] for value in evidence['properties'].values())
        fields_ref = schema['properties']['suggested_fields']['$ref'].rsplit('/', 1)[-1]
        assert all({'type': 'null'} in value['anyOf'] for value in schema['$defs'][fields_ref]['properties'].values())
        result = {'suggested_fields': {'product_code': 'equipment', 'amount_kopecks': 200_000_000,
                                        'term_months': 24, 'purpose': None},
                  'evidence': {'product_code': 'оборудование', 'amount_kopecks': '2 млн',
                               'term_months': '24 месяца', 'purpose': None},
                  'questions': [], 'unsupported_need': False}
        return completion(json.dumps(result, ensure_ascii=False))

    actual = extract_intake(IntakeInput(text='Нужен кредит на оборудование на 24 месяца, 2 млн'),
                            provider(monkeypatch, handler, config))
    assert actual.suggested_fields.amount_kopecks == 200_000_000
    assert actual.suggested_fields.term_months == 24
    assert 'purpose' not in actual.evidence


@pytest.mark.parametrize('enabled', [None, False, True])
def test_openrouter_reasoning_is_only_sent_when_explicit(monkeypatch, enabled):
    config = configured()
    config.llm_reasoning_enabled = enabled
    def handler(request):
        body = json.loads(request.content)
        if enabled is None:
            assert 'reasoning' not in body
        else:
            assert body['reasoning'] == {'enabled': enabled}
        return completion()
    provider(monkeypatch, handler, config).generate_json(system='s', user='u', schema={})


def test_other_provider_does_not_receive_openrouter_reasoning(monkeypatch):
    config = configured()
    config.llm_base_url = 'https://model.test/v1'
    config.llm_reasoning_enabled = False
    def handler(request):
        assert 'reasoning' not in json.loads(request.content)
        return completion()
    provider(monkeypatch, handler, config).generate_json(system='s', user='u', schema={})


@pytest.mark.parametrize('status,content,category', [(200, 'not JSON', 'invalid_response'), (429, '', 'rate_limit'), (401, '', 'authentication'), (503, '', 'unavailable')])
def test_safe_diagnostics_distinguish_case_format_from_outage(monkeypatch, status, content, category):
    from app.assistant.provider import AssistantUnavailable
    response = completion(content) if status == 200 else httpx.Response(status, text='private detail')
    with pytest.raises(AssistantUnavailable) as exc:
        provider(monkeypatch, lambda request: response).generate_json(system='s', user='u', schema={})
    assert exc.value.diagnostic_category == category
    assert exc.value.status_code == 503
    assert exc.value.detail['code'] == 'assistant_unavailable'
    assert 'private' not in str(exc.value.detail)


def test_timeout_diagnostic_is_transport(monkeypatch):
    from app.assistant.provider import AssistantUnavailable
    def handler(request):
        raise httpx.ReadTimeout('private detail')
    with pytest.raises(AssistantUnavailable) as exc:
        provider(monkeypatch, handler).generate_json(system='s', user='u', schema={})
    assert exc.value.diagnostic_category == 'transport'


def test_diagnostic_category_cannot_copy_arbitrary_provider_text():
    from app.assistant.provider import AssistantUnavailable
    error = AssistantUnavailable('private provider text')
    assert error.diagnostic_category == 'unavailable'
