"""Внутренние модели контекста и результатов правил."""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Mapping

from app.recommendations.config import Product, Rule

PASS = 'PASS'
FAIL_HARD = 'FAIL_HARD'
FAIL_ADJUSTABLE = 'FAIL_ADJUSTABLE'
MISSING_DATA = 'MISSING_DATA'
OUTCOME_OK = 'OK'
OUTCOME_COUNTER_OFFER = 'COUNTER_OFFER'
OUTCOME_REQUEST_DATA = 'REQUEST_DATA'
OUTCOME_ALTERNATIVE = 'ALTERNATIVE_PRODUCT'
OUTCOME_NO_MATCH = 'NO_MATCH'


@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    status: str
    actual: Any
    expected: Any


@dataclass(frozen=True)
class RecommendationContext:
    values: Mapping[str, Any]

    def get(self, name: str, default=None):
        return self.values.get(name, default)

    def with_terms(self, *, amount_rub: Decimal, term_months: int,
                   term_days: int | None = None) -> 'RecommendationContext':
        values = dict(self.values)
        values['amount'] = amount_rub
        values['amount_kopecks'] = int(amount_rub * 100)
        values['term_months'] = term_months
        values['term_days'] = term_months * 30 if term_days is None else term_days
        return RecommendationContext(values)


@dataclass(frozen=True)
class Evaluation:
    product: Product
    results: tuple[RuleResult, ...]
    outcome: str
    amount_rub: Decimal
    term_months: int
    term_days: int | None
    missing_fields: tuple[str, ...]
    messages: tuple[str, ...]
    next_actions: tuple[str, ...]

    @property
    def hard_failed(self) -> bool:
        return any(result.status == FAIL_HARD for result in self.results)

    @property
    def missing(self) -> bool:
        return any(result.status == MISSING_DATA for result in self.results)

    @property
    def adjustable(self) -> bool:
        return any(result.status == FAIL_ADJUSTABLE for result in self.results)

    def with_outcome(self, outcome: str, **changes) -> 'Evaluation':
        return replace(self, outcome=outcome, **changes)
