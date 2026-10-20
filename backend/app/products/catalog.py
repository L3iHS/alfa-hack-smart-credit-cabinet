from app.products.schemas import ProductOutput

CATALOG_VERSION = 'demo-v1'
PRODUCTS = {
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
}
