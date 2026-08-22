"""Machine-consumable PALLAS-009 market-review evidence.

This adapter deliberately derives only from structured MarketAnalyzer fields.
LLM prose is retained as explanation, never converted into a numeric signal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


MARKET_CONTEXT_SCHEMA_VERSION = "pallas-009-market-context-v1"


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


def build_market_context(
    payload: Mapping[str, Any],
    *,
    task_id: str,
    market_review_id: str | int | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Build the context consumed by downstream research without order authority."""
    quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), Mapping) else {}
    concepts = payload.get("concepts") if isinstance(payload.get("concepts"), Mapping) else {}
    source_failures = list(quality.get("source_failures") or [])
    required = ("indices", "breadth", "sectors", "concepts")
    statuses = {name: str(quality.get(name) or "unknown") for name in required}
    available = [name for name, status in statuses.items() if status.startswith("available")]
    missing = [name for name, status in statuses.items() if status in {"unknown", "unavailable", "failed"}]
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
        "indices": payload.get("indices") or [],
        "breadth": payload.get("breadth"),
        "turnover": (payload.get("breadth") or {}).get("total_amount") if isinstance(payload.get("breadth"), Mapping) else None,
        "limit_up": (payload.get("breadth") or {}).get("limit_up_count") if isinstance(payload.get("breadth"), Mapping) else None,
        "limit_down": (payload.get("breadth") or {}).get("limit_down_count") if isinstance(payload.get("breadth"), Mapping) else None,
        "sector_strength": payload.get("sectors") or {},
        "concepts": {
            "data_status": concepts.get("data_status") or statuses["concepts"],
            "top": concepts.get("top") or [],
            "bottom": concepts.get("bottom") or [],
        },
        "news": payload.get("news") or [],
        "data_quality": quality,
        "market_strength": derive_market_strength(payload),
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
