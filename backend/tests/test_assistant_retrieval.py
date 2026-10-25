import pytest
from decimal import Decimal
from app.products.catalog import get_catalog


def test_knowledge_is_meaningful_versioned_and_uses_catalog():
    from app.assistant.knowledge import build_knowledge
    for version in ('demo-v1', 'demo-v2'):
        sources = build_knowledge(version)
        assert len(sources) >= 20
        assert len({s.id for s in sources}) == len(sources)
        assert all(s.version == version and len(s.text) > 50 for s in sources)
        products = get_catalog(version)
        for code, product in products.items():
            source = next(s for s in sources if s.id == f'product:{code}')
            from app.assistant.knowledge import DOCUMENTS
            from app.assistant.presentation import _decimal_text
            assert _decimal_text(Decimal(product.min_amount_kopecks) / 100, grouping=True) in source.text
            assert _decimal_text(Decimal(product.max_amount_kopecks) / 100, grouping=True) in source.text
            assert all(DOCUMENTS[kind][0] in source.text for kind in product.required_document_types)
            assert 'копе' not in source.text and '_invoice' not in source.text
        assert {s.id for s in sources if s.id.startswith('product:')} == {f'product:{code}' for code in products}


@pytest.mark.parametrize('question,code', [
    ('Какие документы нужны для кредита на оборудование?', 'equipment'),
    ('Хочу закупить сырьё перед сезоном, что мне подойдёт?', 'working_capital'),
    ('Как закрыть короткий кассовый разрыв до поступления денег?', 'overdraft'),
    ('Можно ли регулярно брать деньги из возобновляемого лимита?', 'credit_line'),
    ('Какое финансирование подходит для долгосрочного развития бизнеса?', 'investment'),
    ('Чем обеспечить обязательства перед заказчиком в тендере?', 'tender_guarantee'),
])
def test_full_russian_questions_find_useful_product(db, question, code):
    from app.assistant.retrieval import retrieve
    sources = retrieve(db, question, 'demo-v2')
    assert f'product:{code}' in [s.id for s in sources]
    assert len(sources) <= 5


def test_history_no_match_and_sql_input_are_safe(db):
    from app.assistant.retrieval import retrieve
    assert all(s.id != 'product:overdraft' for s in retrieve(db, 'овердрафт', 'demo-v1'))
    assert retrieve(db, 'космонавтика марсианский вулкан', 'demo-v2') == []
    assert retrieve(db, "'; DROP TABLE users; --", 'demo-v2') == []
    assert 0 < len(retrieve(db, 'документы', 'demo-v2', limit=100)) <= 5


def test_knowledge_tracks_catalog_changes_without_manual_numbers(monkeypatch):
    from app.assistant import knowledge
    catalog = get_catalog('demo-v2')
    catalog['equipment'] = catalog['equipment'].model_copy(update={'max_amount_kopecks': 123456789,
        'required_document_types': ('financial_statement', 'business_plan')})
    monkeypatch.setattr(knowledge, 'get_catalog', lambda version: catalog)
    source = next(s for s in knowledge.build_knowledge('demo-v2') if s.id == 'product:equipment')
    assert '1 234 567,89 ₽' in source.text and '123456789' not in source.text
    assert 'Бизнес-план' in source.text and 'Счёт на оборудование' not in source.text


def test_guarantee_paraphrase_does_not_match_equipment_by_substring(db):
    from app.assistant.retrieval import retrieve
    identifiers = [s.id for s in retrieve(db, 'Как обеспечить обязательства по тендеру?', 'demo-v2')]
    assert 'product:tender_guarantee' in identifiers
    assert 'product:equipment' not in identifiers
