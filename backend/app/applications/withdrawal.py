import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.applications.service import add_event, get_application, require_client
from app.applications.submission_models import ProcessingRun
from app.auth.models import User
from app.processing.models import Offer
from app.processing.schemas import WITHDRAWABLE_STATUSES
from app.processing.service import latest_revision


class WithdrawalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]


def withdraw_application(db: Session, user: User, application_id: uuid.UUID, body: WithdrawalInput) -> Application:
    require_client(user)
    # Единый порядок application → run → offer совпадает с worker и командами решения.
    application = get_application(db, user, application_id, lock=True)
    if application.version != body.expected_version or application.status not in WITHDRAWABLE_STATUSES:
        raise HTTPException(409, {'code': 'version_conflict', 'message': 'Заявка изменилась, обновите страницу'})
    revision = latest_revision(db, application.id)
    run = db.scalar(select(ProcessingRun).where(ProcessingRun.revision_id == revision.id)
                    .with_for_update().execution_options(populate_existing=True)) if revision else None
    withdrawn_at = datetime.now(timezone.utc)
    if run and run.status in ('pending', 'running'):
        # Поздний результат/сбой worker отсекается существующей проверкой состояния run.
        run.status = 'interrupted'
        run.error_code = 'application_withdrawn'
        run.finished_at = withdrawn_at
    for offer in db.scalars(select(Offer).where(Offer.application_id == application.id, Offer.status == 'active')
                            .with_for_update().execution_options(populate_existing=True)):
        offer.status = 'superseded'
        offer.version += 1
    application.status = 'withdrawn'
    application.version += 1
    application.updated_at = withdrawn_at
    add_event(db, application, user, 'application_withdrawn',
              revision_id=revision.id if revision else None, processing_run_id=run.id if run else None)
    db.commit()
    return application
