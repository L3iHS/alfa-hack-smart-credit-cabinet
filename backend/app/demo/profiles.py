import calendar
from datetime import date

SOURCE_VERSION = 'demo-profiles-v1'
PROFILE_INNS = {letter: f'99000000010{index}' for index, letter in enumerate('abcde', 1)}
_RECOMMENDATION_PROFILES = {
    '990000000001': dict(client_type='OOO', okved='10.71', tax_regime='USN', egrul_status='active',
                         mass_address_flag=False, director_disqualified_flag=False,
                         credit_history_score=620, overdue_days=0),
    '990000000002': dict(client_type='OOO', okved='33.12', tax_regime='USN', egrul_status='active',
                         mass_address_flag=False, director_disqualified_flag=False,
                         credit_history_score=600, overdue_days=0),
    PROFILE_INNS['a']: dict(client_type='OOO', okved='10.71', tax_regime='USN', egrul_status='active',
                            mass_address_flag=False, director_disqualified_flag=False,
                            credit_history_score=650, overdue_days=0),
    PROFILE_INNS['b']: dict(client_type='OOO', okved='46.90', tax_regime='OSNO', egrul_status='active',
                            mass_address_flag=False, director_disqualified_flag=False,
                            credit_history_score=700, overdue_days=0),
    PROFILE_INNS['c']: dict(client_type='OOO', okved='10.71', tax_regime='USN', egrul_status='active',
                            mass_address_flag=False, director_disqualified_flag=False,
                            credit_history_score=600, overdue_days=0),
    PROFILE_INNS['d']: dict(client_type='IP', okved='47.11', tax_regime='USN', egrul_status='active',
                            mass_address_flag=False, director_disqualified_flag=False,
                            credit_history_score=520, overdue_days=0),
    PROFILE_INNS['e']: dict(client_type='OOO', okved='46.90', tax_regime='OSNO', egrul_status='active',
                            mass_address_flag=False, director_disqualified_flag=False,
                            credit_history_score=450, overdue_days=100),
}


def recommendation_profile(inn: str) -> dict:
    """Детерминированный мок ЕГРЮЛ/БКИ для подбора продукта."""
    if inn in _RECOMMENDATION_PROFILES:
        data = dict(_RECOMMENDATION_PROFILES[inn])
    else:
        data = dict(client_type='OOO' if len(inn) == 10 else 'IP', okved=None, tax_regime=None,
                    egrul_status='active', mass_address_flag=False,
                    director_disqualified_flag=False, credit_history_score=None,
                    overdue_days=None)
    data['max_overdue_days'] = data['overdue_days']
    return data


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
