import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text, update

from app.applications.models import Application
from app.applications.submission_models import ApplicationRevision
from app.auth.models import AuthSession, User
from app.core.db import SessionLocal
from app.processing.models import Offer
from test_application_drafts import authenticate, create
from test_assistant_chat import fake
from test_auth import csrf
from test_processing import prepared, process


def summary(client, headers, application, **changes):
    return client.post(f"/api/v1/applications/{application['id']}/summary",
        json={'expected_version': application['version'], **changes}, headers=headers)


def ready(client, profile='d', *, legacy=False):
    _, identifier, submitted = prepared(client, profile, legacy=legacy)
    assert process()
    headers = authenticate(client, 'staff@example.test')
    current = client.get(f'/api/v1/applications/{identifier}').json()
    return headers, current, submitted


def facts(fake):
    return {source['id'].rsplit(':', 1)[-1]: json.loads(source['text'])
            for source in json.loads(fake.calls[-1][1])['sources']}


def test_staff_only_access_auth_and_csrf_precede_generation(client, fake):
    path = f'/api/v1/applications/{uuid.uuid4()}/summary'
    assert client.post(path, json={'expected_version': 1}).status_code == 403
    assert client.post(path, json={'expected_version': 1}, headers={'X-CSRF-Token': csrf(client)}).status_code == 401
    headers = authenticate(client)
    draft = create(client, headers)
    assert summary(client, headers, draft).status_code == 403
    staff = authenticate(client, 'staff@example.test')
    assert summary(client, staff, draft).status_code == 404
    assert client.post(path, json={'expected_version': 1}, headers=staff).status_code == 404
    assert not fake.calls


@pytest.mark.parametrize('changes', [{'expected_version': True}, {'expected_version': 0},
    {'expected_version': '1'}, {'expected_version': 1, 'decision': 'approved'}])
def test_closed_version_input(client, fake, changes):
    headers, current, _ = ready(client)
    assert summary(client, headers, current, **changes).status_code == 422
    assert not fake.calls


def test_current_summary_contains_finances_checks_lr_and_explicit_units(client, fake):
    headers, current, submitted = ready(client)
    response = summary(client, headers, current)
    assert response.status_code == 200, response.text
    output = response.json()
    assert output['status'] == 'answered' and output['model'] == 'test-model'
    assert output['revision_id'] == submitted['revision_id']
    assert output['processing_run_id'] == submitted['processing_run_id']
    assert output['application_version'] == current['version']
    assert output['knowledge_version'] == current['catalog_version']
    assert datetime.fromisoformat(output['generated_at']).tzinfo is not None
    sources = json.loads(fake.calls[-1][1])['sources']
    assert output['sources'] == [sources[0]]
    data = facts(fake)
    assert data['request']['amount_kopecks'] == current['amount_kopecks']
    assert data['request']['revenue_kopecks'] == current['revenue_kopecks']
    assert set(data['checks']['results']) == {'registry', 'tax', 'bki'}
    assert data['calculation']['data']['monthly_payment_kopecks'] > 0
    risk = data['requested_terms']
    assert risk['status'] == 'succeeded' and risk['data']['contributions']
    assert risk['data']['processing_run_id'] == submitted['processing_run_id']
    assert risk['data']['prediction_scope'] == 'requested_terms'
    assert 'копейках' in data['units']['money'] and '100' in data['units']['money']
    system = fake.calls[-1][0]
    assert '4–6' in system and 'недоверенные данные' in system
    assert 'линейные вклады' in system and 'самостоятельную рекомендацию' in system


def test_initial_and_offered_terms_and_risks_are_separate(client, db, fake):
    from test_review import command
    headers, current, _ = ready(client)
    response = command(client, headers, f"/api/v1/applications/{current['id']}/offers", {
        'expected_version': current['version'], 'amount_kopecks': 10000000,
        'term_months': current['term_months'], 'reason': 'Проверенные изменённые условия', 'risk_acknowledged': True})
    assert response.status_code == 201, response.text
    offer = response.json()['offer']
    current = client.get(f"/api/v1/applications/{current['id']}").json()
    assert summary(client, headers, current).status_code == 200
    data = facts(fake)
    assert data['request']['amount_kopecks'] == current['amount_kopecks']
    assert data['requested_terms']['data']['terms']['amount_kopecks'] == current['amount_kopecks']
    assert data['offered_terms']['data']['terms']['amount_kopecks'] == offer['amount_kopecks']
    assert data['offered_terms']['data']['offer_version'] == offer['version']
    db.execute(update(Offer).where(Offer.id == uuid.UUID(offer['id'])).values(status='superseded'))
    db.execute(update(Application).where(Application.id == uuid.UUID(current['id'])).values(status='manual_review'))
    db.commit()
    assert summary(client, headers, current).status_code == 200
    assert facts(fake)['offered_terms']['status'] == 'missing'


