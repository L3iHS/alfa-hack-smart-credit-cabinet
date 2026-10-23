"""Неизменный каталог обучающего и признакового контракта первой модели."""
from types import MappingProxyType

from app.products.catalog import get_catalog

ML_CATALOG_VERSION = 'demo-v1'
ML_PRODUCTS = MappingProxyType(get_catalog(ML_CATALOG_VERSION))
