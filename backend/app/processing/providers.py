from app.demo.profiles import PROFILE_INNS, SOURCE_VERSION
from app.processing.schemas import BkiData, RegistryData, TaxData


class UnsupportedVersion(ValueError):
    pass


def check(kind: str, snapshot: dict, version: str) -> dict:
    if version != SOURCE_VERSION:
        raise UnsupportedVersion('Версия синтетического источника не поддерживается')
    company = snapshot['company']
    if kind == 'registry':
        return RegistryData(registered_at=company['registered_at'], liquidated=False).model_dump()
    if kind == 'tax':
        expected = 80000000 if company['inn'] == PROFILE_INNS['c'] else None
        return TaxData(expected_monthly_revenue_kopecks=expected).model_dump()
    if kind == 'bki':
        return BkiData(overdue_days=100 if company['inn'] == PROFILE_INNS['e'] else 0).model_dump()
    raise ValueError('Неизвестный синтетический источник')
