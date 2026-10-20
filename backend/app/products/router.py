from fastapi import APIRouter

from app.products.catalog import CATALOG_VERSION, PRODUCTS
from app.products.schemas import CatalogOutput

router = APIRouter(tags=['Продукты'])


@router.get('/products', response_model=CatalogOutput)
def products():
    return CatalogOutput(catalog_version=CATALOG_VERSION, items=list(PRODUCTS.values()))
