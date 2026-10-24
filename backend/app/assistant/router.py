from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.applications.service import require_client
from app.assistant.intake import extract_intake
from app.assistant.provider import Provider, get_provider
from app.assistant.schemas import IntakeInput, IntakeOutput
from app.auth.models import User
from app.auth.service import get_current_user
from app.core.db import get_db

router = APIRouter(prefix='/assistant', tags=['Помощник'])


@router.post('/intake', response_model=IntakeOutput)
def intake(body: IntakeInput, user: User = Depends(get_current_user), db: Session = Depends(get_db),
           provider: Provider = Depends(get_provider)):
    require_client(user)
    # CSRF уже проверен. Завершаем читающую транзакцию, освобождая блокировку сессии до HTTP.
    db.rollback()
    return extract_intake(body, provider)
