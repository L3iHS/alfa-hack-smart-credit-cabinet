"""Сохранение только проверенных сводок, без влияния на кредитное решение."""
import hashlib
import json

from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert

from app.assistant.models import ApplicationSummary
from app.assistant.schemas import SummaryOutput
from app.core.config import settings


def row_data(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns} if row else None


def fingerprint(data, provider, system, schema):
    config = getattr(provider, 'config', settings)
    identity = {name: getattr(config, name, None) for name in (
        'llm_provider', 'llm_base_url', 'llm_json_mode', 'llm_max_tokens', 'llm_reasoning_enabled',
        'llm_data_collection')}
    identity.update(model=provider.model, implementation=f'{type(provider).__module__}.{type(provider).__qualname__}')
    payload = {'sources': data, 'provider': identity, 'prompt_version': 'summary-1',
               'system': system, 'schema': schema, 'response_schema': SummaryOutput.model_json_schema()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def read_summary(db, application_id, version, key):
    row = db.get(ApplicationSummary, (application_id, version, key))
    if row:
        try:
            result = SummaryOutput.model_validate_json(json.dumps(row.response))
            if result.status == 'answered' and result.application_version == version:
                return result
        except (ValueError, ValidationError):
            pass
    return None


def save_summary(db, application_id, version, key, started_at, result):
    statement = insert(ApplicationSummary).values(application_id=application_id, application_version=version,
        fingerprint=key, request_started_at=started_at, response=result.model_dump(mode='json'))
    # Ответ более раннего запроса не заменяет уже завершившееся позднее обновление.
    db.execute(statement.on_conflict_do_update(index_elements=[ApplicationSummary.application_id,
        ApplicationSummary.application_version, ApplicationSummary.fingerprint], set_={
            'request_started_at': statement.excluded.request_started_at, 'response': statement.excluded.response},
        where=ApplicationSummary.request_started_at <= statement.excluded.request_started_at))
    db.flush()
    db.expire_all()
    return read_summary(db, application_id, version, key)
