"""Content-addressed evidence about the inputs used by DSA research."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, Field, StrictStr, model_validator
from typing_extensions import Self

from .base import FrozenValue, canonical_json_bytes


PORTFOLIO_SNAPSHOT_MAX_AGE = timedelta(minutes=5)


class DataEvidence(FrozenValue):
    """Purpose-specific data trust metadata; it never grants execution authority."""

    data_evidence_id: StrictStr = Field(min_length=1, max_length=160)
    data_class: StrictStr = Field(min_length=1, max_length=64)
    provider: StrictStr = Field(min_length=1, max_length=128)
    upstream_ref: StrictStr = Field(min_length=1, max_length=512)
    source_reference: StrictStr = Field(min_length=1, max_length=512)
    snapshot_ref: StrictStr | None = Field(default=None, max_length=512)
    source_event_time: AwareDatetime | None = None
    as_of: AwareDatetime
    retrieved_at: AwareDatetime
    observed_at: AwareDatetime
    freshness_policy_id: StrictStr = Field(min_length=1, max_length=128)
    freshness_status: Literal["FRESH", "AGING", "STALE", "UNKNOWN"]
    availability_status: Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE", "CONFLICT", "UNKNOWN"]
    fallback_from: StrictStr | None = Field(default=None, max_length=512)
    quality_flags: tuple[StrictStr, ...] = ()
    conflict_refs: tuple[StrictStr, ...] = ()
    content_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _evidence_semantics(self) -> Self:
        for field_name in ("quality_flags", "conflict_refs"):
            values = getattr(self, field_name)
            if any(not value.strip() for value in values):
                raise ValueError(f"{field_name} cannot contain blank values")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} cannot contain duplicates")
        if self.availability_status == "CONFLICT" and not self.conflict_refs:
            raise ValueError("CONFLICT evidence requires conflict_refs")
        body = self.model_dump(mode="python", exclude={"content_hash"})
        expected = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        if self.content_hash != expected:
            raise ValueError("content_hash does not match DataEvidence content")
        return self

    @classmethod
    def build(cls, **values: Any) -> "DataEvidence":
        if "content_hash" in values:
            raise ValueError("DataEvidence.build() calculates content_hash")
        body = dict(values)
        body.setdefault("snapshot_ref", None)
        body.setdefault("source_event_time", None)
        body.setdefault("fallback_from", None)
        body.setdefault("quality_flags", ())
        body.setdefault("conflict_refs", ())
        body["content_hash"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        return cls.model_validate(body)


def portfolio_snapshot_evidence(*, snapshot: Any, now) -> DataEvidence:
    """Represent Athena truth with freshness derived from authoritative age semantics."""

    reconciled = (
        getattr(snapshot, "authoritative", False) is True
        and getattr(snapshot, "read_only", False) is True
        and getattr(snapshot, "simulation_only", False) is True
        and getattr(snapshot, "reconciliation_status", None) == "RECONCILED"
    )
    quality = str(getattr(snapshot, "data_quality", "UNKNOWN"))
    freshness = _portfolio_freshness(
        as_of=getattr(snapshot, "as_of", None),
        observed_at=now,
    )
    availability = "AVAILABLE" if reconciled else "UNAVAILABLE"
    snapshot_id = str(getattr(snapshot, "snapshot_id", "") or "")
    if not snapshot_id:
        raise ValueError("PortfolioSnapshot evidence requires snapshot_id")
    return DataEvidence.build(
        data_evidence_id=f"data-evidence-portfolio-{snapshot_id}",
        data_class="PORTFOLIO_SNAPSHOT",
        provider="ATHENA_RUNTIME",
        upstream_ref=str(getattr(snapshot, "broker_snapshot_ref", "") or snapshot_id),
        source_reference=f"portfolio-snapshot:{snapshot_id}",
        snapshot_ref=snapshot_id,
        source_event_time=snapshot.as_of,
        as_of=snapshot.as_of,
        retrieved_at=now,
        observed_at=now,
        freshness_policy_id="portfolio-snapshot-authority-v1",
        freshness_status=freshness,
        availability_status=availability,
        quality_flags=("AUTHORITATIVE", "READ_ONLY", "SIMULATION_ONLY", quality),
    )


def analysis_context_evidence(*, context_snapshot: Any, source_report_id: int, now) -> DataEvidence:
    """Preserve DSA quality while leaving freshness UNKNOWN without source timing."""

    from src.services.decision_signal_data_quality import normalize_decision_signal_data_quality

    quality = normalize_decision_signal_data_quality(context_snapshot)
    availability = {
        "high": "AVAILABLE",
        "medium": "AVAILABLE",
        "low": "DEGRADED",
        "poor": "UNAVAILABLE",
        "unknown": "UNKNOWN",
    }[quality]
    return DataEvidence.build(
        data_evidence_id=f"data-evidence-analysis-{source_report_id}",
        data_class="RESEARCH_INPUT",
        provider="DSA_ANALYSIS_CONTEXT",
        upstream_ref=f"dsa-analysis-history:{source_report_id}",
        source_reference=f"dsa-analysis-context:{source_report_id}",
        as_of=now,
        retrieved_at=now,
        observed_at=now,
        freshness_policy_id="analysis-context-explicit-quality-v1",
        freshness_status="UNKNOWN",
        availability_status=availability,
        quality_flags=(f"EXPLICIT_{quality.upper()}",),
    )


def _portfolio_freshness(*, as_of: Any, observed_at: Any) -> str:
    """Reuse the existing five-minute snapshot gate; do not infer age from quality."""

    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        return "UNKNOWN"
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return "UNKNOWN"
    age = observed_at.astimezone(timezone.utc) - as_of.astimezone(timezone.utc)
    if age.total_seconds() < 0:
        return "UNKNOWN"
    return "FRESH" if age <= PORTFOLIO_SNAPSHOT_MAX_AGE else "STALE"
