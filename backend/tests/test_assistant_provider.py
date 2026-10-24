import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, settings


def configured(**kwargs):
    # Настройки теста не должны наследовать рабочие ценовые ограничения из окружения.
    limits = {'llm_polza_max_prompt_rub': 0, 'llm_polza_max_completion_rub': 0}
    limits.update(kwargs)
    return Settings(_env_file=None, database_url=settings.database_url,
                    demo_password=settings.demo_password, llm_provider='openai',
                    llm_base_url='https://openrouter.ai/api/v1', llm_model='vendor/model:free',
                    llm_api_key=SecretStr('private-key'), **limits)


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


def polza_config(**kwargs):
    config = configured(**kwargs)
    config.llm_base_url = 'https://polza.ai/api/v1'
    config.llm_model = 'deepseek/deepseek-v4.1-flash-1017'
    return config


@pytest.mark.parametrize('host', ['polza.ai', 'polza.ai.'])
def test_polza_sends_ruble_price_caps_and_bounded_generation(monkeypatch, host):
    config = polza_config(llm_polza_max_prompt_rub=15, llm_polza_max_completion_rub=25,
                          llm_reasoning_enabled=False, llm_max_tokens=2048)
    config.llm_base_url = f'https://{host}/api/v1'

    def handler(request):
        assert str(request.url) == f'https://{host}/api/v1/chat/completions'
        body = json.loads(request.content)
        assert body['provider'] == {'allow_fallbacks': False, 'sort': 'price',
                                   'max_price': {'prompt': 15, 'completion': 25, 'request': 0}}
        assert body['reasoning'] == {'enabled': False}
        assert body['max_tokens'] == 2048
        assert body['response_format'] == {'type': 'json_object'}
        return completion()

    assert provider(monkeypatch, handler, config).generate_json(system='s', user='u', schema={}) == {'ok': True}


@pytest.mark.parametrize('change', [
    {}, {'llm_polza_max_prompt_rub': 15}, {'llm_polza_max_completion_rub': 25},
    {'llm_base_url': 'http://polza.ai/api/v1'},
    {'llm_base_url': 'https://polza.ai/other'},
    {'llm_base_url': 'https://polza.ai:444/api/v1'},
    {'llm_provider': 'ollama'}, {'llm_api_key': None},
    {'llm_model': 'deepseek/deepseek-v4.1-flash-1017@allow_fallbacks=true'},
])
def test_polza_missing_caps_or_invalid_endpoint_never_sends_http(monkeypatch, change):
    from app.assistant.provider import AssistantUnavailable

    caps = {} if not change or any(key.startswith('llm_polza_') for key in change) else {
        'llm_polza_max_prompt_rub': 15, 'llm_polza_max_completion_rub': 25}
    config = polza_config(**caps)
    for key, value in change.items():
        setattr(config, key, value)

    def forbidden(request):
        pytest.fail('Запрос без корректных ограничений не должен отправляться')

    with pytest.raises(AssistantUnavailable):
        provider(monkeypatch, forbidden, config).generate_json(system='s', user='u', schema={})


@pytest.mark.parametrize('field', ['llm_polza_max_prompt_rub', 'llm_polza_max_completion_rub'])
@pytest.mark.parametrize('value', [-1, float('nan'), float('inf')])
def test_invalid_polza_price_caps_are_rejected(field, value):
    with pytest.raises(ValidationError):
        configured(**{field: value})


@pytest.mark.parametrize('policy', ['deny', 'allow'])
def test_openrouter_data_collection_setting_preserves_free_only(monkeypatch, policy):
    def handler(request):
        routing = json.loads(request.content)['provider']
        assert routing == {'data_collection': policy, 'allow_fallbacks': False,
                           'max_price': {'prompt': 0, 'completion': 0, 'request': 0}}
        return completion()

    config = configured(llm_data_collection=policy)
    provider(monkeypatch, handler, config).generate_json(system='s', user='u', schema={})


def test_invalid_data_collection_setting_is_rejected():
    with pytest.raises(ValidationError):
        configured(llm_data_collection='yes')


@pytest.mark.parametrize('kind', ['openai', 'ollama'])
def test_data_collection_setting_is_not_sent_to_other_providers(monkeypatch, kind):
    config = configured(llm_data_collection='allow')
    config.llm_provider = kind
    config.llm_base_url = 'https://model.test/v1'

    def handler(request):
        body = json.loads(request.content)
        assert 'provider' not in body
        assert 'data_collection' not in body
        if kind == 'ollama':
            return httpx.Response(200, json={'message': {'content': '{"ok": true}'}})
        return completion()

    provider(monkeypatch, handler, config).generate_json(system='s', user='u', schema={})


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
    ('vendor/paid', 'https://openrouter.ai./api/v1'),
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
def test_transport_and_json_failures_are_safe_without_retry(monkeypatch, response, caplog):
    from app.assistant.provider import AssistantUnavailable
    calls = []

    def handler(request):
        calls.append(request)
        return response

    with pytest.raises(AssistantUnavailable) as exc:
        provider(monkeypatch, handler).generate_json(system='s', user='u', schema={})
    assert 'private' not in str(exc.value)
    assert len(calls) == 1
    assert exc.value.diagnostic_category in caplog.text
    assert 'private' not in caplog.text


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
