import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Отдельная база для тестов: данные приложения не очищаются.
application_url = make_url(os.environ["DATABASE_URL"])
if application_url.get_backend_name() != "postgresql":
    raise RuntimeError("Auth integration tests require PostgreSQL")
test_database_name = f"test_credit_{uuid.uuid4().hex}"
os.environ["DATABASE_URL"] = application_url.set(database=test_database_name).render_as_string(hide_password=False)

from app.core.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    admin = create_engine(application_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{test_database_name}"'))
    try:
        command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
        yield
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{test_database_name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def db(migrated_database):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE auth_sessions, users, companies CASCADE"))
    with SessionLocal() as session:
        seed(session)
        yield session


@pytest.fixture
def client(db):
    with TestClient(app, raise_server_exceptions=False) as http:
        yield http
