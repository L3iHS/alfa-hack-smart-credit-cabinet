import math
import uuid
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import text

from app.processing import service
from app.processing.policy import evaluate
from test_application_drafts import BASE, authenticate
from test_processing import prepared, process
from test_review import command, current


def fresh(client, profile='a'):
    return prepared(client, profile, legacy=False)


def stub_probability(monkeypatch, probability):
    from app.risk import assessments
    original = assessments.score_features
    def score(features, *, model_version):
        return replace(original(features, model_version=model_version), probability=probability)
    monkeypatch.setattr(assessments, 'score_features', score)


@pytest.mark.parametrize('probability,outcome,band', [
    (0.0, 'approved', 'low'), (math.nextafter(.1, 0), 'approved', 'low'),
    (.1, 'manual_review', 'elevated'), (math.nextafter(.3, 0), 'manual_review', 'elevated'),
    (.3, 'manual_review', 'high'), (1.0, 'manual_review', 'high'),
])
def test_exact_probability_changes_decision_and_staff_only_payload(client, db, monkeypatch, probability, outcome, band):
    stub_probability(monkeypatch, probability)
    _, identifier, submission = fresh(client)
    process()
    detail = current(client, identifier)
    assert detail['status'] == outcome
    assert 'probability' not in str(detail)
    assert client.get(f'{BASE}/{identifier}/assessment').status_code == 403
    authenticate(client, 'staff@example.test')
    result = client.get(f'{BASE}/{identifier}/assessment').json()
    risk = result['risk_assessment']
    assert risk['revision_id'] == submission['revision_id']
    assert risk['probability'] == probability and risk['risk_band'] == band
    assert risk['prediction_scope'] == 'requested_terms'
    assert result['runs'][0]['scorer_version'] == 'logistic-risk-v1'
    assert result['runs'][0]['policy_version'] == 'demo-policy-0.4'
    assert result['runs'][0]['risk_assessments'] == [risk]


@pytest.mark.parametrize('profile,outcome,reason', [('c','needs_info','revenue_mismatch'), ('e','rejected','overdue_90_plus')])
def test_priorities_skip_model_with_explicit_reason(client, db, monkeypatch, profile, outcome, reason):
    from app.risk import assessments
    def unavailable(*args, **kwargs):
        raise AssertionError('Модель не нужна до полноты и стоп-проверок')
    monkeypatch.setattr(assessments, 'score_features', unavailable)
    _, identifier, _ = fresh(client, profile)
    process()
    assert current(client, identifier)['status'] == outcome
    authenticate(client, 'staff@example.test')
    risk = client.get(f'{BASE}/{identifier}/assessment').json()['risk_assessment']
    assert risk['status'] == 'not_applicable' and risk['reason_code'] == reason
    assert risk['probability'] is None


def test_mandatory_model_failure_has_no_decision_and_retry_keeps_version(client, db, monkeypatch):
    _, identifier, _ = fresh(client)
    db.execute(text("UPDATE processing_runs SET scorer_version='unavailable-model'"))
    db.commit()
    process()
    detail = current(client, identifier)
    assert detail['processing_status'] == 'failed'
    assert detail['public_reasons'] == []
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0
    assert db.execute(text('SELECT count(*) FROM offers')).scalar_one() == 0
    staff = authenticate(client, 'staff@example.test')
    risk = client.get(f'{BASE}/{identifier}/assessment').json()['risk_assessment']
    assert risk['status'] == 'failed' and risk['probability'] is None
    retry = command(client, staff, f'{BASE}/{identifier}/processing-retries', {'expected_version':detail['version']})
    assert retry.status_code == 202
    process()
    assert current(client, identifier)['processing_status'] == 'failed'
    assert db.execute(text('SELECT scorer_version FROM processing_runs')).scalar_one() == 'unavailable-model'


