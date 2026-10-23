"""Полные ручные сценарии новых продуктов и совместимость запусков."""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from test_application_drafts import BASE, authenticate, create, patch
from test_documents import attach
from test_processing import process, prepared
from test_review import command, current, response_body
from test_submission import COMPLETE, submit


CASES = [
    ('overdraft', 10_000_000, 3, 'bank_statement', {}),
    ('credit_line', 50_000_000, 24, 'bank_statement', {}),
    ('investment', 300_000_000, 120, 'business_plan', {'project_description': 'Новая пекарня'}),
    ('tender_guarantee', 10_000_000, 12, 'tender_document',
     {'tender_number': 'Т-123', 'beneficiary_name': 'Заказчик'}),
]


def new_submission(client, case, **changes):
    code, amount, term, document, fields = case
    headers = authenticate(client)
    draft = create(client, headers, **{**COMPLETE, 'product_code': code,
        'amount_kopecks': amount, 'term_months': term, **fields, **changes})
    draft, _ = attach(client, headers, draft)
    draft, _ = attach(client, headers, draft, document)
    sent = submit(client, headers, draft)
    assert sent.status_code == 202, sent.text
    assert process()
    return headers, draft['id'], sent.json()


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('action', ['approve', 'reject', 'accept', 'decline', 'information'])
def test_new_product_full_manual_flows(client, db, monkeypatch, case, action):
    from app.risk import assessments
    def forbidden(*args, **kwargs):
        raise AssertionError('Неподдерживаемый продукт не вызывает модель')
    monkeypatch.setattr(assessments, 'score_features', forbidden)
    _, identifier, sent = new_submission(client, case)
    assert current(client, identifier)['status'] == 'manual_review'
    staff = authenticate(client, 'staff@example.test')
    assessment = client.get(f'{BASE}/{identifier}/assessment').json()
    run = assessment['runs'][0]
    assert (run['catalog_version'], run['policy_version'], run['scorer_version']) == ('demo-v2', 'demo-policy-0.4', None)
    risk = assessment['risk_assessment']
    assert risk['status'] == 'not_applicable' and risk['reason_code'] == 'unsupported_product'
    assert all(risk[name] is None for name in ('scorer_version', 'feature_schema_version', 'target_event', 'horizon_months', 'probability', 'risk_band'))
    assert risk['contributions'] == []
    assert run['calculation']['payment_terms']['amount_kopecks'] == case[1]
    snapshot = db.execute(text('SELECT snapshot FROM application_revisions WHERE id=:id'), {'id': sent['revision_id']}).scalar_one()
    assert snapshot['catalog_version'] == 'demo-v2'
    assert all(snapshot['application'][name] == value for name, value in case[4].items())
    body = {'expected_version': current(client, identifier)['version'], 'reason': 'Проверены условия продукта'}
    if action in ('approve', 'reject'):
        made = command(client, staff, f'{BASE}/{identifier}/decisions', {**body, 'outcome': 'approved' if action == 'approve' else 'rejected'})
        assert made.status_code == 201, made.text
        assert current(client, identifier)['status'] == ('approved' if action == 'approve' else 'rejected')
    elif action == 'information':
        field = next(iter(case[4]), 'purpose')
        request = command(client, staff, f'{BASE}/{identifier}/information-requests',
            {'expected_version': body['expected_version'], 'message': 'Уточните сведения', 'requested_fields': [field], 'requested_document_types': [case[3]]})
        assert request.status_code == 201, request.text
        headers = authenticate(client)
        detail = current(client, identifier)
        detail, _ = attach(client, headers, detail, case[3])
        result = command(client, headers, f'{BASE}/{identifier}/information-responses', response_body(current(client, identifier)))
        assert result.status_code == 202, result.text
        process()
        assert current(client, identifier)['status'] == 'manual_review'
        assert db.execute(text('SELECT count(*) FROM application_revisions')).scalar_one() == 2
    else:
        made = command(client, staff, f'{BASE}/{identifier}/offers', {**body, 'amount_kopecks': case[1], 'term_months': case[2]})
        assert made.status_code == 201, made.text
        offer = made.json()['offer']
        assert offer['payment_terms']['amount_kopecks'] == case[1]
        if case[0] == 'tender_guarantee':
            assert offer['payment_terms']['monthly_payment_kopecks'] is None
            assert offer['payment_terms']['annual_rate_bps'] is None
            assert offer['monthly_payment_kopecks'] == offer['annual_rate_bps'] == 0
        headers = authenticate(client)
        body = {'expected_version': current(client, identifier)['version'], 'offer_version': offer['version']}
        key = str(uuid.uuid4())
        path = f"/api/v1/offers/{offer['id']}/{action}"
        result = command(client, headers, path, body, key)
        assert result.status_code == 200, result.text
        assert command(client, headers, path, body, key).json() == result.json()
        assert current(client, identifier)['status'] == ('approved' if action == 'accept' else 'manual_review')
    assert db.execute(text('SELECT count(*) FROM risk_overrides')).scalar_one() == 0


