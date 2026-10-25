import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.applications.service import require_client
from app.assistant.chat import answer_chat
from app.assistant.intake import extract_intake
from app.assistant.provider import Provider, get_provider
from app.assistant.schemas import AnswerOutput, ChatInput, IntakeInput, IntakeOutput, SummaryInput, SummaryOutput
from app.assistant.summary import saved_application_summary, summarize_application
from app.auth.models import User
from app.auth.service import get_current_user
from app.core.db import get_db

router = APIRouter(tags=['Помощник'])


@router.post('/assistant/intake', response_model=IntakeOutput)
def intake(body: IntakeInput, user: User = Depends(get_current_user), db: Session = Depends(get_db),
           provider: Provider = Depends(get_provider)):
    require_client(user)
    # CSRF уже проверен. Завершаем читающую транзакцию, освобождая блокировку сессии до HTTP.
    db.rollback()
    return extract_intake(body, provider)


@router.post('/assistant/chat', response_model=AnswerOutput)
def chat(body: ChatInput, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db),
         provider: Provider = Depends(get_provider)):
    return answer_chat(body, request, db, user, provider)


@router.post('/applications/{application_id}/summary', response_model=SummaryOutput)
def summary(application_id: uuid.UUID, body: SummaryInput, request: Request,
            user: User = Depends(get_current_user), db: Session = Depends(get_db),
            provider: Provider = Depends(get_provider)):
    return summarize_application(application_id, body, request, db, user, provider)


@router.get('/applications/{application_id}/summary', response_model=SummaryOutput | None)
def saved_summary(application_id: uuid.UUID, request: Request,
                  expected_version: int = Query(ge=1, le=2_147_483_647),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  provider: Provider = Depends(get_provider)):
    return saved_application_summary(application_id, expected_version, request, db, user, provider)