@pytest.mark.parametrize('probability,outcome', [(.01,'counteroffer'),(.1,'manual_review')])
def test_candidate_recomputed_for_exact_amount_and_term(client, db, monkeypatch, probability, outcome):
    from app.risk import assessments
    original = assessments.score_features
    seen = []
    def score(features, *, model_version):
        seen.append(features.values.copy())
        return replace(original(features, model_version=model_version), probability=.01 if len(seen)==1 else probability)
    monkeypatch.setattr(assessments, 'score_features', score)
    _, identifier, _ = fresh(client, 'b')
    process()
    assert current(client, identifier)['status'] == outcome
    assert len(seen) == 2
    assert seen[0]['requested_amount_rub'] == 5000000
    assert seen[1]['requested_amount_rub'] == 2342000 and seen[1]['term_months'] == 24
    assert seen[0]['coverage_ratio'] != seen[1]['coverage_ratio']
    assert db.execute(text('SELECT count(*) FROM risk_assessments')).scalar_one() == 2
    linked = db.execute(text('SELECT r.prediction_scope, r.probability FROM decisions d JOIN risk_assessments r ON r.id=d.risk_assessment_id')).one()
    assert linked.prediction_scope == 'offered_terms' and linked.probability == probability
    if outcome == 'manual_review':
        assert db.execute(text('SELECT public_reason_codes FROM decisions')).scalar_one() == ['offered_risk_review_required']
        assert db.execute(text('SELECT count(*) FROM offers')).scalar_one() == 0


@pytest.mark.parametrize('endpoint', ['decisions','offers'])
def test_risk_ack_is_durable_but_rejected_command_has_no_partial_effects(client, db, monkeypatch, endpoint):
    stub_probability(monkeypatch, .3)
    _, identifier, _ = fresh(client)
    process()
    staff = authenticate(client, 'staff@example.test')
    detail = current(client, identifier)
    before_events = db.execute(text('SELECT count(*) FROM application_events')).scalar_one()
    body = {'expected_version':detail['version'], 'reason':'Риск рассмотрен сотрудником'}
    body.update({'outcome':'approved'} if endpoint=='decisions' else {'amount_kopecks':190000000,'term_months':25})
    key = str(uuid.uuid4())
    path = f'{BASE}/{identifier}/{endpoint}'
    rejected = command(client, staff, path, body, key)
    assert rejected.status_code == 409 and rejected.json()['code'] == 'risk_acknowledgement_required'
    assert current(client, identifier)['version'] == detail['version']
    assert db.execute(text('SELECT count(*) FROM application_events')).scalar_one() == before_events
    assert db.execute(text('SELECT count(*) FROM offers')).scalar_one() == 0
    assert db.execute(text('SELECT count(*) FROM decisions WHERE actor_id IS NOT NULL')).scalar_one() == 0
    assert db.execute(text("SELECT count(*) FROM idempotency_records WHERE operation IN ('staff_decision','create_offer')")).scalar_one() == 0
    count = db.execute(text('SELECT count(*) FROM risk_assessments')).scalar_one()
    risk = client.get(f'{BASE}/{identifier}/assessment').json()
    assert len(risk['runs'][0]['risk_assessments']) == count
    result = command(client, staff, path, {**body,'risk_acknowledged':True}, key)
    assert result.status_code == 201, result.text
    assert command(client, staff, path, {**body,'risk_acknowledged':True}, key).json() == result.json()
    assert db.execute(text('SELECT count(*) FROM risk_assessments')).scalar_one() == count
    audit = db.execute(text('SELECT actor_id, assessment_id, reason FROM risk_overrides')).one()
    assert audit.actor_id and audit.assessment_id and audit.reason == body['reason']


def test_staff_model_error_preserves_only_failure_and_original_run(client, db, monkeypatch):
    from app.risk import assessments
    stub_probability(monkeypatch,.2)
    _, identifier, _ = fresh(client)
    process()
    def fail(*args, **kwargs):
        raise assessments.RiskModelError('private input')
    monkeypatch.setattr(assessments,'score_features',fail)
    staff = authenticate(client,'staff@example.test')
    detail = current(client,identifier)
    result = command(client,staff,f'{BASE}/{identifier}/offers',dict(expected_version=detail['version'],amount_kopecks=190000000,term_months=25,reason='Обоснование',risk_acknowledged=True))
    assert result.status_code == 503 and 'private' not in result.text
    assert current(client,identifier)['version'] == detail['version']
    assert db.execute(text('SELECT status FROM processing_runs')).scalar_one() == 'succeeded'
    assert db.execute(text("SELECT count(*) FROM risk_assessments WHERE status='failed'")).scalar_one() == 1
    assert db.execute(text('SELECT count(*) FROM offers')).scalar_one() == 0


