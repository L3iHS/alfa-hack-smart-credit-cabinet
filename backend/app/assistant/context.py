import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.applications.service import application_output, get_application
from app.assistant.schemas import Source
from app.auth.models import User
from app.auth.service import session_from_request
from app.processing.service import latest_revision
from app.products.catalog import get_product


@dataclass(frozen=True)
class ApplicationContext:
    application_id: uuid.UUID
    version: int
    catalog_version: str
    sources: list[Source]
    product_code: str = ''
    status: str = ''


# Узкий словарь предметов кабинета: id сам по себе не делает снимок релевантным.
_APPLICATION_SUBJECT = re.compile(
    r'\b(?:заявк|сумм|запросил|попросил|срок|цел[ьи]|назначен|'
    r'статус|этап|рассмотр|решени|результат|одобр|отказ|причин|дальше|действи|'
    r'документ|вложен|файл|уточн|предлож|услови|финанс|выруч|доход|расход|'
    r'долг|плат[её]ж|ставк|комисси|период|риск|оценк|продукт|кредит|'
    r'оборудован|овердрафт|оборотн|сырь|закуп|гарант|тендер|инвестици|оформлен|сделк|выдан|лимит)', re.IGNORECASE,
)


def application_sources_for_question(context: ApplicationContext, question: str) -> list[Source]:
    # Это выбор известного предмета, а не обещание общего понимания произвольного текста.
    return context.sources if _APPLICATION_SUBJECT.search(question) else []


def version_conflict():
    return HTTPException(409, {'code': 'version_conflict', 'message': 'Заявка изменилась, обновите страницу'})


def _date_text(value):
    if isinstance(value, datetime):
        # В справочных источниках используем московское время кабинета, а не UTC из БД.
        if value.tzinfo is not None:
            value = value.astimezone(timezone(timedelta(hours=3)))
            return value.strftime('%d.%m.%Y %H:%M МСК')
        return value.strftime('%d.%m.%Y %H:%M')
    if isinstance(value, date):
        return value.strftime('%d.%m.%Y')
    return str(value)


def build_application_context(db: Session, user: User, application_id: uuid.UUID,
                              expected_version: int) -> ApplicationContext:
    application = get_application(db, user, application_id)
    if application.version != expected_version:
        raise version_conflict()
    output = application_output(application, user)
    revision = latest_revision(db, application.id)
    revision_id = revision.id if revision else None
    sources = []

    def add(suffix, title, data):
        sources.append(Source(id=f'application:{application.id}:{suffix}', title=title,
                              text=json.dumps(data, ensure_ascii=False, default=_date_text), version=str(output.version)))

    # Белый список публичной схемы: ORM/assessment и внутренние причины сюда не попадают.
    fields = ('product_code', 'purpose', 'description', 'tender_number', 'beneficiary_name', 'project_description',
              'amount_kopecks', 'term_months', 'period_start', 'period_end', 'revenue_kopecks',
              'operating_expenses_kopecks', 'existing_debt_payments_kopecks')
    request_data = {field: getattr(output, field) for field in fields}
    request_data['product_name'] = get_product(output.product_code, output.catalog_version).name
    add('request', 'Данные заявки', request_data)
    add('state', 'Состояние и доступные действия', {'status': output.status,
        'public_reasons': output.public_reasons, 'available_actions': output.available_actions,
        'processing_status': output.processing_status})
    if output.deal:
        from app.deals.service import COMPLETION_TEXT, DEMO_NOTE
        labels = {'prepared': 'Условия подготовлены', 'confirmed': 'Клиент подтвердил условия',
                  'completed': COMPLETION_TEXT[output.deal.completion_kind], 'cancelled': 'Оформление отменено'}
        next_steps = {'confirm_deal': 'Ознакомиться с условиями и явно подтвердить их в кабинете',
                      'complete_deal': 'Зафиксировать завершение оформления в кабинете',
                      'cancel_deal': 'Отменить оформление с обязательной причиной в кабинете'}
        add('deal', 'Оформление по сохранённому кредитному решению', {
            **output.deal.model_dump(), 'status_text': labels[output.deal.status],
            'next_steps': [next_steps[action] for action in output.deal.available_actions],
            'note': DEMO_NOTE,
            'terms_note': 'Окончательные согласованные условия оформления имеют приоритет над исходным запросом и расчётом.'})
    for item in output.information_requests:
        if output.status != 'withdrawn' and item.status == 'open' and item.revision_id == revision_id:
            add(f'clarification:{item.id}', 'Открытый запрос уточнений', {
                'message': item.message, 'requested_fields': item.requested_fields,
                'requested_document_types': item.requested_document_types})
    offer_status = {'counteroffer': 'active', 'approved': 'accepted'}.get(output.status)
    offers = [item for item in output.offers if item.status == offer_status and item.revision_id == revision_id]
    if offer_status == 'accepted' and offers:
        # Согласованные условия выбираются одинаково для клиентского чата и сводки.
        offers = [max(offers, key=lambda item: (item.application_version, item.created_at))]
    for item in offers:
        title = 'Согласованные условия: принятое предложение' if item.status == 'accepted' else 'Действующее предложение'
        add(f'offer:{item.id}', title, item.model_dump(exclude={
            'responded_at', 'decline_reason', 'created_at'}))
    return ApplicationContext(application.id, output.version, output.catalog_version, sources, output.product_code, output.status)


def revalidate_access(db: Session, request: Request, user_id: uuid.UUID, role: str,
                      context: ApplicationContext | None = None) -> User:
    # Нельзя использовать request.state: после HTTP сессия могла быть отозвана или изменена.
    db.expire_all()
    session = session_from_request(request, db)
    if session is None or session.user_id != user_id:
        raise HTTPException(401, {'code': 'authentication_required', 'message': 'Войдите в кабинет'})
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(401, {'code': 'authentication_required', 'message': 'Войдите в кабинет'})
    if user.role != role:
        raise HTTPException(403, {'code': 'operation_forbidden', 'message': 'Доступ к ответу изменился'})
    if context:
        application = get_application(db, user, context.application_id)
        if application.version != context.version:
            raise version_conflict()
    return user
