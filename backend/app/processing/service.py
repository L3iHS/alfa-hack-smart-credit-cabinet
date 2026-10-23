import hashlib
import json
import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.applications.models import Application, ApplicationEvent
from app.applications.service import get_application
from app.applications.submission_models import ApplicationRevision, IdempotencyRecord, ProcessingRun
from app.auth.models import User
from app.core.db import SessionLocal
from app.demo.profiles import SOURCE_VERSION
from app.processing import providers
from app.processing.models import Calculation, CheckResult, Decision, InformationRequest, Offer
from app.processing.policy import evaluate, policy_profile
from app.risk.assessments import assess, assessment_output, terms_for
from app.risk.models import RiskAssessment
from app.risk.runtime import RiskModelError
from app.processing.schemas import AssessmentOutput, CalculationOutput, CheckOutput, DecisionOutput, RetryInput, RunOutput


logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def latest_revision(db: Session, application_id: uuid.UUID) -> ApplicationRevision | None:
    return db.scalar(select(ApplicationRevision).where(ApplicationRevision.application_id == application_id)
                     .order_by(ApplicationRevision.application_version.desc()).limit(1))


def system_event(db: Session, application: Application, run: ProcessingRun, event_type: str) -> None:
    application.version += 1
    application.updated_at = now()
    db.add(ApplicationEvent(application_id=application.id, actor_id=None, actor_type='system', event_type=event_type,
                            application_version=application.version, revision_id=run.revision_id, processing_run_id=run.id))


def require_staff(user: User) -> None:
    if user.role != 'staff':
        raise HTTPException(403, {'code': 'operation_forbidden', 'message': 'Операция доступна сотруднику'})


def assessment(db: Session, user: User, application_id: uuid.UUID) -> AssessmentOutput:
    require_staff(user)
    get_application(db, user, application_id)
    revision = latest_revision(db, application_id)
    outputs = []
    for run in db.scalars(select(ProcessingRun).where(ProcessingRun.application_id == application_id).order_by(ProcessingRun.created_at)):
        output = RunOutput.model_validate(run)
        output.checks = [CheckOutput.model_validate(item) for item in db.scalars(select(CheckResult).where(CheckResult.run_id == run.id).order_by(CheckResult.created_at))]
        calculation = db.scalar(select(Calculation).where(Calculation.run_id == run.id))
        output.calculation = CalculationOutput.model_validate(calculation.data) if calculation else None
        decision = db.scalar(select(Decision).where(Decision.run_id == run.id))
        output.decision = DecisionOutput.model_validate(decision) if decision else None
        output.risk_assessments = [assessment_output(item) for item in db.scalars(select(RiskAssessment).where(
            RiskAssessment.processing_run_id==run.id).order_by(RiskAssessment.created_at, RiskAssessment.id))]
        outputs.append(output)
    current = next((run for run in reversed(outputs) if revision and run.revision_id==revision.id), None)
    risk = next((item for item in reversed(current.risk_assessments) if item.prediction_scope=='requested_terms'), None) if current else None
    return AssessmentOutput(application_id=application_id, revision_id=revision.id if revision else None, runs=outputs, risk_assessment=risk)


def retry_processing(db: Session, user: User, application_id: uuid.UUID, body: RetryInput, key: uuid.UUID) -> dict:
    require_staff(user)
    get_application(db, user, application_id)
    fingerprint = hashlib.sha256(json.dumps({'application_id':str(application_id), **body.model_dump()}, sort_keys=True).encode()).hexdigest()
    lock_key = int.from_bytes(hashlib.sha256(f'{user.id}:retry_processing:{key}'.encode()).digest()[:8], signed=True)
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key':lock_key})
    previous = db.get(IdempotencyRecord, (user.id, 'retry_processing', key))
    if previous:
        if previous.fingerprint != fingerprint:
            raise HTTPException(409, {'code':'idempotency_conflict', 'message':'Ключ уже использован с другими данными'})
        return previous.response
    application = get_application(db, user, application_id, lock=True)
    revision = latest_revision(db, application.id)
    run = db.scalar(select(ProcessingRun).where(ProcessingRun.revision_id == revision.id).with_for_update()) if revision else None
    if (application.version != body.expected_version or application.status not in ('submitted','processing')
            or run is None or run.status not in ('failed','interrupted')):
        raise HTTPException(409, {'code':'processing_conflict','message':'Обновите заявку: повтор обработки сейчас недоступен'})
    run.status = 'pending'
    run.started_at = None
    run.finished_at = None
    run.error_code = None
    application.status = 'processing'
    application.version += 1
    application.updated_at = now()
    db.add(ApplicationEvent(application_id=application.id, application_version=application.version, actor_id=user.id,
                            actor_type='user', event_type='processing_retried', revision_id=revision.id, processing_run_id=run.id))
    result = dict(application_id=str(application.id), version=application.version, status=application.status,
                  revision_id=str(revision.id), processing_run_id=str(run.id))
    db.add(IdempotencyRecord(user_id=user.id, operation='retry_processing',key=key,fingerprint=fingerprint,response=result))
    db.commit()
    return result


