import json
from threading import BoundedSemaphore
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from app.core.config import Settings, settings

_MAX_RESPONSE_BYTES = 128 * 1024
_slots = BoundedSemaphore(2)


DiagnosticCategory = Literal['unavailable', 'invalid_response', 'authentication', 'rate_limit', 'transport']


class AssistantUnavailable(HTTPException):
    def __init__(self, diagnostic_category: DiagnosticCategory = 'unavailable'):
        # Только безопасная категория для локальной оценки; HTTP-контракт неизменен.
        self.diagnostic_category = (diagnostic_category if diagnostic_category in
            ('unavailable', 'invalid_response', 'authentication', 'rate_limit', 'transport') else 'unavailable')
        super().__init__(503, {'code': 'assistant_unavailable',
                              'message': 'Помощник временно недоступен. Продолжите заполнение формы или повторите позже.'})


class AssistantBusy(HTTPException):
    def __init__(self):
        super().__init__(429, {'code': 'assistant_busy',
                              'message': 'Помощник занят. Повторите запрос позже.'})


class Provider(Protocol):
    model: str

    def generate_json(self, *, system: str, user: str, schema: dict) -> dict: ...


def _reject_constant(value):
    raise ValueError('Некорректная JSON-константа')


def _parse_json(value: bytes | str) -> dict:
    result = json.loads(value, parse_constant=_reject_constant)
    if not isinstance(result, dict):
        raise ValueError('Ожидался JSON-объект')
    pending = [(result, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ValueError('Слишком глубокий JSON')
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return result


class LLMProvider:
    def __init__(self, config: Settings):
        self.config = config
        self.model = config.llm_model or ''

    def _request(self, system: str, user: str, schema: dict):
        config = self.config
        if config.llm_provider == 'disabled' or not config.llm_base_url or not self.model.strip():
            raise AssistantUnavailable()
        url = urlsplit(config.llm_base_url)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment):
            raise AssistantUnavailable()
        # Обращения к OpenRouter всегда ограничены выбранной бесплатной моделью.
        openrouter = url.hostname.lower() == 'openrouter.ai'
        if openrouter and (config.llm_provider != 'openai' or url.scheme != 'https'
                           or url.port not in (None, 443) or url.path.rstrip('/') != '/api/v1'
                           or not self.model.endswith(':free')):
            raise AssistantUnavailable()
        if config.llm_provider == 'openai' and config.llm_json_mode == 'json_object':
            system += '\nСхема обязательного JSON-ответа: ' + json.dumps(schema, ensure_ascii=False)
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
        payload = {'model': self.model, 'messages': messages, 'stream': False}
        headers = {}
        if config.llm_provider == 'ollama':
            endpoint = config.llm_base_url.rstrip('/') + '/api/chat'
            payload.update(format=schema, options={'num_predict': config.llm_max_tokens})
        else:
            endpoint = config.llm_base_url.rstrip('/') + '/chat/completions'
            payload['max_tokens'] = config.llm_max_tokens
            payload['response_format'] = ({'type': 'json_schema', 'json_schema': {
                'name': 'assistant_response', 'strict': True, 'schema': schema,
            }} if config.llm_json_mode == 'json_schema' else {'type': 'json_object'})
            if config.llm_api_key and config.llm_api_key.get_secret_value():
                headers['Authorization'] = 'Bearer ' + config.llm_api_key.get_secret_value()
            if openrouter:
                if not headers:
                    raise AssistantUnavailable()
                if config.llm_reasoning_enabled is not None:
                    payload['reasoning'] = {'enabled': config.llm_reasoning_enabled}
                payload['provider'] = {'allow_fallbacks': False, 'data_collection': config.llm_data_collection,
                                       'max_price': {'prompt': 0, 'completion': 0, 'request': 0}}
        return endpoint, payload, headers

    def generate_json(self, *, system: str, user: str, schema: dict) -> dict:
        if not _slots.acquire(blocking=False):
            raise AssistantBusy()
        try:
            endpoint, payload, headers = self._request(system, user, schema)
            # Поток ограничивается после распаковки HTTP, включая ответы без Content-Length.
            with httpx.Client(timeout=self.config.llm_timeout_seconds, follow_redirects=False,
                              trust_env=False) as client:
                with client.stream('POST', endpoint, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        category = ('rate_limit' if response.status_code == 429 else
                                    'authentication' if response.status_code in (401, 403) else 'unavailable')
                        raise AssistantUnavailable(category)
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=8192):
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE_BYTES:
                            raise AssistantUnavailable('invalid_response')
            envelope = _parse_json(body)
            if self.config.llm_provider == 'ollama':
                content = envelope['message']['content']
            else:
                content = envelope['choices'][0]['message']['content']
            if not isinstance(content, str):
                raise ValueError('Ожидался текст JSON')
            return _parse_json(content)
        except AssistantUnavailable:
            raise
        except httpx.HTTPError:
            raise AssistantUnavailable('transport') from None
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            raise AssistantUnavailable('invalid_response') from None
        finally:
            _slots.release()


def get_provider() -> Provider:
    return LLMProvider(settings)