@pytest.mark.parametrize('case', CASES)
def test_new_product_requires_own_documents_and_specific_fields(client, db, case):
    code, amount, term, document, fields = case
    headers = authenticate(client)
    draft = create(client, headers, **{**COMPLETE, 'product_code': code, 'amount_kopecks': amount, 'term_months': term})
    draft, _ = attach(client, headers, draft)
    invalid = submit(client, headers, draft)
    assert invalid.status_code == 422
    assert 'documents' in invalid.json()['field_errors']
    assert all(name in invalid.json()['field_errors'] for name in fields)
    if fields:
        draft = patch(client, headers, draft, **fields).json()
    draft, _ = attach(client, headers, draft, document)
    assert submit(client, headers, draft).status_code == 202


def test_specific_fields_normalize_and_reject_wrong_product(client):
    headers = authenticate(client)
    draft = create(client, headers, product_code='tender_guarantee', tender_number='  Т-1  ', beneficiary_name='   ')
    assert draft['tender_number'] == 'Т-1' and draft['beneficiary_name'] is None
    assert patch(client, headers, draft, product_code='working_capital').status_code == 422
    result = patch(client, headers, draft, product_code='working_capital', tender_number=None)
    assert result.status_code == 200


@pytest.mark.parametrize('operation', ['save', 'submit'])
def test_old_draft_moves_to_current_catalog_only_on_explicit_action(client, db, operation):
    headers = authenticate(client)
    draft = create(client, headers, **COMPLETE)
    draft, _ = attach(client, headers, draft)
    db.execute(text("UPDATE applications SET catalog_version='demo-v1'"))
    db.commit()
    assert current(client, draft['id'])['catalog_version'] == 'demo-v1'
    result = patch(client, headers, draft, purpose=COMPLETE['purpose']) if operation == 'save' else submit(client, headers, draft)
    assert result.status_code == (200 if operation == 'save' else 202), result.text
    assert current(client, draft['id'])['catalog_version'] == 'demo-v2'


