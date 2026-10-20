from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.auth.models import AuthSession, User
from app.companies.models import Company
from app.core.config import settings
from app.core.db import get_db
from app.main import app
from app.seed import seed

CLIENT_EMAIL = "client1@example.test"
PASSWORD = settings.demo_password


def csrf(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def login(client, email=CLIENT_EMAIL):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD},
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 200
    return response


def test_login_rotates_session_and_csrf(client):
    old_csrf = csrf(client)
    old_cookie = client.cookies.get("credit_session")
    response = client.post(
        "/api/v1/auth/login", json={"email": CLIENT_EMAIL, "password": PASSWORD},
        headers={"X-CSRF-Token": old_csrf},
    )
    assert response.status_code == 200
    new_csrf = response.json()["csrf_token"]
    assert new_csrf != old_csrf
    assert client.cookies.get("credit_session") != old_cookie
    assert response.json()["user"]["role"] == "client"
    assert client.get("/api/v1/me").status_code == 200
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": old_csrf}).status_code == 403
    with TestClient(app) as stale:
        stale.cookies.set("credit_session", old_cookie)
        assert stale.get("/api/v1/me").status_code == 401
        assert stale.post("/api/v1/auth/login", json={"email": CLIENT_EMAIL, "password": PASSWORD}, headers={"X-CSRF-Token": old_csrf}).status_code == 403
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie


@pytest.mark.parametrize("email,password", [(CLIENT_EMAIL, "wrong"), ("unknown@example.test", PASSWORD)])
def test_invalid_login_is_401(client, email, password):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password},
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert "message" in response.json()
    assert "password" not in response.text
    assert client.get("/api/v1/me").status_code == 401


def test_logout_revokes_session(client):
    response = login(client)
    assert response.status_code == 200
    cookie = client.cookies.get("credit_session")
    token = response.json()["csrf_token"]
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})
    assert response.status_code == 204 and response.content == b""
    assert client.get("/api/v1/me").status_code == 401
    client.cookies.set("credit_session", cookie)
    assert client.get("/api/v1/me").status_code == 401
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token}).status_code == 403


def test_missing_csrf_is_403(client):
    csrf(client)
    response = client.post("/api/v1/auth/login", json={"email": CLIENT_EMAIL, "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    response = login(client)
    assert response.status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.get("/api/v1/me").status_code == 200


@pytest.mark.parametrize("extra", [{"role": "staff"}, {"company_id": "e53d6d28-023b-4fa5-bfd2-f221287aeb18"}])
def test_login_cannot_set_role_or_company(client, extra):
    response = client.post(
        "/api/v1/auth/login", json={"email": CLIENT_EMAIL, "password": PASSWORD, **extra},
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 422
    assert set(extra) <= response.json()["field_errors"].keys()
    assert PASSWORD not in response.text
    assert client.get("/api/v1/me").status_code == 401


def test_db_failure_does_not_authenticate(client):
    token = csrf(client)
    # Реальный отказ драйвера на неиспользуемом порту, без подмены авторизации.
    unavailable = create_engine("postgresql+psycopg://unused:unused@127.0.0.1:1/unused?connect_timeout=1")

    def failed_db():
        with Session(unavailable) as session:
            yield session

    app.dependency_overrides[get_db] = failed_db
    try:
        response = client.post("/api/v1/auth/login", json={"email": CLIENT_EMAIL, "password": PASSWORD}, headers={"X-CSRF-Token": token})
        assert response.status_code == 503
        assert response.json() == {"code": "database_unavailable", "message": "Сервис временно недоступен"}
        assert "set-cookie" not in response.headers
        assert client.get("/api/v1/me").status_code == 503
    finally:
        app.dependency_overrides.clear()
        unavailable.dispose()
    assert client.get("/api/v1/me").status_code == 401


def test_seed_is_idempotent(db):
    assert db.scalar(select(func.count()).select_from(User)) == 8
    assert db.scalar(select(func.count()).select_from(Company)) == 7
    user = db.scalar(select(User).where(User.email == CLIENT_EMAIL))
    user.display_name = "Сохранённое имя"
    original_password_hash = user.password_hash
    db.add(User(email="existing@example.test", display_name="Existing staff", password_hash="existing-hash", role="staff", company_id=None))
    db.commit()
    seed(db)
    seed(db)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(User)) == 9
    assert db.scalar(select(func.count()).select_from(Company)) == 7
    user = db.scalar(select(User).where(User.email == CLIENT_EMAIL))
    assert user.display_name == "Сохранённое имя"
    assert user.password_hash == original_password_hash
    assert user.password_hash != PASSWORD
    assert db.scalar(select(User).where(User.email == "existing@example.test")).password_hash == "existing-hash"


def test_identity_roles_and_company_isolation(client):
    first = login(client).json()["user"]
    second = login(client, "client2@example.test").json()["user"]
    staff = login(client, "staff@example.test").json()["user"]
    assert first["company_id"] and second["company_id"]
    assert first["company_id"] != second["company_id"]
    assert staff["role"] == "staff" and staff["company_id"] is None
    assert set(staff) == {"id", "role", "company_id", "display_name"}
    assert client.get("/api/v1/me").json() == staff


def test_expired_or_forged_session_is_unauthorized(client, db):
    response = login(client)
    assert response.status_code == 200
    session = db.scalar(select(AuthSession).where(AuthSession.user_id.is_not(None)))
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/me").status_code == 401
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": response.json()["csrf_token"]}).status_code == 403
    client.cookies.clear()
    client.cookies.set("credit_session", "forged")
    assert client.get("/api/v1/me").status_code == 401
    assert csrf(client)


def test_https_cookie_flag_and_anonymous_csrf_reuse(client, monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", True)
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()
    monkeypatch.setattr(settings, "cookie_secure", False)
    client.cookies.clear()
    token = csrf(client)
    assert csrf(client) == token


def test_validation_errors_have_safe_field_errors(client):
    response = client.post("/api/v1/auth/login", json={"email": "", "password": PASSWORD}, headers={"X-CSRF-Token": csrf(client)})
    assert response.status_code == 422
    assert "email" in response.json()["field_errors"]
    assert PASSWORD not in response.text


def test_openapi_describes_actual_error_contract(client):
    schema = client.get("/api/v1/openapi.json").json()
    response = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]["422"]
    error_schema = response["content"]["application/json"]["schema"]
    if "$ref" in error_schema:
        error_schema = schema["components"]["schemas"][error_schema["$ref"].split("/")[-1]]
    assert {"code", "message", "field_errors"} <= error_schema["properties"].keys()


def test_csrf_binding_matches_the_current_session(client):
    anonymous = client.get("/api/v1/auth/csrf").json()
    assert anonymous["user_id"] is None
    first = login(client).json()
    first_binding = client.get("/api/v1/auth/csrf").json()
    assert first_binding == {"csrf_token": first["csrf_token"], "user_id": first["user"]["id"]}
    second = login(client, "client2@example.test").json()
    second_binding = client.get("/api/v1/auth/csrf").json()
    assert second_binding == {"csrf_token": second["csrf_token"], "user_id": second["user"]["id"]}
    assert first_binding["user_id"] != second_binding["user_id"]
