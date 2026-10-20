from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.auth.models import AuthSession, User
from app.auth.schemas import CsrfOutput, LoginInput, LoginOutput, UserOutput
from app.auth.service import (
    authenticate, create_session, get_current_user, session_from_request, set_session_cookie,
)
from app.core.config import settings
from app.core.db import get_db

router = APIRouter()


@router.get("/auth/csrf", response_model=CsrfOutput, tags=["Доступ"])
def csrf(request: Request, response: Response, db: Session = Depends(get_db)):
    session = session_from_request(request, db)
    if session is None:
        db.execute(delete(AuthSession).where(AuthSession.expires_at <= datetime.now(timezone.utc)))
        session, token = create_session(db)
        db.commit()
        set_session_cookie(response, token)
    return CsrfOutput(csrf_token=session.csrf_token, user_id=session.user_id)


@router.post("/auth/login", response_model=LoginOutput, tags=["Доступ"])
def login(body: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    user = authenticate(db, body.email, body.password)
    db.delete(request.state.auth_session)
    session, token = create_session(db, user)
    # Cookie меняется только после успешного сохранения сессии.
    db.commit()
    set_session_cookie(response, token)
    return LoginOutput(user=UserOutput.model_validate(user), csrf_token=session.csrf_token)


@router.post("/auth/logout", status_code=204, tags=["Доступ"])
def logout(request: Request, db: Session = Depends(get_db)):
    db.delete(request.state.auth_session)
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        settings.session_cookie_name, path="/", httponly=True,
        secure=settings.cookie_secure, samesite="lax",
    )
    return response


@router.get("/me", response_model=UserOutput, tags=["Доступ"])
def me(user: User = Depends(get_current_user)):
    return user
