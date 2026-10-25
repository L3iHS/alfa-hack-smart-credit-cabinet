from decimal import Decimal

from app.assistant.schemas import Source
from app.assistant.presentation import _decimal_text
from app.products.catalog import get_catalog

DOCUMENTS = {
    'financial_statement': ('Финансовая отчётность', 'Финансовая отчётность подтверждает введённые финансовые сведения за выбранный период.'),
    'equipment_invoice': ('Счёт на оборудование', 'Счёт на оборудование описывает приобретаемое оборудование и стоимость покупки.'),
    'bank_statement': ('Банковская выписка', 'Банковская выписка показывает движение денежных средств по счёту компании.'),
    'business_plan': ('Бизнес-план', 'Бизнес-план описывает инвестиционный проект и планируемое развитие компании.'),
    'tender_document': ('Документ тендера', 'Документ тендера содержит сведения об обязательствах перед заказчиком.'),
}
STATUS_TEXT = {
    'draft': ('Черновик', 'Заполните сведения, приложите документы, проверьте сводку и подтвердите согласия перед отправкой заявки.'),
    'submitted': ('Заявка отправлена', 'Заявка отправлена на рассмотрение. Следите за состоянием в кабинете; повторная отправка не требуется.'),
    'processing': ('Обработка', 'Выполняются проверки заявки. Дождитесь результата; техническая ошибка не означает отказ в кредите.'),
    'needs_info': ('Нужны уточнения', 'Прочитайте открытый запрос уточнений, дополните сведения или документы и явно отправьте ответ через кабинет.'),
    'manual_review': ('Рассмотрение сотрудником', 'Заявку рассматривает сотрудник банка. Он может запросить уточнения, предложить условия или принять решение.'),
    'counteroffer': ('Предложены другие условия', 'Ознакомьтесь с действующим предложением: суммой, сроком и платежами. Его можно принять или отклонить в кабинете.'),
    'approved': ('Одобрено', 'Заявка одобрена. Одобрение в кабинете не означает фактический перевод денег или подписание договора.'),
    'rejected': ('Отказ', 'По заявке принято отрицательное решение. Посмотрите доступные публичные причины результата в карточке заявки.'),
    'withdrawn': ('Отозвана', 'Заявка отозвана клиентом. Рассмотрение прекращено. Прежние запросы уточнений сохраняются в истории и не требуют ответа или загрузки документов.'),
}
TERMS = {
    'annuity': ('Аннуитет', 'Аннуитет — способ погашения кредита регулярными платежами. Платёж включает основной долг и проценты; итоговые суммы берутся из расчёта кабинета.'),
    'overdraft': ('Что такое овердрафт', 'Овердрафт помогает покрыть короткий кассовый разрыв: оплатить расходы до поступления выручки. Допустимые условия смотрите в выбранном каталоге.'),
    'credit_line': ('Что такое кредитная линия', 'Кредитная линия — возобновляемый лимит для повторяющихся текущих потребностей бизнеса. Расчёт использует указанные в кабинете допущения.'),
    'guarantee': ('Что такое гарантия', 'Тендерная гарантия обеспечивает обязательства перед заказчиком. Это условное обязательство банка, а не перечисление суммы кредита клиенту.'),
    'financial_period': ('Финансовый период', 'Финансовый период состоит из полных завершённых месяцев. Выручку, операционные расходы и текущие кредитные платежи указывают за один и тот же период.'),
}
PROCESS = {
    'submission': ('Отправка заявки', 'Сохранение черновика не запускает рассмотрение. Перед отправкой клиент проверяет сводку, подтверждает данные и согласие на проверку кредитной истории.'),
    'attachments': ('Загрузка документов', 'Документы прикладываются к заявке как файлы. Загрузка файла не извлекает автоматически выручку и расходы: финансовые показатели вводятся в форму.'),
    'decision': ('Скоринг и решение', 'Скоринг оценивает риск, а кредитное решение принимают правила или сотрудник банка. Помощник объясняет доступные факты и не обещает одобрение.'),
    'access': ('Доступ к заявке', 'Клиент видит заявки только своей компании. Сотрудник видит отправленные заявки. Внутренние оценки не доступны клиенту через справочного помощника.'),
}


def build_knowledge(catalog_version: str) -> list[Source]:
    catalog = get_catalog(catalog_version)
    sources = [Source(id='catalog:products', title='Состав версии каталога продуктов',
        text='Полный перечень продуктов этой версии каталога: ' +
            ', '.join(product.name for product in catalog.values()) +
            '. Продукты вне этого перечня в данной версии отсутствуют.', version=catalog_version)]
    for product in catalog.values():
        documents = ', '.join(DOCUMENTS[kind][0] for kind in product.required_document_types)
        payment = {'annuity': 'равные ежемесячные платежи',
                   'revolving': 'лимит с возвратом основного долга в конце срока',
                   'guarantee': 'комиссия за гарантию'}[product.payment_kind]
        text = (f'{product.name}. {product.purpose_description}. Демонстрационные условия каталога. '
                f'Сумма от {_decimal_text(Decimal(product.min_amount_kopecks) / 100, grouping=True)} '
                f'до {_decimal_text(Decimal(product.max_amount_kopecks) / 100, grouping=True)} ₽. '
                f'Срок от {product.min_term_months} до {product.max_term_months} месяцев. '
                f'Документы: {documents}. Вид платежа: {payment}. ')
        if product.annual_rate_bps is not None:
            text += f'Годовая ставка {product.annual_rate_bps / 100:g}%. '
        if product.upfront_fee_bps:
            text += f'Разовая комиссия {product.upfront_fee_bps / 100:g}%. '
        if product.annual_commission_bps:
            text += f'Годовая комиссия {product.annual_commission_bps / 100:g}%. '
        if product.required_application_fields:
            field_labels = {'project_description': 'описание проекта', 'tender_number': 'номер тендера',
                            'beneficiary_name': 'заказчик по тендеру'}
            text += 'Дополнительные сведения: ' + ', '.join(field_labels[field] for field in product.required_application_fields) + '.'
        sources.append(Source(id=f'product:{product.code}', title=product.name, text=text, version=catalog_version))
    used_documents = {kind for product in catalog.values() for kind in product.required_document_types}
    for prefix, entries in (('document', {key: DOCUMENTS[key] for key in sorted(used_documents)}),
                            ('status', STATUS_TEXT), ('term', TERMS), ('process', PROCESS)):
        sources.extend(Source(id=f'{prefix}:{key}', title=title, text=text, version=catalog_version)
                       for key, (title, text) in entries.items())
    return sources
