import calendar
from datetime import date

SOURCE_VERSION = 'demo-profiles-v1'
PROFILE_INNS = {letter: f'99000000010{index}' for index, letter in enumerate('abcde', 1)}


def months_before(today: date, months: int) -> date:
    index = today.year*12 + today.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month+1, min(today.day, calendar.monthrange(year, month+1)[1]))


def company_profiles(today: date | None = None) -> list[dict]:
    today = today or date.today()
    names = {'a':'Пекарня', 'b':'Торговля', 'c':'Уточнение', 'd':'Новый бизнес', 'e':'Просрочка'}
    return [dict(inn=inn, name=f'Синтетический профиль {letter.upper()} — {names[letter]}', industry='Демонстрационный бизнес',
                 registered_at=months_before(today, 4 if letter == 'd' else 24)) for letter, inn in PROFILE_INNS.items()]


def application_fields(profile: str, today: date | None = None) -> dict:
    today = today or date.today()
    start = months_before(today.replace(day=1), 3)
    end = months_before(today.replace(day=1), 1)
    end = end.replace(day=calendar.monthrange(end.year, end.month)[1])
    equipment = profile in 'ace'
    revenue, expenses, debt = (80000000,50000000,5000000)
    if profile == 'b':
        revenue, debt = 70000000,3000000
    elif profile == 'c':
        revenue = 70000000
    elif profile == 'd':
        revenue, expenses, debt = 40000000,30000000,1000000
    return dict(product_code='equipment' if equipment else 'working_capital', purpose='Синтетическая демонстрационная заявка',
                amount_kopecks=200000000 if equipment else (500000000 if profile == 'b' else 50000000),
                term_months=24 if equipment else 12, period_start=start.isoformat(), period_end=end.isoformat(),
                revenue_kopecks=revenue*3, operating_expenses_kopecks=expenses*3, existing_debt_payments_kopecks=debt*3)
