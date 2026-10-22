"""HTTP API подбора кредитных продуктов."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import get_current_user
from app.companies.models import Company
from app.core.db import get_db
from app.recommendations.config import RecommendationConfigError, load_config
from app.recommendations.engine import recommend
from app.recommendations.schemas import (
    OptionItem, OptionsOutput, PurposeOption, RecommendationRequest, RecommendationResponse,
)

router = APIRouter(tags=['Подбор продуктов'])
COLLATERAL_OPTIONS = (
    ('real_estate', 'Недвижимость'),
    ('equipment', 'Оборудование'),
    ('vehicle', 'Транспорт'),
    ('none', 'Без залога'),
)
URGENCY_OPTIONS = (('high', 'Срочно'), ('normal', 'В плановом порядке'))


def _company(user: User, db: Session, company_id: UUID | None) -> Company:
    if user.role == 'client':
        company = db.get(Company, user.company_id) if user.company_id else None
    else:
        if company_id is None:
            raise HTTPException(422, {'code': 'company_id_required',
                                      'message': 'Для сотрудника нужен company_id'})
        company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(404, {'code': 'company_not_found', 'message': 'Компания не найдена'})
    return company


@router.get('/product-recommendations/options', response_model=OptionsOutput)
def recommendation_options():
    config = load_config()
    return OptionsOutput(
        purposes=[PurposeOption(code=item.code, label=item.label) for item in config.purposes.values()],
        collateral_types=[OptionItem(code=code, label=label) for code, label in COLLATERAL_OPTIONS],
        urgency_levels=[OptionItem(code=code, label=label) for code, label in URGENCY_OPTIONS],
        config_version=config.version,
    )


@router.post('/product-recommendations', response_model=RecommendationResponse)
def product_recommendations(payload: RecommendationRequest,
                            company_id: UUID | None = Query(default=None),
                            user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    company = _company(user, db, company_id)
    try:
        return recommend(payload, company, role=user.role)
    except RecommendationConfigError as error:
        raise HTTPException(500, {'code': 'recommendation_config_error',
                                  'message': 'Конфигурация подбора временно недоступна'}) from error
    except ValueError as error:
        raise HTTPException(422, {'code': 'recommendation_input_error',
                                  'message': str(error)}) from error
