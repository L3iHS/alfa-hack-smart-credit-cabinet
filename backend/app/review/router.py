import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.applications.schemas import SubmissionOutput
from app.auth.models import User
from app.auth.service import get_current_user
from app.core.db import get_db
from app.review import service
from app.review.schemas import (CreateOfferInput, DecisionCommandOutput, DecisionInput, InformationRequestCommandOutput,
                                InformationRequestInput, InformationResponseInput, OfferActionInput, DeclineOfferInput, OfferCommandOutput)

router = APIRouter(tags=['Диалог и решения'])
IdempotencyKey = Annotated[uuid.UUID, Header(alias='Idempotency-Key')]


@router.post('/applications/{application_id}/information-requests', response_model=InformationRequestCommandOutput, status_code=201)
def request_information(application_id: uuid.UUID, body: InformationRequestInput, idempotency_key: IdempotencyKey,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.request_information(db, user, application_id, body, idempotency_key)


@router.post('/applications/{application_id}/information-responses', response_model=SubmissionOutput, status_code=202)
def respond_information(application_id: uuid.UUID, body: InformationResponseInput, idempotency_key: IdempotencyKey,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.respond_information(db, user, application_id, body, idempotency_key)


@router.post('/applications/{application_id}/offers', response_model=OfferCommandOutput, status_code=201)
def create_offer(application_id: uuid.UUID, body: CreateOfferInput, idempotency_key: IdempotencyKey,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.create_offer(db, user, application_id, body, idempotency_key)


@router.post('/applications/{application_id}/decisions', response_model=DecisionCommandOutput, status_code=201)
def decide(application_id: uuid.UUID, body: DecisionInput, idempotency_key: IdempotencyKey,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.decide(db, user, application_id, body, idempotency_key)


@router.post('/offers/{offer_id}/accept', response_model=OfferCommandOutput)
def accept_offer(offer_id: uuid.UUID, body: OfferActionInput, idempotency_key: IdempotencyKey,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.offer_action(db, user, offer_id, body, idempotency_key, True)


@router.post('/offers/{offer_id}/decline', response_model=OfferCommandOutput)
def decline_offer(offer_id: uuid.UUID, body: DeclineOfferInput, idempotency_key: IdempotencyKey,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.offer_action(db, user, offer_id, body, idempotency_key, False)
