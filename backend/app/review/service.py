import hashlib
import json
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.applications.models import Application, ApplicationEvent
from app.applications.schemas import DraftFields
from app.applications.service import get_application, require_client, validate_draft
from app.applications.submission import create_submission
from app.applications.submission_models import IdempotencyRecord, ProcessingRun
from app.auth.models import User
from app.core.config import settings
from app.demo.profiles import SOURCE_VERSION
from app.documents.models import Document
from app.documents.service import active_documents
from app.processing.models import CheckResult, Decision, InformationRequest, Offer
from app.processing.policy import evaluate, offer_terms, period_months, policy_profile, requires_model
from app.risk.assessments import assess, exact_assessment, record_override, terms_for
from app.risk.models import RiskOverride
from app.processing.schemas import InformationRequestOutput, OfferOutput
from app.processing.service import latest_revision, require_staff
from app.products.catalog import get_product
from app.products.financial import financial_gate


def conflict(message='Заявка изменилась, обновите страницу'):
    raise HTTPException(409, {'code': 'review_conflict', 'message': message})


def now():
    return datetime.now(timezone.utc)


def open_request(db: Session, application: Application) -> InformationRequest:
    revision = latest_revision(db, application.id)
    request = db.scalar(select(InformationRequest).where(InformationRequest.application_id == application.id,
                        InformationRequest.status == 'open').order_by(InformationRequest.created_at.desc()).limit(1))
    if not revision or not request or request.revision_id != revision.id:
        conflict('Актуальный запрос уточнений не найден')
    return request


def event(db, application, user, revision, event_type, status):
    application.status = status
    application.version += 1
    application.updated_at = now()
    db.add(ApplicationEvent(application_id=application.id, application_version=application.version,
                            actor_id=user.id, actor_type='user', revision_id=revision.id, event_type=event_type))


def output(application, revision, **extra):
    return dict(application_id=str(application.id), version=application.version, status=application.status,
                revision_id=str(revision.id), **extra)