def recover_interrupted() -> int:
    count = 0
    with SessionLocal() as db:
        ids = db.scalars(select(ProcessingRun.id).where(ProcessingRun.status.in_(['pending','running']))).all()
        for run_id in ids:
            run = db.get(ProcessingRun, run_id)
            application = db.scalar(select(Application).where(Application.id == run.application_id).with_for_update())
            db.refresh(run, with_for_update=True)
            if run.status not in ('pending','running'):
                continue
            run.status = 'interrupted'
            run.error_code = 'process_interrupted'
            run.finished_at = now()
            if latest_revision(db, application.id).id == run.revision_id:
                system_event(db, application, run, 'processing_interrupted')
            count += 1
        db.commit()
    return count


def current_locked(db: Session, run_id: uuid.UUID, attempt: int | None = None):
    candidate = db.get(ProcessingRun, run_id)
    application = db.scalar(select(Application).where(Application.id == candidate.application_id).with_for_update())
    run = db.scalar(select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update().execution_options(populate_existing=True))
    if attempt is not None and run.attempt != attempt:
        return None
    revision = latest_revision(db, application.id)
    valid = run.status == 'running' and revision is not None and revision.id == run.revision_id and application.status == 'processing'
    if not valid:
        if run.status == 'running':
            run.status = 'interrupted'
            run.error_code = 'stale_revision'
            run.finished_at = now()
            db.commit()
        return None
    return application, run, revision


def claim_next(*, with_attempt=False):
    with SessionLocal() as db:
        candidate = db.scalar(select(ProcessingRun).where(ProcessingRun.status == 'pending').order_by(ProcessingRun.created_at).limit(1))
        if candidate is None:
            return None
        application = db.scalar(select(Application).where(Application.id == candidate.application_id).with_for_update())
        run = db.scalar(select(ProcessingRun).where(ProcessingRun.id == candidate.id).with_for_update().execution_options(populate_existing=True))
        if run.status != 'pending':
            return None
        revision = latest_revision(db, application.id)
        if revision is None or revision.id != run.revision_id or application.status not in ('submitted','processing'):
            run.status = 'interrupted'
            run.error_code = 'stale_revision'
            run.finished_at = now()
        else:
            run.status = 'running'
            run.attempt += 1
            run.started_at = now()
            application.status = 'processing'
            system_event(db, application, run, 'processing_started')
        db.commit()
        return (run.id, run.attempt) if with_attempt else run.id


