import json
from datetime import date, datetime, timezone

import pytest

from app.core.config import Settings


@pytest.mark.parametrize('value,expected', [
    (datetime(2026, 10, 24, 17, 36, tzinfo=timezone.utc), '24.10.2026 20:36 МСК'),
    (datetime(2026, 10, 24, 23, 45, tzinfo=timezone.utc), '25.10.2026 02:45 МСК'),
    (date(2026, 10, 24), '24.10.2026'),
    (datetime(2026, 10, 24, 20, 36), '24.10.2026 20:36'),
])
def test_source_dates_match_moscow_cabinet_time(value, expected):
    from app.assistant.context import _date_text
    assert _date_text(value) == expected


@pytest.mark.parametrize('value,expected', [('', None), ('false', False), ('true', True)])
def test_optional_reasoning_configuration(value, expected):
    config = Settings(_env_file=None, database_url='postgresql://unused', demo_password='long-password', llm_reasoning_enabled=value)
    assert config.llm_reasoning_enabled is expected


def test_shared_generation_preserves_raw_response_for_access_check():
    from app.assistant.chat import generate_chat_response
    from app.assistant.summary import generate_summary_response
    from app.assistant.schemas import Source

    class RecordingProvider:
        model = 'test'
        def generate_json(self, **kwargs):
            self.prompt = json.loads(kwargs['user'])
            return {'answer': 'fact', 'source_ids': ['unavailable']}

    provider = RecordingProvider()
    sources = [Source(id='source', title='title', text='fact', version='1')]
    assert generate_chat_response('question', sources, provider)['source_ids'] == ['unavailable']
    assert provider.prompt['question'] == 'question'
    assert generate_summary_response(sources, provider)['source_ids'] == ['unavailable']
    assert provider.prompt['sources'] == [sources[0].model_dump()]


def test_catalog_composition_is_versioned_and_retrievable(db):
    from app.assistant.retrieval import retrieve
    sources = retrieve(db, 'Какие продукты входят в старый каталог?', 'demo-v1')
    source = next(item for item in sources if item.id == 'catalog:products')
    assert 'equipment' in source.text and 'working_capital' in source.text
    assert 'credit_line' not in source.text
    assert source.version == 'demo-v1'