def execute(db, user, application_id, body, key, operation, action, *, resource_id=None):
    # Принадлежность проверяется до повтора: ключ не раскрывает чужую заявку.
    get_application(db, user, application_id)
    values = body.model_dump(mode='json')
    # Отсутствующая причина и явный null сохраняют отпечаток исторической команды.
    if operation == 'decline_offer' and values.get('decline_reason') is None:
        values.pop('decline_reason', None)
    fingerprint = hashlib.sha256(json.dumps({'application_id': str(application_id), 'resource_id': str(resource_id) if resource_id else None, **values},
                                           sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    lock_key = int.from_bytes(hashlib.sha256(f'{user.id}:{operation}:{key}'.encode()).digest()[:8], signed=True)
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
    previous = db.get(IdempotencyRecord, (user.id, operation, key))
    if previous:
        if previous.fingerprint != fingerprint:
            raise HTTPException(409, {'code': 'idempotency_conflict', 'message': 'Ключ уже использован с другими данными'})
        return previous.response
    application = get_application(db, user, application_id, lock=True)
    if application.version != body.expected_version:
        conflict()
    revision = latest_revision(db, application.id)
    if revision is None:
        conflict('Отправленная версия заявки не найдена')
    result = action(application, revision)
    db.add(IdempotencyRecord(user_id=user.id, operation=operation, key=key, fingerprint=fingerprint, response=result))
    db.commit()
    return result


def supersede_offers(db, application):
    for offer in db.scalars(select(Offer).where(Offer.application_id == application.id, Offer.status == 'active').with_for_update()):
        offer.status = 'superseded'
        offer.version += 1


def request_information(db, user, application_id, body, key):
    require_staff(user)
    def action(application, revision):
        if application.status != 'manual_review':
            conflict('Запрос уточнений сейчас недоступен')
        run = db.scalar(select(ProcessingRun).where(ProcessingRun.revision_id == revision.id))
        if run is None:
            conflict('Рассмотрение отправленной версии не найдено')
        try:
            product = get_product(revision.snapshot['application']['product_code'], run.catalog_version)
        except (KeyError, ValueError):
            conflict('Условия отправленной версии не поддерживаются')
        specific_fields = ('tender_number', 'beneficiary_name', 'project_description')
        if any(name in specific_fields and name not in product.required_application_fields
               for name in body.requested_fields):
            raise HTTPException(422, {'code': 'validation_error', 'message': 'Нельзя запросить поле другого продукта',
                                      'field_errors': {'requested_fields': 'Выберите общие поля или поля выбранного продукта'}})
        supersede_offers(db, application)
        event(db, application, user, revision, 'information_requested', 'needs_info')
        request = InformationRequest(id=uuid.uuid4(), application_id=application.id, revision_id=revision.id,
                                     actor_id=user.id, application_version=application.version, status='open',
                                     message=body.message, requested_fields=body.requested_fields,
                                     requested_document_types=body.requested_document_types)
        db.add(request)
        db.flush()
        return output(application, revision, information_request=InformationRequestOutput.model_validate(request).model_dump(mode='json'))
    return execute(db, user, application_id, body, key, 'request_information', action)


def respond_information(db, user, application_id, body, key):
    require_client(user)
    def action(application, revision):
        if application.status != 'needs_info':
            conflict('Ответ на запрос сейчас недоступен')
        request = open_request(db, application)
        if request.id != body.request_id:
            conflict('Запрос уточнений уже изменился')
        errors = {}
        for name in request.requested_fields:
            value = getattr(application, name)
            if value is None or isinstance(value, str) and not value.strip():
                errors[name] = 'Заполните запрошенное поле'
        # Старый файл остаётся в снимке, но не считается новым ответом на запрос документа.
        old_ids = {item['id'] for item in revision.snapshot['documents']}
        new_types = {item.document_type for item in active_documents(db, application.id)
                     if str(item.id) not in old_ids and item.created_at >= request.created_at}
        if not set(request.requested_document_types) <= new_types:
            errors['documents'] = 'Прикрепите новые запрошенные документы'
        if errors:
            raise HTTPException(422, {'code': 'validation_error', 'message': 'Дополните ответ на запрос', 'field_errors': errors})
        supersede_offers(db, application)
        result, new_revision = create_submission(db, user, application, body, 'information_responded')
        request.status = 'answered'
        request.response_revision_id = new_revision.id
        request.response_message = body.message
        request.responded_by = user.id
        request.responded_at = now()
        return result
    return execute(db, user, application_id, body, key, 'respond_information', action)


def safe_terms(db, application, revision, amount=None, term=None):
    """Проверяет ограничения, которые сотрудник и клиент предложения не обходят."""
    run = db.scalar(select(ProcessingRun).where(ProcessingRun.revision_id == revision.id))
    if run is None or run.status != 'succeeded' or run.source_version != SOURCE_VERSION:
        conflict('Не завершены обязательные проверки актуальной версии')
    try:
        policy_profile(run.policy_version, run.catalog_version)
        product = get_product(revision.snapshot['application']['product_code'], run.catalog_version)
    except (ValueError, KeyError):
        conflict('Не завершены обязательные проверки актуальной версии')
    checks = {item.kind: item for item in db.scalars(select(CheckResult).where(CheckResult.run_id == run.id))}
    if set(checks) != {'registry', 'tax', 'bki'} or any(item.status != 'succeeded' or item.revision_id != revision.id or item.source_version != run.source_version for item in checks.values()):
        conflict('Не завершены обязательные проверки актуальной версии')
    snapshot = revision.snapshot
    try:
        values = DraftFields.model_validate(snapshot['application']).model_dump()
    except (ValidationError, KeyError):
        conflict('Отправленные сведения неполны')
    required = ('purpose', 'amount_kopecks', 'term_months', 'period_start', 'period_end',
                'revenue_kopecks', 'operating_expenses_kopecks', 'existing_debt_payments_kopecks',
                *product.required_application_fields)
    if any(values[name] is None or isinstance(values[name], str) and not values[name].strip() for name in required):
        conflict('Отправленные сведения неполны')
    if snapshot.get('catalog_version', run.catalog_version) != run.catalog_version:
        conflict('Версия отправленных условий не совпадает с рассмотрением')
    validate_draft(values, run.catalog_version)
    confirmations = snapshot.get('confirmations', {})
    if confirmations.get('data_confirmed') is not True or confirmations.get('bki_consent') is not True:
        conflict('Нет подтверждения отправленных сведений')
    documents = snapshot.get('documents', [])
    if not set(product.required_document_types) <= {item['document_type'] for item in documents}:
        conflict('Не хватает обязательных документов')
    for item in documents:
        document = db.get(Document, uuid.UUID(item['id']))
        if (document is None or document.application_id != application.id or document.deleted_at is not None
                or document.sha256 != item['sha256'] or document.size_bytes != item['size_bytes']):
            conflict('Отправленный документ недоступен')
        path = settings.document_storage_path / document.storage_key
        if not path.is_file() or path.stat().st_size != document.size_bytes or hashlib.sha256(path.read_bytes()).hexdigest() != document.sha256:
            raise HTTPException(503, {'code': 'document_unavailable', 'message': 'Один из отправленных файлов временно недоступен'})
    original = {**snapshot['application']}
    result = evaluate(original, registered_at=date.fromisoformat(checks['registry'].data['registered_at']),
                      submitted_at=revision.created_at.date(), liquidated=checks['registry'].data['liquidated'],
                      overdue_days=checks['bki'].data['overdue_days'],
                      expected_monthly_revenue_kopecks=checks['tax'].data['expected_monthly_revenue_kopecks'],
                      policy_version=run.policy_version, catalog_version=run.catalog_version)
    if result.outcome in ('needs_info', 'rejected'):
        conflict('Уточните сведения или устраните запретные стоп-факторы')
    amount = values['amount_kopecks'] if amount is None else amount
    term = values['term_months'] if term is None else term
    validate_draft({**values, 'amount_kopecks': amount, 'term_months': term}, run.catalog_version)
    months = period_months(values['period_start'], values['period_end'], revision.created_at.date())
    terms = offer_terms(product, amount, term)
    gate = financial_gate(terms.payment_terms, values['revenue_kopecks'], values['operating_expenses_kopecks'],
                          values['existing_debt_payments_kopecks'], period_months=months)
    if not gate.allowed:
        conflict('Комиссия гарантии недоступна при указанных финансах' if gate.reason_code == 'guarantee_fee_unaffordable' else
                 'Сумма гарантии превышает половину расчётной годовой выручки' if gate.reason_code == 'guarantee_liability_exceeded' else
                 'Для этих условий коэффициент покрытия меньше 1,30')
    return terms.model_dump(mode='json'), run


def guard_risk(db, run, revision, terms, *, offered, user=None, reason=None, acknowledged=False, offer=None):
    profile = policy_profile(run.policy_version, run.catalog_version)
    if not profile.uses_risk_assessments:
        return None
    checks = {item.kind:item.data for item in db.scalars(select(CheckResult).where(CheckResult.run_id==run.id))}
    scope = 'offered_terms' if offered else 'requested_terms'
    canonical = terms_for(revision, terms['amount_kopecks'], terms['term_months'], run=run)
    unsupported = not requires_model(run.policy_version, canonical['product_code'])
    if offer is not None:
        row = exact_assessment(db, offer.risk_assessment_id, run, revision, checks, canonical, scope)
        if (row is None or row.offer_version != offer.version
                or offer.product_code != canonical['product_code'] or offer.annual_rate_bps != terms['annual_rate_bps']
                or offer.monthly_payment_kopecks != terms['monthly_payment_kopecks']
                or offer.total_payment_kopecks != terms['total_payment_kopecks']):
            conflict('Оценка предложенных условий отсутствует или устарела')
        if unsupported:
            actor = db.get(User, offer.actor_id) if offer.actor_id else None
            if actor is None or actor.role != 'staff':
                conflict('Для этого продукта требуется предложение сотрудника')
        if not unsupported and row.probability >= .10 and not db.scalar(select(RiskOverride.id).where(RiskOverride.assessment_id==row.id)):
            conflict('Не сохранено подтверждение сотрудником повышенного риска')
        return row
    row = assess(db, run, revision, checks, canonical, scope)
    if unsupported:
        if exact_assessment(db, row.id, run, revision, checks, canonical, scope) is None:
            conflict('Не подтверждена неприменимость модели к этим условиям')
        return row
    if row.status != 'succeeded':
        # До этого места команда ничего не меняла: коммитим только проверенную оценку.
        db.commit()
        raise HTTPException(503, {'code':'risk_model_unavailable', 'message':'Не удалось оценить риск этих условий. Повторите позже'})
    if row.probability >= .10 and not acknowledged:
        db.commit()
        raise HTTPException(409, {'code':'risk_acknowledgement_required',
                                 'message':'Изучите оценку этих условий и подтвердите рассмотрение повышенного риска'})
    if row.probability >= .10:
        record_override(db,row,user,reason)
    return row


def add_decision(db, application, revision, user, outcome, reason, policy_version, code, risk=None):
    decision = Decision(id=uuid.uuid4(), application_id=application.id, revision_id=revision.id, actor_id=user.id,
                        application_version=application.version, outcome=outcome, public_reason_codes=[code],
                        public_reasons=[reason], internal_reason=reason, policy_version=policy_version,
                        risk_assessment_id=risk.id if risk else None)
    db.add(decision)
    return decision


def decide(db, user, application_id, body, key):
    require_staff(user)
    def action(application, revision):
        if application.status != 'manual_review':
            conflict('Решение сотрудника сейчас недоступно')
        run = db.scalar(select(ProcessingRun).where(ProcessingRun.revision_id == revision.id))
        risk = None
        if body.outcome == 'approved':
            terms, run = safe_terms(db, application, revision)
            risk = guard_risk(db,run,revision,terms,offered=False,user=user,reason=body.reason,acknowledged=body.risk_acknowledged)
        supersede_offers(db, application)
        event(db, application, user, revision, 'staff_approved' if body.outcome == 'approved' else 'staff_rejected', body.outcome)
        decision = add_decision(db, application, revision, user, body.outcome, body.reason, run.policy_version, 'staff_decision',risk)
        return output(application, revision, decision_id=str(decision.id))
    return execute(db, user, application_id, body, key, 'staff_decision', action)


def create_offer(db, user, application_id, body, key):
    require_staff(user)
    def action(application, revision):
        if application.status != 'manual_review':
            conflict('Предложение сотрудника сейчас недоступно')
        terms, run = safe_terms(db, application, revision, body.amount_kopecks, body.term_months)
        risk = guard_risk(db,run,revision,terms,offered=True,user=user,reason=body.reason,acknowledged=body.risk_acknowledged)
        supersede_offers(db, application)
        event(db, application, user, revision, 'offer_created', 'counteroffer')
        offer = Offer(id=uuid.uuid4(), application_id=application.id, revision_id=revision.id, actor_id=user.id,
                      application_version=application.version, status='active', version=1, reason=body.reason,
                      risk_assessment_id=risk.id if risk else None, **terms)
        db.add(offer)
        add_decision(db, application, revision, user, 'counteroffer', body.reason, run.policy_version, 'staff_offer',risk)
        db.flush()
        return output(application, revision, offer=OfferOutput.model_validate(offer).model_dump(mode='json'))
    return execute(db, user, application_id, body, key, 'create_offer', action)


def offer_action(db, user, offer_id, body, key, accept):
    require_client(user)
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(404, {'code': 'offer_not_found', 'message': 'Предложение не найдено'})
    def action(application, revision):
        current = db.scalar(select(Offer).where(Offer.id == offer_id).with_for_update().execution_options(populate_existing=True))
        if (application.status != 'counteroffer' or current.status != 'active'
                or current.revision_id != revision.id or current.version != body.offer_version):
            conflict('Предложение устарело, обновите заявку')
        risk = None
        if accept:
            terms, run = safe_terms(db, application, revision, current.amount_kopecks, current.term_months)
            # Полные условия и старые колонки сверяются даже у исторической политики без ML.
            flat_fields = ('product_code', 'amount_kopecks', 'term_months', 'annual_rate_bps',
                           'monthly_payment_kopecks', 'total_payment_kopecks')
            if (any(getattr(current, name) != terms[name] for name in flat_fields)
                    or current.payment_terms is not None and current.payment_terms != terms['payment_terms']
                    or current.payment_terms is None and run.catalog_version != 'demo-v1'):
                conflict('Условия предложения изменились или устарели')
            risk = guard_risk(db,run,revision,terms,offered=True,offer=current)
        else:
            run = db.scalar(select(ProcessingRun).where(ProcessingRun.revision_id == revision.id))
        current.status = 'accepted' if accept else 'declined'
        current.responded_at = now()
        current.decline_reason = None if accept else body.decline_reason
        current.version += 1
        status = 'approved' if accept else 'manual_review'
        event(db, application, user, revision, 'offer_accepted' if accept else 'offer_declined', status)
        reason = 'Клиент принял предложенные условия' if accept else 'Клиент отклонил предложение; требуется рассмотрение сотрудника'
        add_decision(db, application, revision, user, status, reason, run.policy_version, 'offer_accepted' if accept else 'offer_declined',risk)
        return output(application, revision, offer=OfferOutput.model_validate(current).model_dump(mode='json'))
    # Идентификатор предложения входит в отпечаток повтора команды.
    operation = 'accept_offer' if accept else 'decline_offer'
    return execute(db, user, offer.application_id, body, key, operation, action, resource_id=offer_id)
