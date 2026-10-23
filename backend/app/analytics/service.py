import hashlib

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.analytics.models import AnalyticsEvent, AnalyticsJourney
from app.analytics.schemas import DraftLinked, EventInput, FormOpened, OfferViewed
from app.applications.service import get_application, require_client
from app.auth.models import User
from app.processing.models import Offer


def conflict(message):
    raise HTTPException(409, {'code': 'analytics_conflict', 'message': message})


def not_found():
    raise HTTPException(404, {'code': 'analytics_subject_not_found', 'message': 'Объект наблюдения не найден'})


def lock(db, value):
    key = int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], signed=True)
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})


def record_event(db: Session, user: User, body: EventInput):
    require_client(user)
    # Независимые сессии одного клиента получают один результат повтора.
    lock(db, f'analytics-event:{user.id}:{body.event_id}')
    payload = body.model_dump(mode='json', exclude={'event_id'})
    previous = db.get(AnalyticsEvent, (user.id, body.event_id))
    if previous:
        if previous.payload != payload:
            conflict('Идентификатор события уже использован с другими данными')
        return {'event_id': body.event_id, 'recorded': True}

    journey_id = offer_id = offer_version = None
    if isinstance(body, OfferViewed):
        offer = db.get(Offer, body.offer_id)
        if offer is None:
            not_found()
        # Порядок блокировок совпадает с командой ответа: заявка, затем предложение.
        get_application(db, user, offer.application_id, lock=True)
        offer = db.scalar(select(Offer).where(Offer.id == body.offer_id).with_for_update()
                          .execution_options(populate_existing=True))
        visible_version = offer.version if offer.status == 'active' else offer.version - 1
        if offer.status not in ('active', 'accepted', 'declined') or body.offer_version != visible_version:
            conflict('Предложение изменилось, обновите заявку')
        offer_id, offer_version = offer.id, body.offer_version
    else:
        # Блокировка идентификатора защищает также создание ещё отсутствующей строки.
        lock(db, f'analytics-journey:{body.journey_id}')
        journey = db.scalar(select(AnalyticsJourney).where(AnalyticsJourney.id == body.journey_id).with_for_update())
        if journey is not None and journey.user_id != user.id:
            not_found()
        if isinstance(body, FormOpened):
            if journey is None:
                journey = AnalyticsJourney(id=body.journey_id, user_id=user.id, product_code=body.product_code)
                db.add(journey)
                db.flush()
            elif journey.product_code != body.product_code:
                conflict('Начальный продукт попытки уже сохранён')
        elif journey is None:
            not_found()
        if isinstance(body, DraftLinked):
            application = get_application(db, user, body.application_id, lock=True)
            if application.author_id != user.id or application.created_at < journey.created_at:
                conflict('Попытку можно связать только с созданной в ней заявкой')
            if journey.application_id not in (None, application.id):
                conflict('Попытка уже связана с другой заявкой')
            linked = db.scalar(select(AnalyticsJourney.id).where(AnalyticsJourney.application_id == application.id))
            if linked is not None and linked != journey.id:
                conflict('Заявка уже связана с другой попыткой')
            journey.application_id = application.id
        journey_id = journey.id

    db.add(AnalyticsEvent(user_id=user.id, event_id=body.event_id, kind=body.kind, payload=payload,
                          journey_id=journey_id, offer_id=offer_id, offer_version=offer_version))
    db.commit()
    return {'event_id': body.event_id, 'recorded': True}
