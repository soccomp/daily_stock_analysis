"""Machine-consumable PALLAS-009 market-review evidence.

This adapter deliberately derives only from structured MarketAnalyzer fields.
LLM prose is retained as explanation, never converted into a numeric signal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from src.services.screening.temporal import (
    actionable_news_payload_for_cutoff,
    canonical_utc,
    require_decision_cutoff,
)


MARKET_CONTEXT_SCHEMA_VERSION = "pallas-009-market-context-v1"
_MARKET_COMPONENTS = ("indices", "breadth", "sectors", "concepts")
_COMPONENT_TIMESTAMP_KEYS = (
    "observed_at",
    "source_event_time",
    "event_time",
    "retrieved_at",
    "fetched_at",
    "evidence_at",
    "evidence_timestamp",
    "timestamp",
)


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def derive_market_strength(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Derive a bounded, auditable market-strength support signal."""
    breadth = payload.get("breadth") if isinstance(payload.get("breadth"), Mapping) else {}
    quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), Mapping) else {}
    up = float(breadth.get("up_count") or 0)
    down = float(breadth.get("down_count") or 0)
    flat = float(breadth.get("flat_count") or 0)
    participants = up + down + flat
    breadth_signal = ((up - down) / participants) if participants else None

    limit_up = float(breadth.get("limit_up_count") or 0)
    limit_down = float(breadth.get("limit_down_count") or 0)
    limit_total = limit_up + limit_down
    limit_signal = ((limit_up - limit_down) / limit_total) if limit_total else None

    indices = payload.get("indices") if isinstance(payload.get("indices"), list) else []
    changes = []
    for index in indices:
        if not isinstance(index, Mapping):
            continue
        try:
            changes.append(float(index.get("change_pct")))
        except (TypeError, ValueError):
            continue
    index_signal = (sum(changes) / len(changes) / 5.0) if changes else None

    components = {
        "breadth": None if breadth_signal is None else round(_clamp(breadth_signal), 6),
        "limit_up_down": None if limit_signal is None else round(_clamp(limit_signal), 6),
        "indices": None if index_signal is None else round(_clamp(index_signal), 6),
    }
    available = [value for value in components.values() if value is not None]
    strength = round(_clamp(sum(available) / len(available)), 6) if available else None
    concept_status = str(quality.get("concepts") or "unknown")
    return {
        "value": strength,
        "components": components,
        "method": "deterministic_structured_inputs_v1",
        "quality_adjustment": "degraded" if concept_status in {"failed", "unavailable"} else "normal",
        "available_inputs": len(available),
    }


def _component_metadata(payload: Mapping[str, Any], component: str) -> Any:
    for container_name in (
        "component_provenance",
        "component_evidence",
        "component_timing",
    ):
        container = payload.get(container_name)
        if isinstance(container, Mapping) and component in container:
            return container[component]

    component_payload = payload.get(component)
    if isinstance(component_payload, Mapping):
        for key in ("provenance", "evidence", "timing"):
            if key in component_payload:
                return component_payload[key]
    return None


def _component_timestamps(value: Any) -> tuple[Any, ...]:
    if not isinstance(value, Mapping):
        return ()
    values = [
        value[key]
        for key in _COMPONENT_TIMESTAMP_KEYS
        if value.get(key) is not None
    ]
    nested = value.get("timestamps")
    if isinstance(nested, (list, tuple)):
        values.extend(nested)
    return tuple(values)


def _component_pit_evidence(
    payload: Mapping[str, Any],
    cutoff: datetime,
) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for component in _MARKET_COMPONENTS:
        metadata = _component_metadata(payload, component)
        raw_timestamps = _component_timestamps(metadata)
        if not raw_timestamps:
            evidence[component] = {
                "status": "UNKNOWN_EXCLUDED",
                "reference": None,
            }
            continue
        try:
            timestamps = tuple(
                require_decision_cutoff(value) for value in raw_timestamps
            )
        except (TypeError, ValueError):
            evidence[component] = {
                "status": "UNKNOWN_EXCLUDED",
                "reference": metadata.get("reference")
                if isinstance(metadata, Mapping)
                else None,
            }
            continue
        if any(value > cutoff for value in timestamps):
            status = "LATER_THAN_CUTOFF_EXCLUDED"
        else:
            status = "PIT_VALIDATED"
        evidence[component] = {
            "status": status,
            "observed_at": max(canonical_utc(value) for value in timestamps),
            "reference": metadata.get("reference")
            if isinstance(metadata, Mapping)
            else None,
        }
    return evidence


