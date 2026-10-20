from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import get_current_user
from app.companies.models import Company
from app.companies.schemas import CompanyOutput
from app.core.db import get_db

router = APIRouter(tags=['Компания'])


@router.get('/company', response_model=CompanyOutput)
def company(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != 'client' or user.company_id is None:
        raise HTTPException(403, {'code': 'company_unavailable', 'message': 'Профиль компании доступен клиенту'})
    return db.get(Company, user.company_id)
