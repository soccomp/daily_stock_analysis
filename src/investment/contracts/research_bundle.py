"""DSA-owned ResearchBundle contract."""

from __future__ import annotations

from typing import ClassVar, Literal, Mapping

from pydantic import AwareDatetime, Field, StrictStr, model_validator
from typing_extensions import Self

from .base import CanonicalContract, CanonicalDecimal, DataQuality, FrozenValue
from .candidate_provenance import CandidateProvenance
from .data_evidence import DataEvidence
from .research_trigger import ResearchTrigger


class ExpectedReturnRange(FrozenValue):
    minimum: CanonicalDecimal
    maximum: CanonicalDecimal

    @model_validator(mode="after")
    def _range_is_ordered(self) -> Self:
        if self.minimum > self.maximum:
            raise ValueError("expected return minimum cannot exceed maximum")
        return self


class ModelProvenance(FrozenValue):
    model_name: StrictStr = Field(min_length=1, max_length=128)
    model_version: StrictStr = Field(min_length=1, max_length=128)
    provider: StrictStr = Field(min_length=1, max_length=128)
    prompt_hash: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ResearchBundle(CanonicalContract):
    """Research evidence without account allocation or execution authority."""

    BUILD_DEFAULTS: ClassVar[Mapping[str, object]] = {
        "schema_version": "1.0",
        "catalysts": (),
        "risk_factors": (),
        "invalidation_conditions": (),
        "strategy_refs": (),
        "data_evidence": (),
    }

    schema_version: Literal["1.0"]
    research_id: StrictStr = Field(min_length=1, max_length=160)
    symbol: StrictStr = Field(min_length=1, max_length=64)
    market: StrictStr = Field(min_length=1, max_length=32)
    as_of: AwareDatetime
    horizon: StrictStr = Field(min_length=1, max_length=64)
    trigger_source: StrictStr = Field(min_length=1, max_length=128)
    candidate_provenance: CandidateProvenance | None = None
    research_trigger: ResearchTrigger | None = None
    data_evidence: tuple[DataEvidence, ...] = ()

    market_regime: StrictStr = Field(min_length=1)
    industry_view: StrictStr = Field(min_length=1)
    fundamental_view: StrictStr = Field(min_length=1)
    technical_view: StrictStr = Field(min_length=1)
    valuation_view: StrictStr = Field(min_length=1)
    intel_view: StrictStr = Field(min_length=1)
    capital_flow_view: StrictStr = Field(min_length=1)

    bull_case: StrictStr = Field(min_length=1)
    base_case: StrictStr = Field(min_length=1)
    bear_case: StrictStr = Field(min_length=1)
    expected_return_range: ExpectedReturnRange

    catalysts: tuple[StrictStr, ...]
    risk_factors: tuple[StrictStr, ...]
    invalidation_conditions: tuple[StrictStr, ...]
    evidence_refs: tuple[StrictStr, ...] = Field(min_length=1)
    data_quality: DataQuality
    confidence: CanonicalDecimal = Field(ge=0, le=1)
    model_provenance: tuple[ModelProvenance, ...] = Field(min_length=1)
    strategy_refs: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def _research_semantics(self) -> Self:
        for field_name in (
            "catalysts",
            "risk_factors",
            "invalidation_conditions",
            "evidence_refs",
            "strategy_refs",
        ):
            values = getattr(self, field_name)
            if any(not value.strip() for value in values):
                raise ValueError(f"{field_name} cannot contain blank values")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} cannot contain duplicates")
        evidence_ids = [item.data_evidence_id for item in self.data_evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("data_evidence cannot contain duplicate identifiers")
        return self