@pytest.mark.parametrize('case_index', range(4))
def test_new_product_risk_is_explicitly_not_applicable(client, fake, case_index):
    from test_product_processing import CASES, new_submission
    _, identifier, _ = new_submission(client, CASES[case_index])
    headers = authenticate(client, 'staff@example.test')
    current = client.get(f'/api/v1/applications/{identifier}').json()
    assert summary(client, headers, current).status_code == 200
    risk = facts(fake)['requested_terms']
    assert risk['status'] == 'not_applicable'
    assert risk['data']['probability'] is None and risk['data']['contributions'] == []
    assert 'не применяется' in risk['note']


def test_previous_revision_run_offer_and_risk_are_not_current(client, db, fake):
    headers, current, previous = ready(client, 'b')
    old = db.get(ApplicationRevision, uuid.UUID(previous['revision_id']))
    revision = ApplicationRevision(application_id=old.application_id, application_version=current['version'] + 1,
        submitted_by=old.submitted_by, created_at=old.created_at, snapshot=old.snapshot)
    db.add(revision)
    db.flush()
    db.execute(update(Application).where(Application.id == old.application_id).values(version=current['version'] + 1))
    db.commit()
    current['version'] += 1
    response = summary(client, headers, current)
    assert response.status_code == 200, response.text
    assert response.json()['revision_id'] == str(revision.id)
    assert response.json()['processing_run_id'] is None
    payload = fake.calls[-1][1]
    assert previous['processing_run_id'] not in payload and previous['revision_id'] not in payload
    data = facts(fake)
    assert data['run']['status'] == 'missing'
    assert data['checks']['status'] == 'missing' and data['calculation']['status'] == 'missing'
    assert data['requested_terms']['status'] == 'missing' and data['offered_terms']['status'] == 'missing'


def test_failed_processing_is_technical_failure(client, fake, monkeypatch):
    def failed(*args):
        raise RuntimeError('private upstream exception')
    monkeypatch.setattr('app.processing.providers.check', failed)
    headers, current, _ = ready(client)
    assert summary(client, headers, current).status_code == 200
    data = facts(fake)
    assert data['run']['status'] == 'technical_failure' and data['run']['data']['status'] == 'failed'
    assert data['checks']['results'] == {}
    assert data['requested_terms']['status'] == 'missing'
    assert 'private upstream exception' not in fake.calls[-1][1]


def test_missing_risk_documents_and_no_attachment_reads(client, db, fake, monkeypatch):
    headers, current, _ = ready(client, legacy=True)
    from app.documents.models import Document
    db.execute(delete(Document).where(Document.application_id == uuid.UUID(current['id'])))
    db.commit()
    def forbidden(*args, **kwargs):
        raise AssertionError('Сводка не читает содержимое файлов')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    assert summary(client, headers, current).status_code == 200
    data = facts(fake)
    assert data['requested_terms']['status'] == 'missing'
    assert data['documents']['missing_document_types']
    assert data['documents']['content_read'] is False and 'содержимое' in data['documents']['note']


