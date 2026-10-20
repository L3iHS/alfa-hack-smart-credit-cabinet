import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import get_current_user
from app.core.db import get_db
from app.processing.schemas import AssessmentOutput, RetryInput, RetryOutput
from app.processing.service import assessment, retry_processing

router = APIRouter(tags=['Рассмотрение'])


@router.get('/applications/{application_id}/assessment', response_model=AssessmentOutput)
def get_assessment(application_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return assessment(db, user, application_id)


@router.post('/applications/{application_id}/processing-retries', response_model=RetryOutput, status_code=202)
def retry(application_id: uuid.UUID, body: RetryInput, idempotency_key: Annotated[uuid.UUID, Header()],
          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return retry_processing(db, user, application_id, body, idempotency_key)
