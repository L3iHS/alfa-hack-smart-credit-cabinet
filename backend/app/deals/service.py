import hashlib
import html
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text

from app.applications.models import ApplicationEvent
from app.applications.service import application_output, get_application, require_client
from app.applications.submission_models import IdempotencyRecord, ProcessingRun
from app.deals.models import Deal
from app.deals.schemas import DealOutput
from app.processing.models import Calculation, Decision, Offer
from app.processing.service import latest_revision, require_staff
from app.products.calculations import payment_terms_from_legacy_offer
from app.products.catalog import get_product
from app.products.schemas import PaymentTerms

COMPLETION_KINDS = {'working_capital': 'credit', 'equipment': 'credit', 'investment': 'credit',
                    'overdraft': 'limit', 'credit_line': 'limit', 'tender_guarantee': 'guarantee'}
PAYMENT_KINDS = {'credit': 'annuity', 'limit': 'revolving', 'guarantee': 'guarantee'}
COMPLETION_TEXT = {'credit': 'Кредит выдан', 'limit': 'Лимит открыт', 'guarantee': 'Гарантия выпущена'}
DEMO_NOTE = ('Это демонстрационная фиксация оформления: юридическое подписание договора, '
             'банковский перевод и реальный выпуск гарантии не выполняются.')


def conflict(message='Оформление изменилось или действие недоступно. Обновите заявку'):
    raise HTTPException(409, {'code': 'deal_conflict', 'message': message})


def get_deal(db, application_id):
    return db.scalar(select(Deal).where(Deal.application_id == application_id))


def deal_output(deal, user):
    result = DealOutput.model_validate(deal)
    if deal.status in ('prepared', 'confirmed'):
        if deal.status == 'prepared' and user.role == 'client':
            result.available_actions.append('confirm_deal')
        if deal.status == 'confirmed' and user.role == 'staff':
            result.available_actions.append('complete_deal')
        result.available_actions.append('cancel_deal')
    return result


def saved_terms(data, code, amount, term):
    """Проверяет сохранённый снимок; формулы и текущие тарифы здесь не вызываются."""
    try:
        result = PaymentTerms.model_validate(data)
    except (ValidationError, TypeError):
        conflict('Полные согласованные условия не сохранены; подготовка оформления невозможна')
    values = result.model_dump()
    integers = [value for name, value in values.items() if name.endswith(('_kopecks', '_bps')) and value is not None]
    if (any(type(value) is not int or value < 0 or value > 9_007_199_254_740_991 for value in integers)
            or any(type(data.get(name)) is not int for name in values
                   if name.endswith(('_kopecks', '_bps')) and values[name] is not None)
            or type(amount) is not int or type(term) is not int or amount <= 0 or term <= 0
            or result.amount_kopecks != amount or result.term_months != term
            or type(data.get('term_months')) is not int
            or code not in COMPLETION_KINDS
            or result.payment_kind != PAYMENT_KINDS[COMPLETION_KINDS[code]]):
        conflict('Сохранённые условия не соответствуют одобренной заявке')
    return result.model_dump(mode='json')


