"""Content-addressed evidence about the inputs used by DSA research."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, Field, StrictStr, model_validator
from typing_extensions import Self

from .base import FrozenValue, canonical_json_bytes
from src.services.screening.temporal import actionable_news_for_cutoff


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
    availability, quality_flags = _analysis_availability(
        context_snapshot=context_snapshot,
        default_availability=availability,
        quality=quality,
    )
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
        quality_flags=quality_flags,
    )


def price_plan_evidence(*, context_snapshot: Any, source_report_id: int, now) -> DataEvidence:
    """Record price-plan timing without inventing an upstream event time.

    Analysis snapshots produced by older callers often contain only a display
    price.  Such evidence is retained as UNKNOWN so Athena can reject an
    actionable proposal instead of silently treating retrieval time as quote
    time.
    """

    source_event_time = _find_aware_timestamp(
        context_snapshot,
        keys=("source_event_time", "provider_timestamp", "quote_timestamp", "event_time"),
    )
    retrieved_at = _find_aware_timestamp(
        context_snapshot,
        keys=("retrieved_at", "fetched_at", "realtime_fetched_at"),
    ) or now
    provider = _find_text(context_snapshot, keys=("provider", "source")) or "DSA_ANALYSIS_CONTEXT"
    source_reference = _find_text(
        context_snapshot,
        keys=("source_reference", "quote_reference", "reference"),
    ) or f"dsa-price-plan:{source_report_id}"
    cutoff = now
    flags: list[str] = []
    available = source_event_time is not None
    if source_event_time is None:
        flags.append("PRICE_PLAN_SOURCE_EVENT_TIME_MISSING")
    else:
        completion = _find_text(
            context_snapshot,
            keys=("completion_status", "daily_completion_status"),
        )
        flags.append("DAILY_BAR_COMPLETE" if completion == "CLOSE_CONFIRMED" else "INTRADAY_OBSERVED")
        if source_event_time > now:
            available = False
            flags.append("PRICE_PLAN_SOURCE_EVENT_TIME_LATER_THAN_DECISION")
    return DataEvidence.build(
        data_evidence_id=f"data-evidence-price-plan-{source_report_id}",
        data_class="PRICE_PLAN",
        provider=provider,
        upstream_ref=f"dsa-analysis-history:{source_report_id}",
        source_reference=source_reference,
        source_event_time=source_event_time,
        as_of=cutoff,
        retrieved_at=retrieved_at,
        observed_at=retrieved_at,
        freshness_policy_id="price-plan-point-in-time-v1",
        freshness_status="FRESH" if available else "UNKNOWN",
        availability_status="AVAILABLE" if available else "UNKNOWN",
        quality_flags=tuple(dict.fromkeys(flags)),
    )


def actionable_news_evidence(
    *,
    items: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    decision_as_of,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    """Expose the cutoff rule for callers assembling LLM evidence."""

    return actionable_news_for_cutoff(items, decision_as_of)


def _find_text(value: Any, *, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, Mapping):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            found = _find_text(nested, keys=keys)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_text(nested, keys=keys)
            if found:
                return found
    return None


def _find_aware_timestamp(value: Any, *, keys: tuple[str, ...]) -> datetime | None:
    if isinstance(value, Mapping):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, datetime) and candidate.tzinfo is not None and candidate.utcoffset() is not None:
                return candidate
            if isinstance(candidate, str):
                try:
                    parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
                except ValueError:
                    parsed = None
                if parsed is not None and parsed.tzinfo is not None and parsed.utcoffset() is not None:
                    return parsed
        for nested in value.values():
            found = _find_aware_timestamp(nested, keys=keys)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_aware_timestamp(nested, keys=keys)
            if found is not None:
                return found
    return None


def _analysis_availability(
    *,
    context_snapshot: Any,
    default_availability: str,
    quality: str,
) -> tuple[str, tuple[str, ...]]:
    """Keep block-level degradation visible in the immutable evidence contract."""

    flags = [f"EXPLICIT_{quality.upper()}"]
    if not isinstance(context_snapshot, Mapping):
        return default_availability, tuple(flags)
    overview = context_snapshot.get("analysis_context_pack_overview")
    if not isinstance(overview, Mapping):
        return default_availability, tuple(flags)
    blocks = overview.get("blocks")
    if not isinstance(blocks, list):
        return default_availability, tuple(flags)

    statuses: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        status = str(block.get("status") or "").strip().lower()
        key = str(block.get("key") or "unknown").strip() or "unknown"
        if not status:
            continue
        statuses.append(status)
        if status in {
            "partial",
            "missing",
            "fetch_failed",
            "stale",
            "fallback",
            "estimated",
            "not_supported",
            "unavailable",
        }:
            flags.append(f"BLOCK_{status.upper()}:{key}")

    data_quality = overview.get("data_quality")
    if isinstance(data_quality, Mapping):
        for limitation in data_quality.get("limitations", ()):
            text = str(limitation).strip()
            if text:
                flags.append(f"LIMITATION:{text}")
    for warning in overview.get("warnings", ()):
        text = str(warning).strip()
        if text:
            flags.append(f"WARNING:{text}")

    degraded = {
        "partial",
        "missing",
        "fetch_failed",
        "stale",
        "fallback",
        "estimated",
        "not_supported",
        "unavailable",
    }
    unavailable = {"missing", "fetch_failed", "unavailable", "not_supported"}
    if statuses and all(status in unavailable for status in statuses):
        availability = "UNAVAILABLE"
    elif any(status in degraded for status in statuses):
        availability = "DEGRADED"
    else:
        availability = default_availability
    return availability, tuple(dict.fromkeys(flags))


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
