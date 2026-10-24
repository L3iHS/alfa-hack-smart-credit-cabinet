import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.applications.service import application_output, get_application
from app.assistant.schemas import Source
from app.auth.models import User
from app.auth.service import session_from_request
from app.processing.service import latest_revision


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
    r'оборудован|овердрафт|оборотн|сырь|закуп|гарант|тендер|инвестици)', re.IGNORECASE,
)


def application_sources_for_question(context: ApplicationContext, question: str) -> list[Source]:
    # Это выбор известного предмета, а не обещание общего понимания произвольного текста.
    return context.sources if _APPLICATION_SUBJECT.search(question) else []


def version_conflict():
    return HTTPException(409, {'code': 'version_conflict', 'message': 'Заявка изменилась, обновите страницу'})


def _date_text(value):
    if isinstance(value, datetime):
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
    add('request', 'Данные заявки', {field: getattr(output, field) for field in fields})
    add('state', 'Состояние и доступные действия', {'status': output.status,
        'public_reasons': output.public_reasons, 'available_actions': output.available_actions,
        'processing_status': output.processing_status})
    for item in output.information_requests:
        if item.status == 'open' and item.revision_id == revision_id:
            add(f'clarification:{item.id}', 'Открытый запрос уточнений', {
                'message': item.message, 'requested_fields': item.requested_fields,
                'requested_document_types': item.requested_document_types})
    for item in output.offers:
        if output.status == 'counteroffer' and item.status == 'active' and item.revision_id == revision_id:
            add(f'offer:{item.id}', 'Действующее предложение', item.model_dump(exclude={
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
