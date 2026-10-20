from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import password_hash
from app.companies.models import Company
from app.core.config import settings
from app.core.db import SessionLocal
from app.demo.profiles import company_profiles


def seed(db: Session) -> None:
    companies = [
        {"inn": "990000000001", "name": "Демо Пекарня", "industry": "Производство продуктов", "registered_at": date(2019, 3, 15)},
        {"inn": "990000000002", "name": "Демо Мастерская", "industry": "Ремонт оборудования", "registered_at": date(2021, 6, 10)},
    ]
    companies.extend(company_profiles())
    company_ids = []
    for company in companies:
        db.execute(insert(Company).values(**company).on_conflict_do_nothing(index_elements=["inn"]))
        company_ids.append(db.scalar(select(Company.id).where(Company.inn == company["inn"])))
    users = [
        ("client1@example.test", "Представитель Демо Пекарни", "client", company_ids[0]),
        ("client2@example.test", "Представитель Демо Мастерской", "client", company_ids[1]),
        ("staff@example.test", "Демонстрационный сотрудник", "staff", None),
    ]
    users.extend((f'demo-{letter}@example.test', f'Синтетический профиль {letter.upper()}', 'client', company_ids[index+2]) for index, letter in enumerate('abcde'))
    for email, display_name, role, company_id in users:
        if db.scalar(select(User.id).where(User.email == email)) is None:
            db.execute(insert(User).values(
                email=email, display_name=display_name, role=role, company_id=company_id,
                password_hash=password_hash.hash(settings.demo_password),
            ).on_conflict_do_nothing(index_elements=["email"]))
    db.commit()


if __name__ == "__main__":
    with SessionLocal() as db:
        seed(db)
    print("Демонстрационные компании и учётные записи готовы")
