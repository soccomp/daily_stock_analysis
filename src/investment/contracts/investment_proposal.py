"""DSA-owned advisory investment proposal contract."""

from __future__ import annotations

from typing import ClassVar, Literal, Mapping

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, model_validator
from typing_extensions import Self

from .base import CanonicalContract, CanonicalDecimal, StrictTrue, canonical_json_bytes
from .candidate_provenance import CandidateProvenance
from .data_evidence import DataEvidence
from .research_trigger import ResearchTrigger
from .research_bundle import ModelProvenance
from .strategy_evidence import Pallas008StrategyEvidence


class InvestmentProposal(CanonicalContract):
    """Research-backed advice that carries no portfolio or execution authority."""

    BUILD_DEFAULTS: ClassVar[Mapping[str, object]] = {
        "schema_version": "1.0",
        "suggested_target_weight": None,
        "ideal_entry": None,
        "secondary_entry": None,
        "stop_price": None,
        "target_price": None,
        "advisory_only": True,
        "final_allocation_permitted": False,
        "execution_permitted": False,
    }

    schema_version: Literal["1.0"]
    proposal_id: StrictStr = Field(min_length=1, max_length=160)
    research_id: StrictStr = Field(min_length=1, max_length=160)
    research_content_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    cycle_id: StrictStr = Field(min_length=1, max_length=160)
    source_report_id: StrictInt = Field(gt=0)
    source_report_ref: StrictStr = Field(min_length=1, max_length=256)
    symbol: StrictStr = Field(pattern=r"^[0-9]{6}$")
    market: Literal["CN"]
    action: Literal["BUY", "HOLD", "AVOID", "REDUCE", "SELL"]
    candidate_provenance: CandidateProvenance | None = None
    research_trigger: ResearchTrigger | None = None
    strategy_evidence: Pallas008StrategyEvidence | None = None
    data_evidence: tuple[DataEvidence, ...] = ()
    confidence: CanonicalDecimal = Field(ge=0, le=1)
    expected_return: CanonicalDecimal
    suggested_target_weight: CanonicalDecimal | None = Field(default=None, gt=0, le=1)
    ideal_entry: CanonicalDecimal | None = Field(default=None, gt=0)
    secondary_entry: CanonicalDecimal | None = Field(default=None, gt=0)
    stop_price: CanonicalDecimal | None = Field(default=None, gt=0)
    target_price: CanonicalDecimal | None = Field(default=None, gt=0)
    thesis: StrictStr = Field(min_length=1)
    risks: tuple[StrictStr, ...] = Field(min_length=1)
    invalidation_conditions: tuple[StrictStr, ...] = Field(min_length=1)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    model_provenance: tuple[ModelProvenance, ...] = Field(min_length=1)
    advisory_only: StrictTrue
    final_allocation_permitted: Literal[False]
    execution_permitted: Literal[False]

    def _wire_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="python")
        if self.candidate_provenance is None:
            payload.pop("candidate_provenance", None)
        if self.research_trigger is None:
            payload.pop("research_trigger", None)
        if self.strategy_evidence is None:
            payload.pop("strategy_evidence", None)
        if not self.data_evidence:
            payload.pop("data_evidence", None)
        return payload

    def hash_payload(self) -> dict[str, object]:
        payload = self._wire_payload()
        payload.pop("content_hash", None)
        return payload

    def canonical_json(self) -> str:
        return canonical_json_bytes(self._wire_payload()).decode("utf-8")

    @model_validator(mode="after")
    def _proposal_semantics(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("proposal validity window is invalid")
        for field_name in ("risks", "invalidation_conditions"):
            values = getattr(self, field_name)
            if any(not value.strip() for value in values) or len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique non-blank values")
        evidence_ids = [item.data_evidence_id for item in self.data_evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("data_evidence cannot contain duplicate identifiers")
        trigger_evidence = (
            self.research_trigger.strategy_evidence
            if self.research_trigger is not None
            else None
        )
        if trigger_evidence is not None and self.strategy_evidence != trigger_evidence:
            raise ValueError("research trigger and proposal strategy evidence do not match")
        price_fields = (self.ideal_entry, self.secondary_entry, self.stop_price, self.target_price)
        if self.action == "BUY":
            if any(value is None for value in price_fields):
                raise ValueError("BUY proposal requires entry, stop and target prices")
            assert self.ideal_entry is not None and self.secondary_entry is not None
            assert self.stop_price is not None and self.target_price is not None
            if not self.stop_price < self.ideal_entry <= self.secondary_entry < self.target_price:
                raise ValueError("BUY proposal price plan is invalid")
            if self.expected_return <= 0:
                raise ValueError("BUY proposal expected return must be positive")
        elif any(value is not None for value in price_fields):
            raise ValueError("non-BUY proposal cannot carry an entry price plan")
        return self
