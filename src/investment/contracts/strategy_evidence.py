"""Structured quantitative evidence for the PALLAS-008 strategy boundary."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, model_validator
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
PALLAS_008_TEMPORAL_FIELDS = frozenset({
    "latest_completed_trade_date",
    "decision_cutoff",
    "completion_status",
    "completion_basis",
    "quantitative_input_reference",
    "intraday_prefilter_observed_at",
    "intraday_prefilter_reference",
    "evidence_hash",
})


def pallas008_strategy_evidence_hash(values: dict) -> str:
    """Calculate the immutable hash shared by DSA and Athena."""

    from .base import canonical_json_bytes

    body = dict(values)
    body.pop("evidence_hash", None)
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def build_pallas008_strategy_evidence(**values):
    """Build a complete temporal P008 evidence mapping for producers/tests."""

    body = dict(values)
    body.setdefault("intraday_prefilter_observed_at", None)
    body.setdefault("intraday_prefilter_reference", None)
    body["evidence_hash"] = pallas008_strategy_evidence_hash(body)
    return body


class Pallas008StrategyEvidence(FrozenValue):
    """Immutable P008 ranking evidence carried across the DSA/Athena boundary."""

    strategy_id: Literal["PALLAS-008-A-SHARE-AUTONOMOUS-V1"]
    strategy_version: StrictStr = Field(pattern=r"^1\.0$")
    ranking_method: Literal["PALLAS_008_QUANTITATIVE_EVIDENCE"]
    ranking_score: CanonicalDecimal = Field(ge=0, le=1)
    discovery_rank: StrictInt = Field(ge=1)
    ranking_components: dict[StrictStr, CanonicalDecimal]
    market_strength_raw: CanonicalDecimal
    latest_completed_trade_date: StrictStr = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    decision_cutoff: AwareDatetime
    completion_status: Literal["CLOSE_CONFIRMED"]
    completion_basis: StrictStr = Field(min_length=1, max_length=160)
    quantitative_input_reference: StrictStr = Field(min_length=1, max_length=2048)
    intraday_prefilter_observed_at: AwareDatetime | None = None
    intraday_prefilter_reference: StrictStr | None = Field(default=None, min_length=1, max_length=512)
    evidence_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def _parse_wire_timestamps(cls, values):
        if not isinstance(values, dict):
            return values
        normalized = dict(values)
        for field_name in ("decision_cutoff", "intraday_prefilter_observed_at"):
            value = normalized.get(field_name)
            if isinstance(value, str):
                try:
                    normalized[field_name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    pass
        return normalized

    @model_validator(mode="after")
    def _evidence_semantics(self) -> Self:
        if set(self.ranking_components) != PALLAS_008_EVIDENCE_FIELDS:
            raise ValueError("PALLAS-008 ranking component fields mismatch")
        if any(value < 0 or value > 1 for value in self.ranking_components.values()):
            raise ValueError("PALLAS-008 ranking components are outside [0, 1]")
        latest = date.fromisoformat(self.latest_completed_trade_date)
        if latest > self.decision_cutoff.astimezone(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("latest completed trade date is later than decision cutoff")
        if (self.intraday_prefilter_observed_at is None) != (self.intraday_prefilter_reference is None):
            raise ValueError("intraday prefilter provenance is incomplete")
        expected = pallas008_strategy_evidence_hash(
            self.model_dump(mode="python", exclude={"evidence_hash"})
        )
        if self.evidence_hash != expected:
            raise ValueError("PALLAS-008 evidence_hash does not match canonical content")
        return self
