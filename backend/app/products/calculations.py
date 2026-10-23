from decimal import Decimal, ROUND_CEILING, localcontext
from typing import TYPE_CHECKING

from app.products.schemas import PaymentTerms, ProductOutput

if TYPE_CHECKING:
    from app.processing.models import Offer


def calculate_terms(product: ProductOutput, amount_kopecks: int, term_months: int) -> PaymentTerms:
    if (type(amount_kopecks) is not int or
            not product.min_amount_kopecks <= amount_kopecks <= product.max_amount_kopecks):
        raise ValueError('Сумма вне диапазона выбранного продукта')
    if (type(term_months) is not int or
            not product.min_term_months <= term_months <= product.max_term_months):
        raise ValueError('Срок вне диапазона выбранного продукта')
    with localcontext() as context:
        context.prec = 50
        amount = Decimal(amount_kopecks)
        fee = int((amount * product.upfront_fee_bps / 10000).to_integral_value(rounding=ROUND_CEILING))
        principal = liability = 0
        if product.payment_kind == 'guarantee':
            fee = int((amount * product.annual_commission_bps * term_months / 120000).to_integral_value(rounding=ROUND_CEILING))
            monthly = burden = None
            last = 0
            total = cost = fee
            liability = amount_kopecks
            assumptions = (
                'Гарантия не является выдачей кредита; комиссия уплачивается разово за весь срок.',
                'При исполнении гарантии может возникнуть обязанность возместить её сумму.',
                'Регулярный кредитный платёж и месячная нагрузка не рассчитываются.',
            )
        else:
            if product.annual_rate_bps is None:
                raise ValueError('Для кредитного продукта нужна процентная ставка')
            rate = Decimal(product.annual_rate_bps) / 120000
            if product.payment_kind == 'annuity':
                factor = (1 + rate) ** term_months
                value = amount / term_months if not rate else amount * rate * factor / (factor - 1)
                monthly = int(value.to_integral_value(rounding=ROUND_CEILING))
                last = monthly
                total = monthly * term_months + fee
                burden = monthly + fee
                assumptions = (
                    'Аннуитетный платёж округлён вверх до копейки; календарный график не моделируется.',
                    'Разовая комиссия целиком включена в нагрузку первого месяца.',
                )
            elif product.payment_kind == 'revolving':
                monthly = int((amount * rate).to_integral_value(rounding=ROUND_CEILING))
                principal = amount_kopecks
                last = principal + monthly
                total = principal + monthly * term_months + fee
                reserve = int((amount / term_months).to_integral_value(rounding=ROUND_CEILING))
                burden = monthly + reserve + fee
                assumptions = (
                    'Предполагается полное использование лимита в течение всего срока.',
                    'Ежемесячно уплачиваются проценты; весь лимит возвращается в конце срока.',
                    'Расчётный резерв возврата лимита не является договорным платежом или накопленными деньгами.',
                    'Разовая комиссия целиком включена в нагрузку первого месяца.',
                )
            else:
                raise ValueError('Неизвестный вид платежей')
            cost = total - amount_kopecks
        return PaymentTerms(
            payment_kind=product.payment_kind, amount_kopecks=amount_kopecks, term_months=term_months,
            annual_rate_bps=product.annual_rate_bps, annual_commission_bps=product.annual_commission_bps,
            monthly_payment_kopecks=monthly, upfront_fee_kopecks=fee,
            principal_due_at_end_kopecks=principal, last_payment_kopecks=last,
            total_payment_kopecks=total, total_cost_kopecks=cost,
            assessment_monthly_burden_kopecks=burden, contingent_liability_kopecks=liability,
            assumptions=assumptions,
        )


def payment_terms_from_legacy_offer(offer: 'Offer') -> PaymentTerms:
    """Представление старого аннуитета из сохранённых сумм без переоценки по каталогу."""
    return PaymentTerms(
        payment_kind='annuity', amount_kopecks=offer.amount_kopecks, term_months=offer.term_months,
        annual_rate_bps=offer.annual_rate_bps, annual_commission_bps=0,
        monthly_payment_kopecks=offer.monthly_payment_kopecks, upfront_fee_kopecks=0,
        principal_due_at_end_kopecks=0, last_payment_kopecks=offer.monthly_payment_kopecks,
        total_payment_kopecks=offer.total_payment_kopecks,
        total_cost_kopecks=offer.total_payment_kopecks - offer.amount_kopecks,
        assessment_monthly_burden_kopecks=offer.monthly_payment_kopecks,
        contingent_liability_kopecks=0,
        assumptions=('Исторические аннуитетные условия восстановлены из сохранённого предложения без пересчёта.',),
    )