def prepare_snapshot(db, application):
    revision = latest_revision(db, application.id)
    decision = db.scalar(select(Decision).where(Decision.application_id == application.id)
                         .order_by(Decision.application_version.desc(), Decision.created_at.desc()).limit(1))
    if (revision is None or decision is None or decision.outcome != 'approved'
            or decision.revision_id != revision.id or decision.application_version != application.version):
        conflict('Актуальное одобрение отправленной версии не найдено')
    run = db.scalar(select(ProcessingRun).where(ProcessingRun.revision_id == revision.id))
    if (run is None or run.application_id != application.id or run.status != 'succeeded'
            or run.policy_version != decision.policy_version
            or decision.run_id is not None and decision.run_id != run.id):
        conflict('Сохранённое рассмотрение не соответствует кредитному решению')
    snapshot = revision.snapshot
    values = snapshot.get('application', {})
    code = values.get('product_code')
    company = snapshot.get('company', {})
    if (code != application.product_code or str(company.get('id')) != str(application.company_id)
            or not isinstance(company.get('name'), str) or not company['name'].strip()):
        conflict('Отправленная версия не содержит достоверных сведений о продукте и компании')
    offer = None
    accepted = list(db.scalars(select(Offer).where(Offer.application_id == application.id,
                    Offer.revision_id == revision.id, Offer.status == 'accepted')))
    if 'offer_accepted' in decision.public_reason_codes:
        if len(accepted) != 1:
            conflict('Принятые условия не найдены однозначно')
        offer = accepted[0]
        # До 0008 время ответа не сохранялось. Связь доказывают редакция,
        # единственное принятое предложение и следующая версия решения.
        if (offer.product_code != code
                or offer.application_version != decision.application_version - 1):
            conflict('Принятое предложение не соответствует кредитному решению')
        # Старые demo-v1 предложения содержат полный аннуитет в отдельных колонках.
        if offer.payment_terms is None:
            if run.catalog_version != 'demo-v1' or code not in ('working_capital', 'equipment'):
                conflict('Полные условия принятого предложения не сохранены')
            data = payment_terms_from_legacy_offer(offer).model_dump(mode='json')
        else:
            data = offer.payment_terms
        amount, term = offer.amount_kopecks, offer.term_months
        terms = saved_terms(data, code, amount, term)
        if ((terms['annual_rate_bps'] or 0) != offer.annual_rate_bps
                or (terms['monthly_payment_kopecks'] or 0) != offer.monthly_payment_kopecks
                or terms['total_payment_kopecks'] != offer.total_payment_kopecks
                or decision.payment_terms is not None and decision.payment_terms != terms):
            conflict('Сохранённые условия принятого предложения расходятся с решением')
    else:
        if accepted:
            conflict('История принятия предложения не соответствует решению')
        amount, term = values.get('amount_kopecks'), values.get('term_months')
        data = decision.payment_terms
        if data is None:
            calculation = db.scalar(select(Calculation).where(Calculation.run_id == run.id,
                                                               Calculation.revision_id == revision.id))
            if calculation is None or calculation.data.get('policy_version') != decision.policy_version:
                conflict('Согласованные условия нельзя восстановить из сохранённого расчёта')
            data = calculation.data.get('payment_terms')
        terms = saved_terms(data, code, amount, term)
    try:
        # Из версии каталога берём только название; суммы и ставка уже сохранены.
        product = get_product(code, run.catalog_version)
    except ValueError:
        conflict('Название продукта отправленной версии недоступно')
    return Deal(application_id=application.id, revision_id=revision.id, decision_id=decision.id,
                offer_id=offer.id if offer else None, company_id=application.company_id,
                company_snapshot=company, reference=f'СД-{application.number:06d}',
                product_code=code, product_name=product.name, completion_kind=COMPLETION_KINDS[code],
                amount_kopecks=amount, term_months=term, payment_terms=terms, status='prepared')


def execute(db, user, application_id, body, key, action):
    if action in ('prepare', 'complete'):
        require_staff(user)
    elif action == 'confirm':
        require_client(user)
    elif user.role not in ('client', 'staff'):
        raise HTTPException(403, {'code': 'operation_forbidden', 'message': 'Операция недоступна'})
    # Проверка доступа предшествует даже поиску сохранённого ответа.
    get_application(db, user, application_id)
    operation = f'deal_{action}'
    fingerprint = hashlib.sha256(json.dumps({'application_id': str(application_id), **body.model_dump(mode='json')},
                               sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    lock_key = int.from_bytes(hashlib.sha256(f'{user.id}:{operation}:{key}'.encode()).digest()[:8], signed=True)
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
    previous = db.get(IdempotencyRecord, (user.id, operation, key))
    if previous:
        if previous.fingerprint != fingerprint:
            raise HTTPException(409, {'code': 'idempotency_conflict', 'message': 'Ключ уже использован с другими данными'})
        return previous.response
    # Общая блокировка с рассмотрением, отзывом и изменением рабочей копии.
    application = get_application(db, user, application_id, lock=True)
    if application.version != body.expected_version or application.status != 'approved':
        conflict()
    deal = get_deal(db, application.id)
    stamp = datetime.now(timezone.utc)
    if action == 'prepare':
        if deal is not None:
            conflict('Оформление по этой заявке уже подготовлено')
        deal = prepare_snapshot(db, application)
        db.add(deal)
        event_type = 'deal_prepared'
    else:
        if deal is None or deal.company_id != application.company_id:
            conflict('Оформление по заявке не найдено')
        if action == 'confirm' and deal.status == 'prepared':
            deal.status, deal.confirmed_at = 'confirmed', stamp
            event_type = 'deal_confirmed'
        elif action == 'complete' and deal.status == 'confirmed':
            deal.status, deal.completed_at = 'completed', stamp
            event_type = 'deal_completed'
        elif action == 'cancel' and deal.status in ('prepared', 'confirmed'):
            deal.status, deal.cancelled_at, deal.cancel_reason = 'cancelled', stamp, body.reason
            event_type = 'deal_cancelled'
        else:
            conflict()
    application.version += 1
    application.updated_at = stamp
    db.add(ApplicationEvent(application_id=application.id, revision_id=deal.revision_id,
                            actor_id=user.id, actor_type='user', event_type=event_type,
                            application_version=application.version))
    db.flush()
    result = application_output(application, user).model_dump(mode='json')
    db.add(IdempotencyRecord(user_id=user.id, operation=operation, key=key,
                            fingerprint=fingerprint, response=result))
    db.commit()
    return result


def markdown_text(value):
    # Свободный текст не может добавлять Markdown/HTML, ссылки и новые блоки.
    value = html.escape(' '.join(str(value).split()), quote=True)
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~\-])', r'\\\1', value)