def test_summary_releases_locks_and_does_not_write_business_data(client, db, fake):
    headers, current, _ = ready(client)
    tables = ['applications', 'application_events', 'application_revisions', 'processing_runs', 'documents',
              'decisions', 'offers', 'information_requests', 'calculations', 'check_results',
              'risk_assessments', 'risk_overrides']
    def snapshot():
        return [db.execute(text(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY id), '[]'::jsonb) FROM {table} t")).scalar_one() for table in tables]
    before = snapshot()
    def during():
        with SessionLocal() as other:
            list(other.scalars(select(AuthSession).with_for_update(nowait=True)))
            list(other.scalars(select(Application).with_for_update(nowait=True)))
    fake.during = during
    assert summary(client, headers, current).status_code == 200
    assert snapshot() == before


@pytest.mark.parametrize('change,want', [('version', 409), ('session', 401), ('role', 403), ('draft', 404)])
def test_summary_revalidates_after_generation(client, fake, change, want):
    headers, current, _ = ready(client)
    def during():
        with SessionLocal() as other:
            if change == 'version':
                other.execute(update(Application).where(Application.id == uuid.UUID(current['id'])).values(version=current['version'] + 1))
            elif change == 'draft':
                other.execute(update(Application).where(Application.id == uuid.UUID(current['id'])).values(status='draft'))
            else:
                staff = other.scalar(select(User).where(User.email == 'staff@example.test'))
                if change == 'session':
                    other.execute(delete(AuthSession).where(AuthSession.user_id == staff.id))
                else:
                    owner = other.scalar(select(User).where(User.email == 'client1@example.test'))
                    other.execute(update(User).where(User.id == staff.id).values(role='client', company_id=owner.company_id))
            other.commit()
    fake.during = during
    assert summary(client, headers, current).status_code == want


def test_stale_version_precedes_model(client, fake):
    headers, current, _ = ready(client)
    assert summary(client, headers, current, expected_version=current['version'] + 1).status_code == 409
    assert not fake.calls


@pytest.mark.parametrize('result', [{'answer': 'Ответ', 'source_ids': ['foreign']},
    {'answer': 'Ответ', 'source_ids': []}, {'answer': ' ', 'source_ids': ['anything']},
    {'answer': 'Ответ'}, {'answer': 'Ответ', 'source_ids': ['anything'], 'decision': 'approved'}])
def test_invalid_generated_summary_is_safe_503(client, fake, result):
    headers, current, _ = ready(client)
    fake.result = result
    response = summary(client, headers, current)
    assert response.status_code == 503 and response.json()['code'] == 'assistant_unavailable'


def test_existing_assistant_routes_remain_compatible(client, fake):
    headers = authenticate(client)
    response = client.post('/api/v1/assistant/intake', json={'text': 'Нужны деньги'}, headers=headers)
    assert response.status_code == 503
    assert fake.calls
    assert client.post('/api/v1/assistant/chat', json={'question': 'Документы для оборудования'}, headers=headers).status_code == 200
    assert client.post('/api/v1/intake', json={'text': 'Нужны деньги'}, headers=headers).status_code == 404


def test_accepted_offer_is_current_agreed_terms_with_its_own_risk(client, fake):
    from test_review import command
    headers, current, _ = ready(client)
    made = command(client, headers, f"/api/v1/applications/{current['id']}/offers", {
        'expected_version': current['version'], 'amount_kopecks': 10000000,
        'term_months': current['term_months'], 'reason': 'Проверенное предложение', 'risk_acknowledged': True})
    assert made.status_code == 201, made.text
    offer = made.json()['offer']
    client_headers = authenticate(client, 'demo-d@example.test')
    current = client.get(f"/api/v1/applications/{current['id']}").json()
    accepted = command(client, client_headers, f"/api/v1/offers/{offer['id']}/accept", {
        'expected_version': current['version'], 'offer_version': offer['version']})
    assert accepted.status_code == 200, accepted.text
    current = client.get(f"/api/v1/applications/{current['id']}").json()
    headers = authenticate(client, 'staff@example.test')
    response = summary(client, headers, current)
    assert response.status_code == 200, response.text
    data = facts(fake)
    assert data['state']['status'] == 'approved'
    assert data['offered_terms']['status'] == 'succeeded'
    assert data['offered_terms']['data']['terms']['amount_kopecks'] == offer['amount_kopecks']
    assert data['requested_terms']['data']['terms']['amount_kopecks'] == current['amount_kopecks']
    offer_sources = [source for source in json.loads(fake.calls[-1][1])['sources'] if ':offer:' in source['id']]
    assert len(offer_sources) == 1 and json.loads(offer_sources[0]['text'])['status'] == 'accepted'


def test_current_open_clarification_and_missing_finances_are_explicit(client, fake):
    headers, current, _ = ready(client, 'c')
    assert summary(client, headers, current).status_code == 200
    data = facts(fake)
    assert data['request']['revenue_kopecks'] == current['revenue_kopecks']
    sources = json.loads(fake.calls[-1][1])['sources']
    clarifications = [json.loads(source['text']) for source in sources if ':clarification:' in source['id']]
    assert len(clarifications) == 1 and 'revenue_kopecks' in clarifications[0]['requested_fields']


def test_failed_risk_is_technical_failure_not_credit_refusal(client, fake, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError('private model failure')
    monkeypatch.setattr('app.risk.assessments.score_features', failed)
    headers, current, _ = ready(client)
    assert summary(client, headers, current).status_code == 200
    risk = facts(fake)['requested_terms']
    assert risk['status'] == 'technical_failure'
    assert risk['data']['probability'] is None and risk['data']['status'] == 'failed'
    assert 'private model failure' not in fake.calls[-1][1]


def test_risk_from_previous_attempt_of_same_run_is_not_current(client, db, fake):
    from app.applications.submission_models import ProcessingRun
    headers, current, submitted = ready(client)
    run = db.get(ProcessingRun, uuid.UUID(submitted['processing_run_id']))
    run.attempt += 1
    db.commit()
    assert summary(client, headers, current).status_code == 200
    assert facts(fake)['requested_terms']['status'] == 'missing'