@pytest.mark.parametrize('tamper', ['typed', 'legacy', 'product', 'catalog', 'policy', 'assessment', 'reason', 'manual_origin', 'assessment_terms', 'snapshot', 'attempt'])
def test_new_offer_acceptance_rejects_tampering(client, db, tamper):
    _, identifier, _ = new_submission(client, CASES[3])
    staff = authenticate(client, 'staff@example.test')
    made = command(client, staff, f'{BASE}/{identifier}/offers', dict(expected_version=current(client, identifier)['version'],
        amount_kopecks=10_000_000, term_months=12, reason='Комиссия доступна'))
    assert made.status_code == 201, made.text
    statements = {
        'typed': "UPDATE offers SET payment_terms=jsonb_set(payment_terms,'{contingent_liability_kopecks}','1')",
        'legacy': 'UPDATE offers SET monthly_payment_kopecks=1',
        'product': "UPDATE offers SET product_code='overdraft'",
        'catalog': "UPDATE processing_runs SET catalog_version='demo-v1'",
        'policy': "UPDATE processing_runs SET policy_version='demo-policy-0.2'",
        'assessment': "UPDATE offers SET risk_assessment_id=(SELECT id FROM risk_assessments WHERE prediction_scope='requested_terms')",
        'reason': "UPDATE risk_assessments SET reason_code='financial_period_required' WHERE prediction_scope='offered_terms'",
        'manual_origin': 'UPDATE offers SET actor_id=NULL',
        'assessment_terms': "UPDATE risk_assessments SET terms=jsonb_set(terms,'{payment_terms,total_cost_kopecks}','1') WHERE prediction_scope='offered_terms'",
        'snapshot': "UPDATE application_revisions SET snapshot=jsonb_set(snapshot,'{application,beneficiary_name}','\"Другой заказчик\"')",
        'attempt': 'UPDATE processing_runs SET attempt=attempt+1',
    }
    db.execute(text(statements[tamper]))
    db.commit()
    headers = authenticate(client)
    offer = made.json()['offer']
    before = current(client, identifier)['version']
    result = command(client, headers, f"/api/v1/offers/{offer['id']}/accept", {'expected_version': before, 'offer_version': offer['version']})
    assert result.status_code == 409, result.text
    assert current(client, identifier)['version'] == before


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('operation', ['offers', 'decisions'])
def test_new_manual_financial_gate_cannot_be_bypassed(client, db, case, operation):
    _, identifier, _ = new_submission(client, case, revenue_kopecks=1, operating_expenses_kopecks=0)
    staff = authenticate(client, 'staff@example.test')
    body = dict(expected_version=current(client, identifier)['version'], reason='Проверка ограничения')
    body.update(dict(amount_kopecks=case[1], term_months=case[2]) if operation == 'offers' else dict(outcome='approved'))
    result = command(client, staff, f'{BASE}/{identifier}/{operation}', body)
    assert result.status_code == 409, result.text


@pytest.mark.parametrize('failed', [False, True])
def test_historical_03_remains_mandatory_after_activation(client, db, monkeypatch, failed):
    from app.risk import assessments
    _, identifier, sent = prepared(client, legacy=False)
    db.execute(text("UPDATE processing_runs SET policy_version='demo-policy-0.3', catalog_version='demo-v1'"))
    db.execute(text("UPDATE application_revisions SET snapshot=snapshot-'catalog_version'"))
    db.commit()
    if failed:
        def unavailable(*args, **kwargs):
            raise RuntimeError('Обязательная модель недоступна')
        monkeypatch.setattr(assessments, 'score_features', unavailable)
    process()
    detail = current(client, identifier)
    assert detail['processing_status'] == ('failed' if failed else 'succeeded')
    assert db.execute(text('SELECT status FROM risk_assessments')).scalar_one() == ('failed' if failed else 'succeeded')
    terms, fingerprint = db.execute(text('SELECT terms,terms_fingerprint FROM risk_assessments')).one()
    assert terms == dict(product_code='equipment', amount_kopecks=200_000_000, term_months=24, annual_rate_bps=2400)
    assert fingerprint == 'd6f87a78246f4346d56224dda4c49742f0dae209a04860760c71d778ebca7daf'
    if failed:
        assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0
        staff = authenticate(client, 'staff@example.test')
        retried = command(client, staff, f'{BASE}/{identifier}/processing-retries', {'expected_version': detail['version']})
        assert retried.status_code == 202, retried.text
        process()
        assert current(client, identifier)['processing_status'] == 'failed'
        assert db.execute(text('SELECT policy_version,catalog_version FROM processing_runs')).one() == ('demo-policy-0.3', 'demo-v1')
        assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0


def test_financial_gate_exact_coverage_fee_and_guarantee_boundaries():
    from app.products.calculations import calculate_terms
    from app.products.catalog import get_product
    from app.products.financial import financial_gate
    annuity = calculate_terms(get_product('investment', 'demo-v2'), 300_000_000, 120)
    burden = annuity.assessment_monthly_burden_kopecks
    assert annuity.upfront_fee_kopecks == 4_500_000
    boundary = Decimal('1.30') * burden
    assert financial_gate(annuity, boundary, 0, 0).allowed
    assert not financial_gate(annuity, boundary - Decimal('.01'), 0, 0).allowed
    guarantee = calculate_terms(get_product('tender_guarantee', 'demo-v2'), 60_000_000, 12)
    allowed = financial_gate(guarantee, 10_000_000, 8_200_000, 0)
    assert allowed.allowed and allowed.coverage_ratio is None
    assert allowed.guarantee_fee_affordable is True and allowed.guarantee_liability_within_limit is True
    assert not financial_gate(guarantee, 10_000_000, 8_200_001, 0).allowed
    assert not financial_gate(guarantee, 9_999_999, 0, 0).allowed


