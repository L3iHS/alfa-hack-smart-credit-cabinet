import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.applications.schemas import ApplicationOutput
from app.auth.models import User
from app.auth.service import get_current_user
from app.core.db import get_db
from app.deals import service
from app.deals.schemas import CancelDealInput, ConfirmDealInput, DealCommandInput

router = APIRouter(prefix='/applications/{application_id}/deal', tags=['Оформление сделки'])
IdempotencyKey = Annotated[uuid.UUID, Header(alias='Idempotency-Key')]


@router.post('/prepare', response_model=ApplicationOutput)
def prepare(application_id: uuid.UUID, body: DealCommandInput, idempotency_key: IdempotencyKey,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.execute(db, user, application_id, body, idempotency_key, 'prepare')


@router.post('/confirm', response_model=ApplicationOutput)
def confirm(application_id: uuid.UUID, body: ConfirmDealInput, idempotency_key: IdempotencyKey,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.execute(db, user, application_id, body, idempotency_key, 'confirm')


@router.post('/complete', response_model=ApplicationOutput)
def complete(application_id: uuid.UUID, body: DealCommandInput, idempotency_key: IdempotencyKey,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.execute(db, user, application_id, body, idempotency_key, 'complete')


@router.post('/cancel', response_model=ApplicationOutput)
def cancel(application_id: uuid.UUID, body: CancelDealInput, idempotency_key: IdempotencyKey,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.execute(db, user, application_id, body, idempotency_key, 'cancel')


@router.get('/document')
def document(application_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    content, filename = service.document(db, user, application_id)
    return Response(content, media_type='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})