@pytest.mark.parametrize('raise_error', [False,True])
def test_aba_attempt_fences_late_source_success_and_error(client, db, monkeypatch, raise_error):
    from app.processing import providers
    _, identifier, submission = fresh(client)
    original = providers.check
    triggered = False
    def check(kind, snapshot, version):
        nonlocal triggered
        if not triggered:
            triggered = True
            service.recover_interrupted()
            with service.SessionLocal() as other:
                other.execute(text("UPDATE processing_runs SET status='pending'"))
                other.commit()
            assert service.claim_next() is not None
            if raise_error:
                raise RuntimeError('late old attempt')
        return original(kind,snapshot,version)
    monkeypatch.setattr(providers,'check',check)
    process()
    row = db.execute(text('SELECT status, attempt FROM processing_runs')).one()
    assert row.status == 'running' and row.attempt == 2
    assert db.execute(text('SELECT count(*) FROM check_results')).scalar_one() == 0
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0


def test_new_submission_pins_mandatory_model(client, db):
    fresh(client)
    row = db.execute(text('SELECT policy_version, scorer_version FROM processing_runs')).one()
    assert row.policy_version == 'demo-policy-0.4'
    assert row.scorer_version == 'logistic-risk-v1'


@pytest.mark.parametrize('expenses,outcome,low,high', [(30000000,'approved',.06,.08),(150000000,'manual_review',.16,.18)])
def test_real_model_changes_route_with_sufficient_coverage(client, db, expenses, outcome, low, high):
    from test_application_drafts import create
    from test_documents import attach
    from test_submission import submit
    from app.demo.profiles import application_fields
    headers=authenticate(client,'demo-a@example.test')
    draft=create(client,headers,**{**application_fields('a'),'operating_expenses_kopecks':expenses})
    draft,_=attach(client,headers,draft)
    draft,_=attach(client,headers,draft,'equipment_invoice')
    assert submit(client,headers,draft).status_code==202
    process()
    assert current(client,draft['id'])['status']==outcome
    authenticate(client,'staff@example.test')
    run=client.get(f"{BASE}/{draft['id']}/assessment").json()['runs'][0]
    assert float(run['calculation']['coverage_ratio'])>=1.30
    assert low<run['risk_assessments'][0]['probability']<high


@pytest.mark.parametrize('tamper',['missing','original','amount','rate','payment','checks','scorer','override'])
def test_offer_acceptance_requires_exact_immutable_context_and_override(client,db,monkeypatch,tamper):
    stub_probability(monkeypatch,.3)
    client_headers,identifier,_=fresh(client)
    process()
    staff=authenticate(client,'staff@example.test')
    body=dict(expected_version=current(client,identifier)['version'],amount_kopecks=190000000,term_months=25,
              reason='Согласован повышенный риск новых условий',risk_acknowledged=True)
    made=command(client,staff,f'{BASE}/{identifier}/offers',body)
    assert made.status_code==201,made.text
    if tamper=='missing':
        db.execute(text('UPDATE offers SET risk_assessment_id=NULL'))
    elif tamper=='original':
        db.execute(text("UPDATE offers SET risk_assessment_id=(SELECT id FROM risk_assessments WHERE prediction_scope='requested_terms')"))
    elif tamper=='amount':
        db.execute(text('UPDATE offers SET amount_kopecks=180000000'))
    elif tamper=='rate':
        db.execute(text('UPDATE offers SET annual_rate_bps=0'))
    elif tamper=='payment':
        db.execute(text('UPDATE offers SET monthly_payment_kopecks=1,total_payment_kopecks=25'))
    elif tamper=='checks':
        db.execute(text("UPDATE check_results SET data=jsonb_set(data,'{overdue_days}','1') WHERE kind='bki'"))
    elif tamper=='scorer':
        db.execute(text('UPDATE processing_runs SET scorer_version=NULL'))
    elif tamper=='override':
        db.execute(text('DELETE FROM risk_overrides'))
    db.commit()
    headers=authenticate(client,'demo-a@example.test')
    offer=current(client,identifier)['offers'][-1]
    before=current(client,identifier)['version']
    result=command(client,headers,f"/api/v1/offers/{offer['id']}/accept",dict(expected_version=before,offer_version=offer['version']))
    assert result.status_code==409,result.text
    assert current(client,identifier)['version']==before
    assert current(client,identifier)['offers'][-1]['status']=='active'


