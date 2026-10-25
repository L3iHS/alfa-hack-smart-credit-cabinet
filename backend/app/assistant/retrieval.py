import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assistant.knowledge import build_knowledge
from app.assistant.schemas import ChatExchange, Source

# Из полного вопроса выбираем известный предмет поиска вместо AND по всей фразе.
_SYNONYMS = (
    (r'\b(?:оборудован\w*|печ[ьи]\w*|станок|станки)', 'оборудование'),
    (r'оборотн|сырь|товар|закуп', 'оборотный'),
    (r'овердрафт|кассов\w*\s+разрыв', 'овердрафт'),
    (r'кредитн\w*\s+лини|возобновляем\w*\s+лимит', 'кредитная линия'),
    (r'инвестици|долгосрочн|развити\w*\s+бизнес', 'инвестиционный'),
    (r'тендер|гаранти', 'тендерная гарантия'),
)

# Только короткие продолжения наследуют предмет. Произвольный новый вопрос
# (в том числе посторонний) не объединяется с прошлыми вопросами автоматически.
_FOLLOWUP = re.compile(
    r'(?:(?:а|и)\s+)?(?:почему(?:\s+(?:так|ты\s+так\s+считаешь|вы\s+так\s+считаете))?|'
    r'что\s+это\s+значит|(?:можешь|можете)\s+подробнее(?:\s+об\s+этом)?|'
    r'подробнее|поподробнее|объясни(?:те)?(?:\s+подробнее)?|'
    r'расскажи(?:те)?\s+подробнее|что\s+(?:дальше|теперь)|что\s+делать(?:\s+дальше)?|'
    r'(?:какие\s+)?документы(?:\s+ещ[её])?(?:\s+нужны)?|'
    r'(?:какие\s+)?условия|(?:какой\s+)?срок|(?:какая\s+)?(?:сумма|ставка)|'
    r'что\s+(?:с\s+)?(?:документами|условиями|суммой|сроком|дальнейшими\s+действиями))',
    re.IGNORECASE,
)
_SHORT_SUBJECT = re.compile(r'\b(?:документ|услови|срок|сумм|ставк)', re.IGNORECASE)
_NEXT_STEP = re.compile(r'\b(?:дальше|действи)', re.IGNORECASE)


def dialog_question(question: str, history: list[ChatExchange]) -> str:
    """Предмет ближайшего вопроса для одного поиска; старые ответы не участвуют."""
    def continuation(value):
        return _FOLLOWUP.fullmatch(re.sub(r'[^\w\s]', '', value).strip()) is not None

    if continuation(question):
        # Общая реплика не добавляет предмет поиска: «дальше» не должно
        # включать снимок заявки, когда найденный предок — вопрос о Марсе.
        detail = f'\n{question}' if _SHORT_SUBJECT.search(question) else ''
        short_subject = None
        next_step = None
        for exchange in reversed(history):
            if not continuation(exchange.question):
                # Продукт уточняет «А документы?». Посторонняя тема ограничивает
                # поиск назад, но не отменяет более новый вопрос «Какая сумма?».
                product_subject = any(re.search(pattern, exchange.question.lower()) for pattern, _ in _SYNONYMS)
                subject = short_subject if short_subject and not product_subject else exchange.question
                return f'{subject}{detail}'
            if short_subject is None and _SHORT_SUBJECT.search(exchange.question):
                short_subject = exchange.question
            if next_step is None and _NEXT_STEP.search(exchange.question):
                next_step = exchange.question
        # Общий следующий шаг — fallback только без самостоятельного предка;
        # он продолжает найденную тему и не отменяет посторонний предмет.
        subject = short_subject or next_step
        if subject:
            return f'{subject}{detail}'
    return question


def retrieve(db: Session, question: str, catalog_version: str, limit: int = 5) -> list[Source]:
    sources = build_knowledge(catalog_version)
    selected = [canonical for pattern, canonical in _SYNONYMS if re.search(pattern, question.lower())]
    if re.search(r'каталог|перечень|список\s+продукт', question.lower()):
        selected.append('состав версии каталога')
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