def process_next() -> bool:
    claimed = claim_next(with_attempt=True)
    if claimed is None:
        return False
    run_id, attempt = claimed
    stage = 'initialization'
    try:
        with SessionLocal() as db:
            state = current_locked(db, run_id, attempt)
            if state is None:
                return True
            _, run, revision = state
            try:
                profile = policy_profile(run.policy_version, run.catalog_version)
            except ValueError as exc:
                raise providers.UnsupportedVersion('Версия расчёта не поддерживается') from exc
            if run.source_version != SOURCE_VERSION:
                raise providers.UnsupportedVersion('Версия расчёта не поддерживается')
            snapshot, submitted_at = revision.snapshot, revision.created_at.date()
            source_version, policy_version, catalog_version = run.source_version, run.policy_version, run.catalog_version
            db.commit()
        checks = {}
        for kind in ('registry','tax','bki'):
            stage = f'check_{kind}'
            with SessionLocal() as db:
                state = current_locked(db, run_id, attempt)
                if state is None:
                    return True
                cached = db.scalar(select(CheckResult).where(CheckResult.run_id == run_id, CheckResult.kind == kind))
                if cached:
                    checks[kind] = cached.data
                    continue
            data = providers.check(kind, snapshot, source_version)
            with SessionLocal() as db:
                state = current_locked(db, run_id, attempt)
                if state is None:
                    return True
                _, run, _ = state
                db.add(CheckResult(run_id=run.id, revision_id=run.revision_id, kind=kind, source_version=source_version, data=data))
                db.commit()
                checks[kind] = data
        stage = 'policy'
        kwargs = dict(registered_at=date.fromisoformat(checks['registry']['registered_at']), submitted_at=submitted_at,
                      liquidated=checks['registry']['liquidated'], overdue_days=checks['bki']['overdue_days'],
                      expected_monthly_revenue_kopecks=checks['tax']['expected_monthly_revenue_kopecks'],
                      policy_version=policy_version, catalog_version=catalog_version)
        result = evaluate(snapshot['application'], **kwargs)
        requested_risk = offered_risk = None
        if profile.uses_risk_assessments:
            stage = 'risk'
            with SessionLocal() as db:
                state = current_locked(db, run_id, attempt)
                if state is None:
                    return True
                _, run, revision = state
                db.commit()
                # Внешний расчёт выполняется без блокировки; перед commit сверяем попытку заново.
                requested_risk = assess(db, run, revision, checks, terms_for(revision, run=run), 'requested_terms',
                                      not_applicable=result.reason_code if result.outcome in ('needs_info','rejected') else None, persist=False)
                state = current_locked(db, run_id, attempt)
                if state is None:
                    db.rollback()
                    return True
                db.add(requested_risk)
                db.commit()
                if requested_risk.status == 'failed':
                    raise RiskModelError('Не удалось выполнить обязательную оценку риска')
            if requested_risk.status == 'succeeded':
                result = evaluate(snapshot['application'], probability=requested_risk.probability, **kwargs)
                if result.offer:
                    with SessionLocal() as db:
                        state = current_locked(db, run_id, attempt)
                        if state is None:
                            return True
                        _, run, revision = state
                        db.commit()
                        offered_risk = assess(db, run, revision, checks,
                            terms_for(revision,result.offer.amount_kopecks,result.offer.term_months,run=run), 'offered_terms', persist=False)
                        if current_locked(db, run_id, attempt) is None:
                            db.rollback()
                            return True
                        db.add(offered_risk)
                        db.commit()
                        if offered_risk.status == 'failed':
                            raise RiskModelError('Не удалось оценить предложенные условия')
                        if offered_risk.probability >= .10:
                            result = result.model_copy(update=dict(outcome='manual_review', offer=None,
                                reason_code='offered_risk_review_required', reason='Новые условия требуют рассмотрения сотрудника'))
        stage = 'persist_result'
        with SessionLocal() as db:
            state = current_locked(db, run_id, attempt)
            if state is None:
                return True
            application, run, revision = state
            application.status = result.outcome
            system_event(db, application, run, 'processing_completed')
            if result.calculation:
                db.add(Calculation(run_id=run.id, revision_id=revision.id, data=result.calculation.model_dump(mode='json')))
            linked_risk = offered_risk if offered_risk is not None else requested_risk
            db.add(Decision(application_id=application.id, revision_id=revision.id, run_id=run.id, actor_id=None,
                            risk_assessment_id=linked_risk.id if linked_risk else None,
                            application_version=application.version, outcome=result.outcome, public_reason_codes=[result.reason_code],
                            public_reasons=[result.reason], internal_reason=result.reason, policy_version=run.policy_version))
            if result.outcome == 'needs_info':
                db.add(InformationRequest(application_id=application.id, revision_id=revision.id, run_id=run.id,
                                          application_version=application.version, message=result.reason,
                                          requested_fields=result.requested_fields, requested_document_types=[]))
            if result.offer:
                db.add(Offer(application_id=application.id, revision_id=revision.id, run_id=run.id,
                             risk_assessment_id=offered_risk.id if offered_risk else None,
                             application_version=application.version, reason=result.reason, **result.offer.model_dump(mode='json')))
            run.status, run.finished_at, run.error_code = 'succeeded', now(), None
            db.commit()
    except Exception as exc:
        # Не пишем входные сведения и текст исключения: источник может включить их в ошибку.
        if not isinstance(exc, (providers.UnsupportedVersion, RiskModelError)):
            logger.error('Unexpected processing failure', extra={'run_id': str(run_id), 'stage': stage, 'exception_type': type(exc).__name__})
        with SessionLocal() as db:
            state = current_locked(db, run_id, attempt)
            if state:
                application, run, _ = state
                run.status, run.finished_at = 'failed', now()
                run.error_code = ('unsupported_version' if isinstance(exc, providers.UnsupportedVersion) else
                                  'risk_model_failed' if isinstance(exc, RiskModelError) else 'check_failed')
                system_event(db, application, run, 'processing_failed')
                db.commit()
    return True
