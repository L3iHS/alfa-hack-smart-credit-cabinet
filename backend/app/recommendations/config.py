"""Проверяемый YAML содержит ссылки, порядок подбора и тексты, без второго каталога."""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Annotated, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from app.products.catalog import CATALOG_VERSION, get_catalog
from app.recommendations.schemas import PurposeCode

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / 'config' / 'rules'
_FILE_NAMES = ('products.yaml', 'purpose_map.yaml', 'ranking.yaml', 'reasons.yaml')
_REASON_CODES = frozenset(('purpose_match', 'purpose_alternative', 'catalog_amount_adjusted',
    'financial_amount_adjusted', 'term_adjusted', 'amount_below_minimum', 'financial_no_match',
    'company_liquidated', 'overdue_90_plus', 'company_data_missing'))
Text = Annotated[str, Field(min_length=1, strict=True)]


class RecommendationConfigError(ValueError):
    """Конфигурация не соответствует исполняемому контракту."""


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)


class Purpose(ConfigModel):
    label: Text
    primary: list[Text] = Field(min_length=1)
    secondary: list[Text]


class Ranking(ConfigModel):
    show_top_n: Annotated[StrictInt, Field(ge=1, le=6)]
    amount_weight: float = Field(ge=0, le=1)
    term_weight: float = Field(ge=0, le=1)

    @model_validator(mode='after')
    def check_weights(self):
        if abs(self.amount_weight + self.term_weight - 1) > 1e-9:
            raise ValueError('Сумма весов близости суммы и срока должна равняться 1')
        return self


class ProductsFile(ConfigModel):
    config_version: Text
    products: list[Text] = Field(min_length=1)


class PurposesFile(ConfigModel):
    purposes: dict[PurposeCode, Purpose]


class RecommendationConfig(ConfigModel):
    version: str
    fingerprint: str
    products: tuple[str, ...]
    purposes: dict[str, Purpose]
    ranking: Ranking
    reasons: dict[str, str]

    def purpose(self, code: str) -> Purpose:
        try:
            return self.purposes[code]
        except KeyError as error:
            raise RecommendationConfigError(f'Неизвестная цель: {code}') from error


@lru_cache(maxsize=8)
def load_config(path: str | None = None) -> RecommendationConfig:
    """Проверяет структуру, ссылки, повторы и отсутствие неисполняемых настроек."""
    directory = Path(path) if path is not None else DEFAULT_RULES_PATH
    if {file.name for file in directory.glob('*.yaml')} != set(_FILE_NAMES):
        raise RecommendationConfigError('Нужны только поддерживаемые файлы конфигурации подбора')
    raw = {}
    digest = hashlib.sha256()
    try:
        for name in _FILE_NAMES:
            content = (directory / name).read_bytes()
            digest.update(name.encode())
            digest.update(content)
            raw[name] = yaml.safe_load(content.decode('utf-8'))
            if not isinstance(raw[name], dict):
                raise RecommendationConfigError(f'{name}: нужен объект YAML')
        products = ProductsFile.model_validate(raw['products.yaml'])
        purposes = PurposesFile.model_validate(raw['purpose_map.yaml']).purposes
        ranking = Ranking.model_validate(raw['ranking.yaml'])
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
        raise RecommendationConfigError('Не удалось прочитать конфигурацию подбора') from error
    catalog = get_catalog(CATALOG_VERSION)
    if len(products.products) != len(set(products.products)) or set(products.products) != set(catalog):
        raise RecommendationConfigError('Нужны уникальные ссылки на все продукты каталога')
    if set(purposes) != set(get_args(PurposeCode)):
        raise RecommendationConfigError('Нужны все поддерживаемые цели')
    for purpose in purposes.values():
        codes = purpose.primary + purpose.secondary
        if len(codes) != len(set(codes)) or not set(codes) <= set(products.products):
            raise RecommendationConfigError('Цель ссылается на неизвестный или повторный продукт')
        if 'tender_guarantee' in codes and codes != ['tender_guarantee']:
            raise RecommendationConfigError('Гарантия подбирается отдельно от кредитов')
    referenced = {code for purpose in purposes.values() for code in purpose.primary + purpose.secondary}
    if referenced != set(products.products):
        raise RecommendationConfigError('Каждому продукту нужна цель подбора')
    reasons = raw['reasons.yaml']
    if set(reasons) != _REASON_CODES or any(not isinstance(text, str) or not text.strip() for text in reasons.values()):
        raise RecommendationConfigError('Нужны все исполняемые тексты причин')
    return RecommendationConfig(version=products.config_version, fingerprint=digest.hexdigest(),
        products=tuple(products.products), purposes=purposes, ranking=ranking, reasons=reasons)
