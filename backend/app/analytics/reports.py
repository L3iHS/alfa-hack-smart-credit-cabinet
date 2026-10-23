"""Когортные отчёты: SQL-агрегаты и ограниченная страница сохранённых условий."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import BigInteger, case, func, select
from sqlalchemy.orm import Session

from app.analytics.models import AnalyticsEvent, AnalyticsJourney
from app.analytics.schemas import (AnalyticsSummary, ConditionChangeCount, CounterofferPage, CounterofferRow,
                                   DeclineReasonCount, FunnelStage, LastStepCount, ObservationCount,
                                   OfferOutcomeCount, ReportMetadata, ResponseCoverage)
from app.applications.models import Application
from app.applications.submission_models import ApplicationRevision
from app.companies.models import Company
from app.processing.models import Offer
from app.products.calculations import payment_terms_from_legacy_offer
from app.products.schemas import PaymentTerms

OUTCOMES = ('accepted', 'declined', 'superseded', 'no_response', 'awaiting_response', 'not_viewed')
CHANGES = ('amount_only', 'term_only', 'amount_and_term', 'unchanged')
STEPS = ('terms', 'finances', 'documents', 'review', 'not_observed')
REASONS = ('insufficient_amount', 'high_payment', 'unsuitable_term', 'no_longer_needed', 'other', None)
MOSCOW = ZoneInfo('Europe/Moscow')


def metadata(date_from: date | None, date_to: date | None, product_code, now: datetime) -> ReportMetadata:
    end = date_to or now.astimezone(MOSCOW).date()
    start = date_from or end - timedelta(days=29)
    if start > end or (end - start).days >= 366:
        raise HTTPException(422, {'code': 'invalid_period', 'message': 'Выберите период от 1 до 366 дней'})
    return ReportMetadata(date_from=start, date_to=end, generated_at=now,
                          outcomes_as_of=now, product_code=product_code)


def bounds(meta: ReportMetadata):
    start = datetime.combine(meta.date_from, time.min, MOSCOW).astimezone(timezone.utc)
    end = datetime.combine(meta.date_to, time.max, MOSCOW).astimezone(timezone.utc)
    return start, end


def share(count: int, base: int) -> float | None:
    return count / base if base else None


def stages(keys, values):
    return [FunnelStage(key=key, count=count, base_from_first=values[0],
                        base_from_previous=values[index - 1] if index else values[0],
                        share_from_first=share(count, values[0]),
                        share_from_previous=share(count, values[index - 1] if index else values[0]))
            for index, (key, count) in enumerate(zip(keys, values))]


def observations(count: int, base: int):
    return dict(count=count, base=base, share=share(count, base))


def form_cohort(meta: ReportMetadata):
    start, end = bounds(meta)
    sent = select(ApplicationRevision.id).where(
        ApplicationRevision.application_id == AnalyticsJourney.application_id).exists()
    query = select(AnalyticsJourney.id, AnalyticsJourney.application_id, sent.label('submitted')).outerjoin(
        Application, Application.id == AnalyticsJourney.application_id).where(
        AnalyticsJourney.created_at >= start, AnalyticsJourney.created_at <= end,
        AnalyticsJourney.created_at <= meta.generated_at)
    if meta.product_code:
        query = query.where(func.coalesce(Application.product_code, AnalyticsJourney.product_code) == meta.product_code)
    return query.cte('form_cohort')


def offer_cohort(meta: ReportMetadata):
    start, end = bounds(meta)
    query = select(Offer.id, Offer.application_id, Offer.revision_id, Offer.product_code, Offer.created_at,
                   Offer.status, Offer.responded_at, Offer.decline_reason, Offer.amount_kopecks, Offer.term_months,
                   ApplicationRevision.snapshot['application']['amount_kopecks'].astext.cast(BigInteger).label('original_amount'),
                   ApplicationRevision.snapshot['application']['term_months'].as_integer().label('original_term')).join(
        ApplicationRevision, ApplicationRevision.id == Offer.revision_id).where(
        Offer.created_at >= start, Offer.created_at <= end, Offer.created_at <= meta.generated_at)
    if meta.product_code:
        query = query.where(Offer.product_code == meta.product_code)
    issued = query.cte('issued')
    # Только события предложений выбранной когорты, включая наблюдения после её периода.
    views = select(AnalyticsEvent.offer_id, func.min(AnalyticsEvent.created_at).label('first_viewed_at')).join(
        issued, issued.c.id == AnalyticsEvent.offer_id).where(
        AnalyticsEvent.kind == 'offer_viewed', AnalyticsEvent.created_at <= meta.generated_at).group_by(
        AnalyticsEvent.offer_id).cte('first_views')
    first = views.c.first_viewed_at
    outcome = case(
        (issued.c.status != 'active', issued.c.status),
        (first.is_(None), 'not_viewed'),
        (first <= meta.generated_at - timedelta(hours=72), 'no_response'),
        else_='awaiting_response')
    change = case(
        ((issued.c.amount_kopecks != issued.c.original_amount) & (issued.c.term_months != issued.c.original_term), 'amount_and_term'),
        (issued.c.amount_kopecks != issued.c.original_amount, 'amount_only'),
        (issued.c.term_months != issued.c.original_term, 'term_only'), else_='unchanged')
    return select(issued, first, outcome.label('outcome'), change.label('change')).outerjoin(
        views, views.c.offer_id == issued.c.id).cte('offer_facts')


def summary(db: Session, meta: ReportMetadata) -> AnalyticsSummary:
    forms = form_cohort(meta)
    total, saved, submitted = db.execute(select(func.count(),
        func.count().filter(forms.c.application_id.is_not(None)),
        func.count().filter(forms.c.submitted)).select_from(forms)).one()
    # Одинаковое время разрешается UUID события; история вне выбранных попыток не загружается.
    ranked = select(AnalyticsEvent.journey_id, AnalyticsEvent.payload['step'].as_string().label('step'),
                    func.row_number().over(partition_by=AnalyticsEvent.journey_id,
                        order_by=(AnalyticsEvent.created_at.desc(), AnalyticsEvent.event_id.desc())).label('position')).join(
        forms, forms.c.id == AnalyticsEvent.journey_id).where(
        AnalyticsEvent.kind == 'form_step_viewed', AnalyticsEvent.created_at <= meta.generated_at).cte('ranked_steps')
    step = func.coalesce(ranked.c.step, 'not_observed')
    last_counts = dict(db.execute(select(step, func.count()).select_from(forms).outerjoin(
        ranked, (ranked.c.journey_id == forms.c.id) & (ranked.c.position == 1)).where(
        ~forms.c.submitted).group_by(step)).all())
    facts = offer_cohort(meta)
    answered = facts.c.status.in_(('accepted', 'declined'))
    prior = answered & facts.c.responded_at.is_not(None) & (facts.c.first_viewed_at <= facts.c.responded_at)
    issued, viewed, responded, accepted, declined, unknown, without_view, late_view = db.execute(select(
        func.count(), func.count().filter(facts.c.first_viewed_at.is_not(None)), func.count().filter(prior),
        func.count().filter(prior & (facts.c.status == 'accepted')),
        func.count().filter(prior & (facts.c.status == 'declined')),
        func.count().filter(answered & facts.c.responded_at.is_(None)),
        func.count().filter(answered & facts.c.responded_at.is_not(None) & facts.c.first_viewed_at.is_(None)),
        func.count().filter(answered & facts.c.responded_at.is_not(None) & (facts.c.first_viewed_at > facts.c.responded_at)),
    ).select_from(facts)).one()
    outcome_counts = dict(db.execute(select(facts.c.outcome, func.count()).group_by(facts.c.outcome)).all())
    reason_counts = dict(db.execute(select(facts.c.decline_reason, func.count()).where(
        facts.c.status == 'declined').group_by(facts.c.decline_reason)).all())
    groups = {change: (count, accepted_count) for change, count, accepted_count in db.execute(select(
        facts.c.change, func.count(), func.count().filter(facts.c.status == 'accepted')).group_by(facts.c.change))}
    return AnalyticsSummary(
        metadata=meta, form_funnel=stages(('opened', 'draft_saved', 'submitted'), (total, saved, submitted)),
        offer_funnel=stages(('issued', 'viewed', 'responded', 'accepted'), (issued, viewed, responded, accepted)),
        last_steps=[LastStepCount(step=key, **observations(last_counts.get(key, 0), total - submitted)) for key in STEPS],
        offer_outcomes=[OfferOutcomeCount(outcome=key, **observations(outcome_counts.get(key, 0), issued)) for key in OUTCOMES],
        declined_after_view=ObservationCount(**observations(declined, viewed)),
        response_coverage=ResponseCoverage(responses_without_prior_view=unknown + without_view + late_view,
            response_without_registered_view=without_view, response_viewed_after_response=late_view, response_time_unknown=unknown),
        decline_reasons=[DeclineReasonCount(reason=key, **observations(reason_counts.get(key, 0),
                         outcome_counts.get('declined', 0))) for key in REASONS],
        condition_changes=[ConditionChangeCount(change=key, count=groups.get(key, (0, 0))[0],
            accepted=groups.get(key, (0, 0))[1], acceptance_share=share(groups.get(key, (0, 0))[1],
            groups.get(key, (0, 0))[0])) for key in CHANGES])


def counteroffers(db: Session, meta: ReportMetadata, outcome, page: int, page_size: int) -> CounterofferPage:
    facts = offer_cohort(meta)
    conditions = [facts.c.outcome == outcome] if outcome else []
    total = db.scalar(select(func.count()).select_from(facts).where(*conditions))
    # Снимки и условия считываются только для ограниченной страницы, одним пакетным запросом.
    rows = db.execute(select(Offer, facts.c.original_amount, facts.c.original_term,
                             facts.c.first_viewed_at, facts.c.outcome, Company.name).join(
        facts, facts.c.id == Offer.id).join(Application, Application.id == Offer.application_id).join(
        Company, Company.id == Application.company_id).where(*conditions).order_by(
        Offer.created_at.desc(), Offer.id.desc()).offset((page - 1) * page_size).limit(page_size))
    items = []
    for offer, original_amount, original_term, first_viewed, result, company_name in rows:
        terms = PaymentTerms.model_validate(offer.payment_terms) if offer.payment_terms else payment_terms_from_legacy_offer(offer)
        delta = offer.amount_kopecks - original_amount
        items.append(CounterofferRow(id=offer.id, application_id=offer.application_id, revision_id=offer.revision_id,
            company_name=company_name, product_code=offer.product_code, created_at=offer.created_at,
            original_amount_kopecks=original_amount, original_term_months=original_term,
            # В revision сохранён запрос, а не рассчитанный по нему договорный платёж.
            original_monthly_payment_kopecks=None, amount_kopecks=offer.amount_kopecks,
            term_months=offer.term_months, payment_terms=terms, amount_delta_kopecks=delta,
            amount_delta_rubles=format(Decimal(delta) / 100, '.2f'),
            amount_delta_percent=float(Decimal(delta) * 100 / original_amount) if original_amount else None,
            term_delta_months=offer.term_months - original_term, first_viewed_at=first_viewed,
            responded_at=offer.responded_at, outcome=result, decline_reason=offer.decline_reason))
    return CounterofferPage(metadata=meta, items=items, total=total, page=page, page_size=page_size)