def test_elevated_offer_accepts_saved_staff_override(client,db,monkeypatch):
    stub_probability(monkeypatch,.3)
    _,identifier,_=fresh(client)
    process()
    staff=authenticate(client,'staff@example.test')
    made=command(client,staff,f'{BASE}/{identifier}/offers',dict(expected_version=current(client,identifier)['version'],
         amount_kopecks=190000000,term_months=25,reason='Риск оценён',risk_acknowledged=True))
    assert made.status_code==201,made.text
    headers=authenticate(client,'demo-a@example.test')
    offer=current(client,identifier)['offers'][-1]
    result=command(client,headers,f"/api/v1/offers/{offer['id']}/accept",dict(expected_version=current(client,identifier)['version'],offer_version=offer['version']))
    assert result.status_code==200,result.text
    assert current(client,identifier)['status']=='approved'


@pytest.mark.parametrize('raise_error',[False,True])
def test_aba_attempt_fences_late_score_success_and_error(client,db,monkeypatch,raise_error):
    from app.risk import assessments
    fresh(client)
    original=assessments.score_features
    def score(features,*,model_version):
        service.recover_interrupted()
        with service.SessionLocal() as other:
            other.execute(text("UPDATE processing_runs SET status='pending'"))
            other.commit()
        assert service.claim_next() is not None
        if raise_error:
            raise RuntimeError('late score failure')
        return original(features,model_version=model_version)
    monkeypatch.setattr(assessments,'score_features',score)
    process()
    assert db.execute(text('SELECT status,attempt FROM processing_runs')).one()==('running',2)
    assert db.execute(text('SELECT count(*) FROM risk_assessments')).scalar_one()==0
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one()==0


@pytest.mark.parametrize('failure',['model','source'])
def test_worker_failures_never_create_decision(client,db,monkeypatch,failure):
    from app.risk import assessments
    from app.processing import providers
    _,identifier,_=fresh(client)
    def fail(*args,**kwargs):
        raise RuntimeError('private')
    monkeypatch.setattr(assessments if failure=='model' else providers,'score_features' if failure=='model' else 'check',fail)
    process()
    assert current(client,identifier)['processing_status']=='failed'
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one()==0
    assert db.execute(text('SELECT count(*) FROM offers')).scalar_one()==0


def test_candidate_failure_has_no_partial_decision_or_offer(client,db,monkeypatch):
    from app.risk import assessments
    original=assessments.score_features
    def score(features,*,model_version):
        if features.values['term_months']==24:
            raise RuntimeError('unavailable candidate')
        return replace(original(features,model_version=model_version),probability=.01)
    monkeypatch.setattr(assessments,'score_features',score)
    _,identifier,_=fresh(client,'b')
    process()
    assert current(client,identifier)['processing_status']=='failed'
    assert db.execute(text('SELECT status FROM risk_assessments ORDER BY created_at')).scalars().all()==['succeeded','failed']
    assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one()==0
    assert db.execute(text('SELECT count(*) FROM offers')).scalar_one()==0


