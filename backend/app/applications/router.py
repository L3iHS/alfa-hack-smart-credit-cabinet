import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.applications.models import Application, ApplicationEvent
from app.applications.schemas import ApplicationOutput, ApplicationPage, DraftCreate, DraftPatch, EventPage
from app.applications.service import application_query, create_draft, get_application, update_draft
from app.auth.models import User
from app.auth.schemas import ErrorOutput
from app.auth.service import get_current_user
from app.core.db import get_db

router = APIRouter(tags=['Заявки'], responses={status: {'model': ErrorOutput} for status in (404, 409)})
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post('/applications', response_model=ApplicationOutput, status_code=201)
def create(body: DraftCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return create_draft(db, user, body)


@router.get('/applications', response_model=ApplicationPage)
def applications(limit: Limit = 20, offset: Offset = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = application_query(user)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Application.created_at, Application.id).limit(limit).offset(offset)).all()
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.get('/applications/{application_id}', response_model=ApplicationOutput)
def application(application_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_application(db, user, application_id)


@router.patch('/applications/{application_id}', response_model=ApplicationOutput)
def update(application_id: uuid.UUID, body: DraftPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return update_draft(db, user, application_id, body)


@router.get('/applications/{application_id}/history', response_model=EventPage)
def history(application_id: uuid.UUID, limit: Limit = 20, offset: Offset = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_application(db, user, application_id)
    query = select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(ApplicationEvent.application_version, ApplicationEvent.id).limit(limit).offset(offset)).all()
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}
