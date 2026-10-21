import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.applications.schemas import DraftFields, SubmissionInput
from app.applications.service import add_event, get_application, require_client, validate_draft
from app.applications.submission_models import ApplicationRevision, IdempotencyRecord, ProcessingRun
from app.applications.submission_policy import BKI_CONSENT_TEXT, CONSENT_VERSION, DATA_CONFIRMATION_TEXT, POLICY_VERSION
from app.auth.models import User
from app.companies.models import Company
from app.companies.schemas import CompanyOutput
from app.core.config import settings
from app.demo.profiles import SOURCE_VERSION
from app.documents.schemas import DocumentOutput
from app.documents.service import active_documents, require_editable
from app.products.catalog import CATALOG_VERSION, PRODUCTS
from app.risk.runtime import MODEL_VERSION


def submit_application(db: Session, user: User, application_id: uuid.UUID, body: SubmissionInput, key: uuid.UUID) -> dict:
    require_client(user)
    get_application(db, user, application_id)
    fingerprint = hashlib.sha256(json.dumps(
        {'application_id': str(application_id), **body.model_dump()}, sort_keys=True, separators=(',', ':'),
    ).encode()).hexdigest()
    lock_key = int.from_bytes(hashlib.sha256(f'{user.id}:submit:{key}'.encode()).digest()[:8], signed=True)
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
    previous = db.get(IdempotencyRecord, (user.id, 'submit', key))
    if previous:
        if previous.fingerprint != fingerprint:
            raise HTTPException(409, {'code': 'idempotency_conflict', 'message': 'Этот ключ уже использован для другой отправки'})
        return previous.response
    application = get_application(db, user, application_id, lock=True)
    require_editable(application, body.expected_version)
    result, _ = create_submission(db, user, application, body)
    db.add(IdempotencyRecord(user_id=user.id, operation='submit', key=key, fingerprint=fingerprint, response=result))
    db.commit()
    return result


def validate_submission(db: Session, application: Application, body: SubmissionInput):
    values = DraftFields.model_validate(application).model_dump()
    validate_draft(values)
    errors = {}
    for field in ('purpose', 'amount_kopecks', 'term_months', 'period_start', 'period_end',
                  'revenue_kopecks', 'operating_expenses_kopecks', 'existing_debt_payments_kopecks'):
        if values[field] is None or (field == 'purpose' and not values[field].strip()):
            errors[field] = 'Заполните поле перед отправкой'
    if not body.data_confirmed:
        errors['data_confirmed'] = 'Подтвердите данные заявки'
    if not body.bki_consent:
        errors['bki_consent'] = 'Подтвердите демонстрационную проверку БКИ'
    if body.consent_version != CONSENT_VERSION:
        errors['consent_version'] = 'Текст согласия изменился, обновите страницу'
    documents = active_documents(db, application.id)
    if not set(PRODUCTS[application.product_code].required_document_types) <= {item.document_type for item in documents}:
        errors['documents'] = 'Прикрепите все обязательные документы выбранного продукта'
    if errors:
        raise HTTPException(422, {'code': 'validation_error', 'message': 'Заявка ещё не готова к отправке', 'field_errors': errors})
    if application.catalog_version != CATALOG_VERSION:
        raise HTTPException(409, {'code': 'catalog_changed', 'message': 'Условия продукта изменились, обновите заявку'})
    for document in documents:
        path = settings.document_storage_path / document.storage_key
        if not path.is_file() or path.stat().st_size != document.size_bytes:
            raise HTTPException(503, {'code': 'document_unavailable', 'message': 'Один из файлов временно недоступен'})
    return documents


def create_submission(db: Session, user: User, application: Application, body: SubmissionInput,
                      event_type: str = 'application_submitted'):
    documents = validate_submission(db, application, body)
    now = datetime.now(timezone.utc)
    application.version += 1
    application.status = 'submitted'
    application.updated_at = now
    revision = ApplicationRevision(
        id=uuid.uuid4(), application_id=application.id, application_version=application.version,
        submitted_by=user.id, created_at=now,
        snapshot={
            'application': DraftFields.model_validate(application).model_dump(mode='json'),
            'company': CompanyOutput.model_validate(db.get(Company, application.company_id)).model_dump(mode='json'),
            'documents': [{**DocumentOutput.model_validate(document).model_dump(mode='json'), 'sha256': document.sha256} for document in documents],
            'confirmations': {
                'data_confirmed': True, 'bki_consent': True, 'consent_version': CONSENT_VERSION,
                'confirmed_at': now.isoformat(), 'data_confirmation_text': DATA_CONFIRMATION_TEXT,
                'bki_consent_text': BKI_CONSENT_TEXT,
            },
        },
    )
    db.add(revision)
    db.flush()
    run = ProcessingRun(
        id=uuid.uuid4(), application_id=application.id, revision_id=revision.id, status='pending',
        catalog_version=application.catalog_version, policy_version=POLICY_VERSION, source_version=SOURCE_VERSION, scorer_version=MODEL_VERSION,
    )
    db.add(run)
    db.flush()
    add_event(db, application, user, event_type, revision_id=revision.id, processing_run_id=run.id)
    result = {
        'application_id': str(application.id), 'version': application.version, 'status': 'submitted',
        'revision_id': str(revision.id), 'processing_run_id': str(run.id),
    }
    return result, revision
