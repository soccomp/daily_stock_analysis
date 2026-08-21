"""Immutable provenance for the event that caused one DSA research run."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, model_validator
from typing_extensions import Self

from .base import FrozenValue, canonical_json_bytes


ResearchTriggerType = Literal[
    "SCHEDULED_SCREENING",
    "SCHEDULED_HOLDING_REVIEW",
    "MATERIAL_EVENT_REVIEW",
    "DEFENSIVE_RISK_REVIEW",
    "MANUAL_OWNER_REVIEW",
]


class ResearchTrigger(FrozenValue):
    """Content-addressed trigger metadata carried beside candidate provenance."""

    research_trigger_id: StrictStr = Field(min_length=1, max_length=160)
    trigger_type: ResearchTriggerType
    trigger_source: StrictStr = Field(min_length=1, max_length=160)
    symbol: StrictStr = Field(pattern=r"^[0-9]{6}$")
    market: Literal["CN"]
    priority: StrictInt = Field(ge=1, le=100)
    created_at: AwareDatetime
    source_event_time: AwareDatetime | None = None
    effective_at: AwareDatetime
    scheduled_for: AwareDatetime
    dedup_key: StrictStr = Field(min_length=1, max_length=256)
    policy_version: StrictStr = Field(min_length=1, max_length=128)
    evidence_refs: tuple[StrictStr, ...] = Field(min_length=1)
    screening_scheduler_run_id: StrictStr | None = Field(default=None, min_length=1, max_length=160)
    screening_run_id: StrictStr | None = Field(default=None, min_length=1, max_length=160)
    portfolio_snapshot_id: StrictStr | None = Field(default=None, min_length=1, max_length=160)
    supersedes_trigger_id: StrictStr | None = Field(default=None, min_length=1, max_length=160)
    content_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_trigger(self) -> Self:
        if any(not value.strip() for value in self.evidence_refs):
            raise ValueError("evidence_refs cannot contain blank values")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidence_refs cannot contain duplicates")
        expected = hashlib.sha256(
            canonical_json_bytes(self.model_dump(mode="python", exclude={"content_hash"}))
        ).hexdigest()
        if self.content_hash != expected:
            raise ValueError("research trigger content_hash does not match canonical content")
        return self

    @classmethod
    def build(cls, **values: object) -> "ResearchTrigger":
        """Validate producer values and calculate the immutable content hash."""

        draft = cls.model_construct(**{**values, "content_hash": "0" * 64})
        payload = draft.model_dump(mode="python", exclude={"content_hash"})
        content_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return cls.model_validate({**payload, "content_hash": content_hash})