def test_expanded_catalog_does_not_expand_frozen_features_or_training_manifest():
    from app.products.catalog import PRODUCTS
    from app.risk.dataset import _schema
    from app.risk.features import build_features
    from app.risk.catalog import ML_CATALOG_VERSION, ML_PRODUCTS
    assert len(PRODUCTS) == 6
    assert ML_CATALOG_VERSION == 'demo-v1' and set(ML_PRODUCTS) == {'working_capital', 'equipment'}
    assert _schema()['columns']['product_code']['values'] == ['equipment', 'working_capital']
    with pytest.raises(ValueError, match='Продукт'):
        build_features({**COMPLETE, 'product_code': 'overdraft', 'amount_kopecks': 10_000_000, 'term_months': 3},
            registered_at=date(2024, 1, 1), submitted_at=date(2026, 10, 23), overdue_days=0, annual_rate_bps=2100)


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('failure', ['incomplete', 'stop', 'source'])
def test_new_products_keep_completeness_stop_and_source_priority(client, db, monkeypatch, case, failure):
    from app.processing import providers
    from app.risk import assessments
    original = providers.check
    def check(kind, snapshot, version):
        if failure == 'source':
            raise RuntimeError('Источник временно недоступен')
        if kind == 'tax' and failure == 'incomplete':
            return {'expected_monthly_revenue_kopecks': 1}
        if kind == 'bki':
            return {'overdue_days': 100}
        return original(kind, snapshot, version)
    def forbidden(*args, **kwargs):
        raise AssertionError('Новые продукты не используют модель')
    monkeypatch.setattr(providers, 'check', check)
    monkeypatch.setattr(assessments, 'score_features', forbidden)
    _, identifier, _ = new_submission(client, case)
    detail = current(client, identifier)
    if failure == 'source':
        assert detail['processing_status'] == 'failed'
        assert db.execute(text('SELECT count(*) FROM decisions')).scalar_one() == 0
        assert db.execute(text('SELECT count(*) FROM risk_assessments')).scalar_one() == 0
    else:
        assert detail['status'] == ('needs_info' if failure == 'incomplete' else 'rejected')
        assert db.execute(text('SELECT reason_code FROM risk_assessments')).scalar_one() == ('revenue_mismatch' if failure == 'incomplete' else 'overdue_90_plus')


@pytest.mark.parametrize('version', ['demo-policy-0.2', 'demo-policy-0.3'])
@pytest.mark.parametrize('action', ['approve', 'accept', 'retry'])
def test_historical_runs_manual_offer_and_retry_use_own_versions(client, db, monkeypatch, version, action):
    from test_risk_decisions import stub_probability
    stub_probability(monkeypatch, .3)
    _, identifier, sent = prepared(client, 'd', legacy=False)
    db.execute(text("UPDATE processing_runs SET policy_version=:version,catalog_version='demo-v1',scorer_version=:scorer"),
        {'version': version, 'scorer': 'logistic-risk-v1' if version == 'demo-policy-0.3' else None})
    db.execute(text("UPDATE application_revisions SET snapshot=snapshot-'catalog_version'"))
    db.commit()
    if action == 'retry':
        db.execute(text("UPDATE processing_runs SET status='failed'"))
        db.commit()
        staff = authenticate(client, 'staff@example.test')
        result = command(client, staff, f'{BASE}/{identifier}/processing-retries', {'expected_version': current(client, identifier)['version']})
        assert result.status_code == 202, result.text
        process()
        assert current(client, identifier)['status'] == 'manual_review'
        assert db.execute(text('SELECT policy_version,catalog_version FROM processing_runs')).one() == (version, 'demo-v1')
        return
    process()
    staff = authenticate(client, 'staff@example.test')
    body = dict(expected_version=current(client, identifier)['version'], reason='Исторические условия проверены', risk_acknowledged=True)
    if action == 'approve':
        made = command(client, staff, f'{BASE}/{identifier}/decisions', {**body, 'outcome': 'approved'})
        assert made.status_code == 201, made.text
    else:
        made = command(client, staff, f'{BASE}/{identifier}/offers', {**body, 'amount_kopecks': 40_000_000, 'term_months': 12})
        assert made.status_code == 201, made.text
        # Историческая строка до добавления payment_terms сериализуется без пересчёта.
        db.execute(text('UPDATE offers SET payment_terms=NULL'))
        db.commit()
        headers = authenticate(client, 'demo-d@example.test')
        detail = current(client, identifier)
        offer = detail['offers'][-1]
        assert offer['payment_terms']['monthly_payment_kopecks'] == offer['monthly_payment_kopecks']
        accepted = command(client, headers, f"/api/v1/offers/{offer['id']}/accept", dict(expected_version=detail['version'], offer_version=offer['version']))
        assert accepted.status_code == 200, accepted.text
    assert current(client, identifier)['status'] == 'approved'