def test_current_revision_does_not_expose_old_requested_risk(client,db,monkeypatch):
    from test_review import response_body
    stub_probability(monkeypatch,.2)
    _,identifier,_=fresh(client)
    process()
    staff=authenticate(client,'staff@example.test')
    request=command(client,staff,f'{BASE}/{identifier}/information-requests',dict(expected_version=current(client,identifier)['version'],message='Уточните цель',requested_fields=['purpose']))
    assert request.status_code==201
    headers=authenticate(client,'demo-a@example.test')
    response=command(client,headers,f'{BASE}/{identifier}/information-responses',response_body(current(client,identifier)))
    assert response.status_code==202
    authenticate(client,'staff@example.test')
    assessment=client.get(f'{BASE}/{identifier}/assessment').json()
    assert len(assessment['runs'])==2
    assert assessment['risk_assessment'] is None
    assert assessment['runs'][0]['risk_assessments'][0]['status']=='succeeded'


def test_risk_success_cannot_be_changed_in_database(client,db,monkeypatch):
    from sqlalchemy.exc import DBAPIError
    stub_probability(monkeypatch,.01)
    fresh(client)
    process()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE risk_assessments SET probability=.9 WHERE status='succeeded'"))
    db.rollback()


@pytest.mark.parametrize('probability',[float('nan'),-.01,1.01])
def test_policy_requires_valid_probability_after_hard_checks(probability):
    data=dict(product_code='equipment',amount_kopecks=200000000,term_months=24,
              period_start='2026-07-01',period_end='2026-09-30',revenue_kopecks=240000000,
              operating_expenses_kopecks=150000000,existing_debt_payments_kopecks=15000000)
    with pytest.raises(ValueError):
        evaluate(data,registered_at=date(2024,1,1),submitted_at=date(2026,10,20),overdue_days=0,
                 liquidated=False,policy_version='demo-policy-0.3',probability=probability)


@pytest.mark.parametrize('probability,flow,outcome',[(.01,60739458,'approved'),(.01,60739457,'counteroffer'),(.1,60739458,'manual_review')])
def test_ml_and_exact_coverage_boundaries(probability,flow,outcome):
    data=dict(product_code='equipment',amount_kopecks=200000000,term_months=24,
              period_start='2026-07-01',period_end='2026-09-30',revenue_kopecks=150000000+flow,
              operating_expenses_kopecks=150000000,existing_debt_payments_kopecks=15000000)
    result=evaluate(data,registered_at=date(2024,1,1),submitted_at=date(2026,10,20),overdue_days=0,
                    liquidated=False,policy_version='demo-policy-0.3',probability=probability)
    assert result.outcome==outcome


@pytest.mark.parametrize('profile,expected', [('d','short_business_history'),('a','current_overdue')])
def test_manual_rules_follow_successful_low_risk(client,db,monkeypatch,profile,expected):
    from app.processing import providers
    stub_probability(monkeypatch,.01)
    original=providers.check
    def check(kind,snapshot,version):
        return {'overdue_days':1} if kind=='bki' and profile=='a' else original(kind,snapshot,version)
    monkeypatch.setattr(providers,'check',check)
    _,identifier,_=fresh(client,profile)
    process()
    assert current(client,identifier)['status']=='manual_review'
    assert db.execute(text('SELECT public_reason_codes FROM decisions')).scalar_one()==[expected]
    assert db.execute(text('SELECT status FROM risk_assessments')).scalar_one()=='succeeded'



def test_worker_fences_before_taking_assessment_foreign_key_lock(client,db,monkeypatch):
    from app.risk import assessments
    from sqlalchemy.exc import OperationalError
    _,identifier,submission=fresh(client)
    original_score=assessments.score_features
    original_locked=service.current_locked
    scored=False
    lock_available=[]
    def score(features,*,model_version):
        nonlocal scored
        scored=True
        return replace(original_score(features,model_version=model_version),probability=.01)
    def current_locked(session,run_id,attempt=None):
        nonlocal scored
        if scored:
            scored=False
            with service.SessionLocal() as other:
                try:
                    other.execute(text('SELECT id FROM processing_runs WHERE id=:id FOR UPDATE NOWAIT'),{'id':run_id})
                    lock_available.append(True)
                except OperationalError:
                    lock_available.append(False)
        return original_locked(session,run_id,attempt)
    monkeypatch.setattr(assessments,'score_features',score)
    monkeypatch.setattr(service,'current_locked',current_locked)
    process()
    assert lock_available==[True]
    assert current(client,identifier)['status']=='approved'
