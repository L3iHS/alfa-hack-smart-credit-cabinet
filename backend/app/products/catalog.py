from types import MappingProxyType

from app.products.schemas import ProductOutput

CATALOG_VERSION = 'demo-v1'
_DEMO_V1 = MappingProxyType({
    'working_capital': ProductOutput(
        code='working_capital', name='Оборотный кредит',
        purpose_description='Закупка товара, сырья и финансирование текущей деятельности',
        min_amount_kopecks=10_000_000, max_amount_kopecks=500_000_000,
        min_term_months=3, max_term_months=24, annual_rate_bps=2400,
        required_document_types=('financial_statement',),
    ),
    'equipment': ProductOutput(
        code='equipment', name='Кредит на оборудование',
        purpose_description='Покупка оборудования для бизнеса',
        min_amount_kopecks=30_000_000, max_amount_kopecks=1_000_000_000,
        min_term_months=6, max_term_months=36, annual_rate_bps=2400,
        required_document_types=('financial_statement', 'equipment_invoice'),
    ),
})

_DEMO_V2 = MappingProxyType({
    **_DEMO_V1,
    'overdraft': ProductOutput(
        code='overdraft', name='Овердрафт',
        purpose_description='Покрытие краткосрочного кассового разрыва',
        min_amount_kopecks=10_000_000, max_amount_kopecks=300_000_000,
        min_term_months=1, max_term_months=3, annual_rate_bps=2100,
        payment_kind='revolving',
        required_document_types=('financial_statement', 'bank_statement'),
    ),
    'credit_line': ProductOutput(
        code='credit_line', name='Кредитная линия',
        purpose_description='Возобновляемый лимит для текущих потребностей бизнеса',
        min_amount_kopecks=50_000_000, max_amount_kopecks=1_500_000_000,
        min_term_months=6, max_term_months=24, annual_rate_bps=2000,
        payment_kind='revolving', upfront_fee_bps=50,
        required_document_types=('financial_statement', 'bank_statement'),
    ),
    'investment': ProductOutput(
        code='investment', name='Инвестиционный кредит',
        purpose_description='Финансирование долгосрочного развития бизнеса',
        min_amount_kopecks=300_000_000, max_amount_kopecks=10_000_000_000,
        min_term_months=24, max_term_months=120, annual_rate_bps=1600,
        upfront_fee_bps=150,
        required_document_types=('financial_statement', 'business_plan'),
        required_application_fields=('project_description',),
    ),
    'tender_guarantee': ProductOutput(
        code='tender_guarantee', name='Тендерная гарантия',
        purpose_description='Обеспечение обязательств перед заказчиком по тендеру',
        min_amount_kopecks=10_000_000, max_amount_kopecks=2_000_000_000,
        min_term_months=1, max_term_months=36, annual_rate_bps=None,
        payment_kind='guarantee', annual_commission_bps=300,
        required_document_types=('financial_statement', 'tender_document'),
        required_application_fields=('tender_number', 'beneficiary_name'),
    ),
})

_CATALOGS = MappingProxyType({'demo-v1': _DEMO_V1, 'demo-v2': _DEMO_V2})
PRODUCTS = _CATALOGS[CATALOG_VERSION]


def get_catalog(version: str) -> dict[str, ProductOutput]:
    try:
        return dict(_CATALOGS[version])
    except KeyError as exc:
        raise ValueError(f'Неизвестная версия каталога: {version}') from exc


def get_product(code: str, version: str) -> ProductOutput:
    catalog = get_catalog(version)
    try:
        return catalog[code]
    except KeyError as exc:
        raise ValueError(f'Продукт {code} отсутствует в каталоге {version}') from exc
