"""Structured quantitative evidence for the PALLAS-008 strategy boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictInt, StrictStr, model_validator
from typing_extensions import Self

from .base import CanonicalDecimal, FrozenValue


PALLAS_008_STRATEGY_ID = "PALLAS-008-A-SHARE-AUTONOMOUS-V1"
PALLAS_008_RANKING_METHOD = "PALLAS_008_QUANTITATIVE_EVIDENCE"
PALLAS_008_EVIDENCE_FIELDS = frozenset({
    "momentum_20",
    "momentum_60",
    "trend_strength",
    "liquidity_ratio",
    "market_strength",
})


class Pallas008StrategyEvidence(FrozenValue):
    """Immutable P008 ranking evidence carried across the DSA/Athena boundary."""

    strategy_id: Literal["PALLAS-008-A-SHARE-AUTONOMOUS-V1"]
    strategy_version: StrictStr = Field(pattern=r"^1\.0$")
    ranking_method: Literal["PALLAS_008_QUANTITATIVE_EVIDENCE"]
    ranking_score: CanonicalDecimal = Field(ge=0, le=1)
    discovery_rank: StrictInt = Field(ge=1)
    ranking_components: dict[StrictStr, CanonicalDecimal]
    market_strength_raw: CanonicalDecimal

    @model_validator(mode="after")
    def _evidence_semantics(self) -> Self:
        if set(self.ranking_components) != PALLAS_008_EVIDENCE_FIELDS:
            raise ValueError("PALLAS-008 ranking component fields mismatch")
        if any(value < 0 or value > 1 for value in self.ranking_components.values()):
            raise ValueError("PALLAS-008 ranking components are outside [0, 1]")
        return self