def money(value):
    if value is None:
        return 'Не применяется'
    return f'{Decimal(value) / 100:,.2f}'.replace(',', ' ').replace('.', ',') + ' ₽'


def document(db, user, application_id):
    application = get_application(db, user, application_id)
    deal = get_deal(db, application.id)
    if deal is None:
        raise HTTPException(404, {'code': 'deal_not_found', 'message': 'Условия сделки ещё не подготовлены'})
    status = {'prepared': 'Условия подготовлены', 'confirmed': 'Условия подтверждены клиентом',
              'completed': COMPLETION_TEXT[deal.completion_kind], 'cancelled': 'Оформление отменено'}[deal.status]
    terms = deal.payment_terms
    lines = ['# Условия сделки', '', f'Номер сделки: {deal.reference}',
             f'Номер заявки: {application.display_number}',
             f'Компания: {markdown_text(deal.company_snapshot["name"])}',
             f'ИНН: {markdown_text(deal.company_snapshot.get("inn", "Не указан"))}',
             f'Продукт: {markdown_text(deal.product_name)}', f'Состояние: {status}', '',
             f'Сумма: {money(deal.amount_kopecks)}', f'Срок: {deal.term_months} мес.',
             'Вид платежа: ' + {'annuity': 'Аннуитет', 'revolving': 'Возобновляемый лимит', 'guarantee': 'Комиссия за гарантию'}[terms['payment_kind']],
             f'Годовая ставка: {"Не применяется" if terms["annual_rate_bps"] is None else str(Decimal(terms["annual_rate_bps"]) / 100).replace(".", ",") + "%"}',
             f'Годовая комиссия: {str(Decimal(terms["annual_commission_bps"]) / 100).replace(".", ",")}%']
    labels = {'monthly_payment_kopecks': 'Ежемесячный платёж', 'upfront_fee_kopecks': 'Разовая комиссия',
              'principal_due_at_end_kopecks': 'Основной долг к возврату в конце срока', 'last_payment_kopecks': 'Последний платёж',
              'total_payment_kopecks': 'Общая сумма платежей', 'total_cost_kopecks': 'Стоимость финансирования',
              'assessment_monthly_burden_kopecks': 'Расчётная месячная нагрузка', 'contingent_liability_kopecks': 'Условное обязательство по гарантии'}
    lines.extend(f'{label}: {money(terms[key])}' for key, label in labels.items())
    lines.extend(['', '## Допущения расчёта', ''])
    lines.extend(f'- {markdown_text(item)}' for item in terms['assumptions'])
    lines.extend(['', '## История оформления', ''])
    for name, label in (('created_at', 'Подготовлено'), ('confirmed_at', 'Подтверждено клиентом'),
                        ('completed_at', 'Завершено сотрудником'), ('cancelled_at', 'Отменено')):
        value = getattr(deal, name)
        if value:
            lines.append(f'{label}: {value.astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M МСК")}')
    if deal.cancel_reason:
        lines.append(f'Причина отмены: {markdown_text(deal.cancel_reason)}')
    lines.extend(['', DEMO_NOTE, ''])
    return '\n\n'.join(lines), f'deal-{application.number:06d}.md'
