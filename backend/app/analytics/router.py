from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics import reports
from app.analytics.schemas import (AnalyticsSummary, CounterofferPage, EventInput, EventOutput,
                                   OfferOutcome, ReportMetadata)
from app.analytics.service import record_event
from app.auth.models import User
from app.auth.service import get_current_user
from app.core.db import get_db
from app.processing.service import require_staff
from app.products.schemas import ProductCode

router = APIRouter(prefix='/analytics', tags=['Аналитика'])


@router.post('/events', response_model=EventOutput)
def events(body: EventInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return record_event(db, user, body)


def report_now() -> datetime:
    return datetime.now(timezone.utc)


def report_metadata(date_from: date | None = None, date_to: date | None = None,
                    product_code: ProductCode | None = None, user: User = Depends(get_current_user)) -> ReportMetadata:
    require_staff(user)
    return reports.metadata(date_from, date_to, product_code, report_now())


@router.get('/summary', response_model=AnalyticsSummary)
def summary(meta: ReportMetadata = Depends(report_metadata), db: Session = Depends(get_db)):
    return reports.summary(db, meta)


@router.get('/counteroffers', response_model=CounterofferPage)
def counteroffers(meta: ReportMetadata = Depends(report_metadata), outcome: OfferOutcome | None = None,
                  page: int = Query(default=1, ge=1, le=2_147_483_647), page_size: int = Query(default=20, ge=1, le=100),
                  db: Session = Depends(get_db)):
    return reports.counteroffers(db, meta, outcome, page, page_size)
