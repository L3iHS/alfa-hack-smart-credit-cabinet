import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AuthSession, User
from app.core.config import settings
from app.core.db import get_db

password_hash = PasswordHash.recommended()
# Проверка неизвестного пользователя требует ту же работу с хешем, что и известного.
_dummy_password_hash = password_hash.hash(secrets.token_urlsafe(32))


def session_from_request(request: Request, db: Session) -> AuthSession | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    query = select(AuthSession).where(
        AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        AuthSession.expires_at > datetime.now(timezone.utc),
    )
    # Блокировка не позволяет двум запросам повторно использовать отозванную сессию.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        query = query.with_for_update()
    return db.scalar(query)


def require_csrf(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    session = session_from_request(request, db)
    if session is None or csrf_token is None or not secrets.compare_digest(
        session.csrf_token.encode(), csrf_token.encode(),
    ):
        raise HTTPException(403, {"code": "csrf_failed", "message": "Обновите сессию и повторите запрос"})
    request.state.auth_session = session


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    session = getattr(request.state, "auth_session", None) or session_from_request(request, db)
    user = db.get(User, session.user_id) if session and session.user_id else None
    if user is None:
        raise HTTPException(401, {"code": "authentication_required", "message": "Войдите в кабинет"})
    return user


def create_session(db: Session, user: User | None = None) -> tuple[AuthSession, str]:
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        csrf_token=secrets.token_urlsafe(32),
        user_id=user.id if user else None,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds),
    )
    db.add(session)
    return session, token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name, token,
        httponly=True, secure=settings.cookie_secure, samesite="lax", path="/",
        max_age=settings.session_ttl_seconds,
    )


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    valid = password_hash.verify(password, user.password_hash if user else _dummy_password_hash)
    if user is None or not valid:
        raise HTTPException(401, {"code": "invalid_credentials", "message": "Неверный email или пароль"})
    return user
