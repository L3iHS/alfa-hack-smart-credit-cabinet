"""Контекст компании и исходных финансов для предварительного подбора."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RecommendationContext:
    values: Mapping[str, Any]

    def get(self, name: str, default=None):
        return self.values.get(name, default)
