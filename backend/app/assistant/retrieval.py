import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assistant.knowledge import build_knowledge
from app.assistant.schemas import Source

# Из полного вопроса выбираем известный предмет поиска вместо AND по всей фразе.
_SYNONYMS = (
    (r'\b(?:оборудован\w*|печ[ьи]\w*|станок|станки)', 'оборудование'),
    (r'оборотн|сырь|товар|закуп', 'оборотный'),
    (r'овердрафт|кассов\w*\s+разрыв', 'овердрафт'),
    (r'кредитн\w*\s+лини|возобновляем\w*\s+лимит', 'кредитная линия'),
    (r'инвестици|долгосрочн|развити\w*\s+бизнес', 'инвестиционный'),
    (r'тендер|гаранти', 'тендерная гарантия'),
)


def retrieve(db: Session, question: str, catalog_version: str, limit: int = 5) -> list[Source]:
    sources = build_knowledge(catalog_version)
    selected = [canonical for pattern, canonical in _SYNONYMS if re.search(pattern, question.lower())]
    # Каждый элемент становится отдельным plainto_tsquery; между предметами действует OR.
    terms = selected or re.findall(r'[а-яёa-z]+', question.lower())
    if not terms or limit <= 0:
        return []
    params = {'terms': terms, 'limit': min(limit, 5)}
    rows = []
    for index, source in enumerate(sources):
        rows.append(f'(:id{index}, :title{index}, :text{index})')
        params.update({f'id{index}': source.id, f'title{index}': source.title, f'text{index}': source.text})
    # SQL-структура фиксирована; вопрос и весь корпус передаются только параметрами.
    query = text('''
        WITH corpus(id, title, body) AS (VALUES ''' + ','.join(rows) + '''),
        terms AS (SELECT plainto_tsquery('russian', term) AS q FROM unnest(CAST(:terms AS text[])) AS term),
        search AS (SELECT CAST(string_agg('(' || q::text || ')', ' | ') AS tsquery) AS q
                   FROM terms WHERE q::text <> ''),
        ranked AS (SELECT id, setweight(to_tsvector('russian', title), 'A') ||
                             setweight(to_tsvector('russian', body), 'B') AS document FROM corpus)
        SELECT id FROM ranked, search WHERE document @@ search.q
        ORDER BY ts_rank(document, search.q) DESC, id LIMIT :limit
    ''')
    by_id = {source.id: source for source in sources}
    return [by_id[identifier] for identifier in db.scalars(query, params)]
