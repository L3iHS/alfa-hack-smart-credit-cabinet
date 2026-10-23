from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.schemas import EventInput, EventOutput
from app.analytics.service import record_event
from app.auth.models import User
from app.auth.service import get_current_user
from app.core.db import get_db

router = APIRouter(prefix='/analytics', tags=['Аналитика'])


@router.post('/events', response_model=EventOutput)
def events(body: EventInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return record_event(db, user, body)