def test_financial_gate_period_totals_do_not_round_coverage_boundary():
    from app.products.calculations import calculate_terms
    from app.products.catalog import get_product
    from app.products.financial import financial_gate
    terms = calculate_terms(get_product('equipment', 'demo-v1'), 200_000_000, 24)
    # 3*10574220+10 = 31722670; точная граница потока за три месяца 41239471.
    assert financial_gate(terms, 41_239_471, 0, 10, period_months=3).allowed
    assert not financial_gate(terms, 41_239_470, 0, 10, period_months=3).allowed


def test_new_specific_snapshot_field_is_checked_before_unsupported_model():
    from app.processing.policy import evaluate
    result = evaluate({**COMPLETE, 'product_code': 'investment', 'amount_kopecks': 300_000_000, 'term_months': 120},
        registered_at=date(2024, 1, 1), submitted_at=date(2026, 10, 23), overdue_days=0, liquidated=False)
    assert result.outcome == 'needs_info'
    assert result.requested_fields == ['project_description']


def test_historical_calculation_reads_saved_values_without_backfill(client, db):
    _, identifier, _ = prepared(client)
    process()
    db.execute(text("UPDATE calculations SET data=data-'payment_terms'-'financial_gate'"))
    db.commit()
    saved = db.execute(text('SELECT data FROM calculations')).scalar_one()
    authenticate(client, 'staff@example.test')
    response = client.get(f'{BASE}/{identifier}/assessment')
    assert response.status_code == 200, response.text
    calculation = response.json()['runs'][0]['calculation']
    assert calculation == {**saved, 'payment_terms': None, 'financial_gate': None}
    assert db.execute(text('SELECT data FROM calculations')).scalar_one() == saved


def test_cached_historical_offer_response_restores_terms_without_repricing(client, db):
    _, identifier, _ = prepared(client, 'd')
    process()
    staff = authenticate(client, 'staff@example.test')
    body = dict(expected_version=current(client, identifier)['version'], amount_kopecks=40_000_000,
                term_months=12, reason='Историческое предложение')
    key = str(uuid.uuid4())
    path = f'{BASE}/{identifier}/offers'
    made = command(client, staff, path, body, key)
    assert made.status_code == 201, made.text
    db.execute(text("UPDATE idempotency_records SET response=response #- '{offer,payment_terms}' WHERE operation='create_offer'"))
    db.commit()
    saved = db.execute(text("SELECT response FROM idempotency_records WHERE operation='create_offer'")).scalar_one()
    repeated = command(client, staff, path, body, key)
    assert repeated.status_code == 201, repeated.text
    restored = repeated.json()['offer']['payment_terms']
    assert restored['monthly_payment_kopecks'] == saved['offer']['monthly_payment_kopecks']
    assert restored['total_payment_kopecks'] == saved['offer']['total_payment_kopecks']
    assert db.execute(text("SELECT response FROM idempotency_records WHERE operation='create_offer'")).scalar_one() == saved
