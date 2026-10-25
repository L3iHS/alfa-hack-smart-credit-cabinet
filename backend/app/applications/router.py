import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.applications.models import Application, ApplicationEvent
from app.applications.schemas import ApplicationOutput, ApplicationPage, DraftCreate, DraftPatch, EventPage, SubmissionInput, SubmissionOutput
from app.applications.service import application_output, application_query, create_draft, get_application, update_draft
from app.applications.submission import submit_application
from app.applications.submission_policy import submission_policy
from app.applications.withdrawal import WithdrawalInput, withdraw_application
from app.auth.models import User
from app.auth.schemas import ErrorOutput
from app.auth.service import get_current_user
from app.core.db import get_db
from app.processing.schemas import ApplicationStatus

router = APIRouter(tags=['Заявки'], responses={status: {'model': ErrorOutput} for status in (404, 409)})
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post('/applications', response_model=ApplicationOutput, status_code=201)
def create(body: DraftCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return application_output(create_draft(db, user, body), user)


@router.get('/applications', response_model=ApplicationPage)
def applications(limit: Limit = 20, offset: Offset = 0, status: ApplicationStatus | None = None,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = application_query(user)
    if status:
        query = query.where(Application.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Application.created_at, Application.id).limit(limit).offset(offset)).all()
    return {'items': [application_output(item, user) for item in items], 'total': total, 'limit': limit, 'offset': offset}


@router.get('/applications/{application_id}', response_model=ApplicationOutput)
def application(application_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return application_output(get_application(db, user, application_id), user)


@router.patch('/applications/{application_id}', response_model=ApplicationOutput)
def update(application_id: uuid.UUID, body: DraftPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return application_output(update_draft(db, user, application_id, body), user)


@router.post('/applications/{application_id}/withdraw', response_model=ApplicationOutput)
def withdraw(application_id: uuid.UUID, body: WithdrawalInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return application_output(withdraw_application(db, user, application_id, body), user)


@router.get('/applications/{application_id}/history', response_model=EventPage)
def history(application_id: uuid.UUID, limit: Limit = 20, offset: Offset = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_application(db, user, application_id)
    query = select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(ApplicationEvent.application_version, ApplicationEvent.id).limit(limit).offset(offset)).all()
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.get('/submission-policy')
def policy(user: User = Depends(get_current_user)):
    return submission_policy()


@router.post('/applications/{application_id}/submit', response_model=SubmissionOutput, status_code=202)
def submit(application_id: uuid.UUID, body: SubmissionInput, idempotency_key: Annotated[uuid.UUID, Header()],
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return submit_application(db, user, application_id, body, idempotency_key)
