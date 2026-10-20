import calendar
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.models import Application, ApplicationEvent
from app.applications.schemas import DraftCreate, DraftFields, DraftPatch
from app.auth.models import User
from app.products.catalog import CATALOG_VERSION, PRODUCTS


def require_client(user: User) -> None:
    if user.role != 'client' or user.company_id is None:
        raise HTTPException(403, {'code': 'operation_forbidden', 'message': 'Черновик создаёт и редактирует клиент'})


def application_query(user: User):
    query = select(Application)
    if user.role == 'client':
        return query.where(Application.company_id == user.company_id)
    # До реализации отправки очередь сотрудника пуста.
    return query.where(Application.status != 'draft')


def get_application(db: Session, user: User, application_id: uuid.UUID, *, lock=False) -> Application:
    query = application_query(user).where(Application.id == application_id)
    if lock:
        query = query.with_for_update()
    application = db.scalar(query)
    if application is None:
        raise HTTPException(404, {'code': 'application_not_found', 'message': 'Заявка не найдена'})
    return application


def validate_draft(values: dict) -> None:
    product = PRODUCTS[values['product_code']]
    errors = {}
    amount = values['amount_kopecks']
    term = values['term_months']
    if amount is not None and not product.min_amount_kopecks <= amount <= product.max_amount_kopecks:
        errors['amount_kopecks'] = 'Сумма вне диапазона выбранного продукта'
    if term is not None and not product.min_term_months <= term <= product.max_term_months:
        errors['term_months'] = 'Срок вне диапазона выбранного продукта'
    start, end = values['period_start'], values['period_end']
    if start and start.day != 1:
        errors['period_start'] = 'Укажите первый день месяца'
    if end:
        if end.day != calendar.monthrange(end.year, end.month)[1]:
            errors['period_end'] = 'Укажите последний день месяца'
        if end >= datetime.now(timezone.utc).date().replace(day=1):
            errors['period_end'] = 'Период должен состоять из завершённых месяцев'
    if start and end and start > end:
        errors['period_end'] = 'Конец периода раньше начала'
    if errors:
        raise HTTPException(422, {'code': 'validation_error', 'message': 'Проверьте введённые данные', 'field_errors': errors})


def add_event(db: Session, application: Application, user: User, event_type: str) -> None:
    db.add(ApplicationEvent(application_id=application.id, actor_id=user.id, event_type=event_type, application_version=application.version))


def create_draft(db: Session, user: User, body: DraftCreate) -> Application:
    require_client(user)
    values = body.model_dump()
    validate_draft(values)
    application = Application(company_id=user.company_id, author_id=user.id, catalog_version=CATALOG_VERSION, **values)
    db.add(application)
    db.flush()
    add_event(db, application, user, 'draft_created')
    db.commit()
    return application


def update_draft(db: Session, user: User, application_id: uuid.UUID, body: DraftPatch) -> Application:
    require_client(user)
    # Строка заявки блокируется независимо от авторизационной сессии.
    application = get_application(db, user, application_id, lock=True)
    if application.status != 'draft' or application.version != body.expected_version:
        raise HTTPException(409, {'code': 'version_conflict', 'message': 'Заявка изменилась, обновите страницу'})
    changes = body.model_dump(exclude_unset=True, exclude={'expected_version'})
    values = {name: getattr(application, name) for name in DraftFields.model_fields}
    values.update(changes)
    validate_draft(values)
    if any(getattr(application, name) != value for name, value in changes.items()):
        for name, value in changes.items():
            setattr(application, name, value)
        application.version += 1
        application.updated_at = datetime.now(timezone.utc)
        add_event(db, application, user, 'draft_updated')
    db.commit()
    return application