def build_market_context(
    payload: Mapping[str, Any],
    *,
    task_id: str,
    market_review_id: str | int | None = None,
    as_of: str | datetime | None = None,
) -> dict[str, Any]:
    """Build the context consumed by downstream research without order authority."""
    quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), Mapping) else {}
    source_failures = list(quality.get("source_failures") or [])
    news_cutoff = as_of or payload.get("generated_at")
    news_actionability = "UNKNOWN_EXCLUDED"
    news: tuple[dict[str, Any], ...] = ()
    news_audit_excluded: tuple[dict[str, Any], ...] = ()
    decision_as_of = None
    if news_cutoff:
        try:
            decision_as_of = canonical_utc(require_decision_cutoff(news_cutoff))
            news, news_audit_excluded = actionable_news_payload_for_cutoff(
                payload.get("news") or [],
                decision_as_of,
            )
            news_actionability = "CUTOFF_FILTERED"
        except (TypeError, ValueError):
            news_audit_excluded = (
                {"point_in_time_status": "EXCLUDED_UNKNOWN_OR_LATER_THAN_CUTOFF"},
            ) if payload.get("news") else ()
    component_evidence = {}
    component_payload = payload
    if as_of is not None:
        pit_cutoff = require_decision_cutoff(as_of)
        component_evidence = _component_pit_evidence(payload, pit_cutoff)
        component_payload = dict(payload)
        for component, metadata in component_evidence.items():
            if metadata["status"] != "PIT_VALIDATED":
                component_payload.pop(component, None)
        component_payload["breadth"] = (
            payload.get("breadth")
            if component_evidence["breadth"]["status"] == "PIT_VALIDATED"
            else None
        )
        component_payload["indices"] = (
            payload.get("indices")
            if component_evidence["indices"]["status"] == "PIT_VALIDATED"
            else []
        )
        component_payload["sectors"] = (
            payload.get("sectors")
            if component_evidence["sectors"]["status"] == "PIT_VALIDATED"
            else {}
        )
        component_payload["concepts"] = (
            payload.get("concepts")
            if component_evidence["concepts"]["status"] == "PIT_VALIDATED"
            else {}
        )
        component_quality = dict(quality)
        for component, metadata in component_evidence.items():
            if metadata["status"] != "PIT_VALIDATED":
                component_quality[component] = f"{metadata['status'].lower()}"
        component_payload["data_quality"] = component_quality
        quality = component_quality
    elif isinstance(quality, Mapping):
        component_evidence = {
            component: {"status": "UNVERIFIED", "reference": None}
            for component in _MARKET_COMPONENTS
        }
    required = ("indices", "breadth", "sectors", "concepts")
    statuses = {name: str(quality.get(name) or "unknown") for name in required}
    available = [name for name, status in statuses.items() if status.startswith("available")]
    missing = [name for name, status in statuses.items() if status in {"unknown", "unavailable", "failed"}]
    if as_of is not None:
        missing.extend(
            name for name, metadata in component_evidence.items()
            if metadata["status"] != "PIT_VALIDATED" and name not in missing
        )
        available = [
            name for name in available
            if component_evidence[name]["status"] == "PIT_VALIDATED"
        ]
    missing = list(dict.fromkeys(missing))
    component_timing_status = (
        "PIT_VALIDATED"
        if as_of is not None and all(
            metadata["status"] == "PIT_VALIDATED"
            for metadata in component_evidence.values()
        )
        else "PIT_PARTIAL"
        if as_of is not None and any(
            metadata["status"] == "PIT_VALIDATED"
            for metadata in component_evidence.values()
        )
        else "UNKNOWN_EXCLUDED"
        if as_of is not None
        else "UNVERIFIED"
    )
    context = {
        "schema_version": MARKET_CONTEXT_SCHEMA_VERSION,
        "context_id": f"market-context:{task_id}",
        "market_review_id": market_review_id,
        "source_task_id": task_id,
        "market": payload.get("region"),
        "trade_date": payload.get("date"),
        "as_of": as_of or payload.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "source_completeness": {
            "requested": required,
            "available": available,
            "missing": missing,
            "failed": source_failures,
            "status": "complete" if not missing and not source_failures else "degraded",
        },
        "indices": component_payload.get("indices") or [],
        "breadth": component_payload.get("breadth"),
        "turnover": (component_payload.get("breadth") or {}).get("total_amount") if isinstance(component_payload.get("breadth"), Mapping) else None,
        "limit_up": (component_payload.get("breadth") or {}).get("limit_up_count") if isinstance(component_payload.get("breadth"), Mapping) else None,
        "limit_down": (component_payload.get("breadth") or {}).get("limit_down_count") if isinstance(component_payload.get("breadth"), Mapping) else None,
        "sector_strength": component_payload.get("sectors") or {},
        "concepts": {
            "data_status": (component_payload.get("concepts") or {}).get("data_status") or statuses["concepts"],
            "top": (component_payload.get("concepts") or {}).get("top") or [],
            "bottom": (component_payload.get("concepts") or {}).get("bottom") or [],
        },
        "news": list(news),
        "news_audit_excluded": list(news_audit_excluded),
        "news_actionability": news_actionability,
        "decision_as_of": decision_as_of,
        "data_quality": quality,
        "market_strength": derive_market_strength(component_payload),
        "component_timing_status": component_timing_status,
        "component_provenance": component_evidence,
        "provenance": {
            "source": "DSA MarketAnalyzer",
            "source_payload_kind": payload.get("kind", "market_review"),
            "source_task_id": task_id,
            "immutable_evidence": True,
        },
    }
    return context


def no_action_outcome(*, task_id: str, reason: str, candidate_count: int = 0) -> dict[str, Any]:
    """Represent zero candidates before repository persistence.

    Callers that need a durable artifact must use
    ``MarketReviewOutcomeRepository.persist_no_action`` and pass its returned
    record downstream.  Keeping this helper explicitly non-durable prevents an
    in-memory projection from being mistaken for persisted evidence.
    """
    return {
        "outcome": "NO_ACTION",
        "candidate_count": int(candidate_count),
        "reason": reason,
        "source_task_id": task_id,
        "outcome_id": None,
        "trade_date": None,
        "persisted_at": None,
        "durable": False,
        "content_hash": None,
        "provenance": {"record_type": "in_memory_market_review_outcome"},
        "execution_authority": False,
    }
