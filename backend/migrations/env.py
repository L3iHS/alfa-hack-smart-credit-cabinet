from alembic import context
from sqlalchemy import create_engine, pool

from app.applications.models import Application, ApplicationEvent  # noqa: F401
from app.applications.submission_models import ApplicationRevision, IdempotencyRecord, ProcessingRun  # noqa: F401
from app.documents.models import Document  # noqa: F401
from app.auth.models import AuthSession, User  # noqa: F401
from app.companies.models import Company  # noqa: F401
from app.core.config import settings
from app.core.db import Base


def run_migrations_offline():
    context.configure(url=settings.database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
