"""Сохраняет оценку конкретных условий отдельно от бизнес-решения."""
import hashlib
import json
import math
import uuid
from dataclasses import asdict
from datetime import date

from sqlalchemy import select

from app.products.catalog import PRODUCTS
from app.risk.features import build_features
from app.risk.models import RiskAssessment, RiskOverride
from app.risk.runtime import RiskModelError, score_features
from app.risk.schemas import RiskAssessmentOutput


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def terms_for(revision, amount=None, term=None):
    data = revision.snapshot['application']
    return dict(product_code=data['product_code'], amount_kopecks=data['amount_kopecks'] if amount is None else amount,
                term_months=data['term_months'] if term is None else term,
                annual_rate_bps=PRODUCTS[data['product_code']].annual_rate_bps)


def context_for(run, revision, checks, terms, scope):
    return digest(dict(run_id=str(run.id), revision_id=str(revision.id), snapshot=revision.snapshot,
                       checks=checks, terms=terms, scope=scope, policy_version=run.policy_version,
                       scorer_version=run.scorer_version, source_version=run.source_version,
                       catalog_version=run.catalog_version))


def assess(db, run, revision, checks, terms, scope, *, not_applicable=None, persist=True):
    context = context_for(run, revision, checks, terms, scope)
    existing = db.scalar(select(RiskAssessment).where(RiskAssessment.context_fingerprint==context,
                         RiskAssessment.status.in_(['succeeded','not_applicable'])))
    if existing:
        return existing
    row = RiskAssessment(id=uuid.uuid4(), revision_id=revision.id, processing_run_id=run.id,
                         attempt=run.attempt, prediction_scope=scope, context_fingerprint=context,
                         terms_fingerprint=digest(terms), terms=terms,
                         offer_version=1 if scope=='offered_terms' else None,
                         scorer_version=run.scorer_version, status='not_applicable' if not_applicable else 'failed',
                         reason_code=not_applicable, payload={})
    if not not_applicable:
        try:
            features = build_features({**revision.snapshot['application'],
                                      'amount_kopecks':terms['amount_kopecks'], 'term_months':terms['term_months']},
                                      registered_at=date.fromisoformat(checks['registry']['registered_at']),
                                      submitted_at=revision.created_at.date(), overdue_days=checks['bki']['overdue_days'],
                                      annual_rate_bps=terms['annual_rate_bps'])
            row.inputs, row.missing_mask = features.values, features.missing_mask
            prediction = score_features(features, model_version=run.scorer_version)
            if (prediction.model_version != run.scorer_version or type(prediction.probability) not in (int,float)
                    or not math.isfinite(prediction.probability) or not 0<=prediction.probability<=1):
                raise RiskModelError('Неверный результат модели')
            row.probability, row.payload, row.status = prediction.probability, asdict(prediction), 'succeeded'
        except Exception:
            # Текст внешнего исключения не сохраняется: он может содержать входные данные.
            row.status, row.reason_code = 'failed', 'risk_model_failed'
    if persist:
        db.add(row)
        db.flush()
    return row


def assessment_output(row):
    payload = {key:value for key,value in row.payload.items() if key!='model_version'}
    return RiskAssessmentOutput(**payload, assessment_id=row.id, revision_id=row.revision_id,
        processing_run_id=row.processing_run_id, status=row.status, reason_code=row.reason_code,
        scorer_version=row.scorer_version, prediction_scope=row.prediction_scope, offer_version=row.offer_version,
        terms_fingerprint=row.terms_fingerprint, terms=row.terms,
        **({} if 'probability' in payload else {'probability':None}),
        risk_band=None if row.probability is None else ('low' if row.probability<.1 else 'elevated' if row.probability<.3 else 'high'))


def exact_assessment(db, assessment_id, run, revision, checks, terms, scope):
    row = db.get(RiskAssessment, assessment_id) if assessment_id else None
    if (row is None or row.status!='succeeded' or row.revision_id!=revision.id
            or row.processing_run_id!=run.id or row.scorer_version!=run.scorer_version
            or row.prediction_scope!=scope or row.terms!=terms or row.terms_fingerprint!=digest(terms)
            or row.context_fingerprint!=context_for(run,revision,checks,terms,scope)):
        return None
    return row


def record_override(db, row, user, reason):
    db.add(RiskOverride(assessment_id=row.id, actor_id=user.id, reason=reason))
