"""Read-only PALLAS research-runtime improvement signals."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select

from src.investment.contracts.data_evidence import DataEvidence
from src.storage import ResearchTriggerLedgerRecord


def build_research_runtime_signals(
    *,
    coordinator: Any,
    now: datetime,
    data_evidence: Iterable[DataEvidence] = (),
) -> dict[str, Any]:
    """Produce explicit counters from the durable trigger/coverage projections."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("telemetry time must be timezone-aware")
    with coordinator.db.get_session() as session:
        rows = tuple(session.execute(select(ResearchTriggerLedgerRecord)).scalars())
    counts = Counter(row.trigger_type for row in rows)
    status_counts = Counter(row.status for row in rows)
    coverage = tuple(coordinator.coverage.projection())
    now_utc = now.astimezone(timezone.utc)
    due = [
        item for item in coverage
        if item["review_status"] in {"DUE", "DEFERRED_CAPACITY"}
        and item["next_review_due_at"] is not None
        and datetime.fromisoformat(item["next_review_due_at"].replace("Z", "+00:00")) <= now_utc
    ]
    overdue_ages = [
        max(0, int((now_utc - datetime.fromisoformat(item["next_review_due_at"].replace("Z", "+00:00")).astimezone(timezone.utc)).total_seconds()))
        for item in due
    ]
    evidence = tuple(data_evidence)
    return {
        "schema_version": "pallas-004-research-signals-v1",
        "observed_at": now_utc.isoformat().replace("+00:00", "Z"),
        "trigger_count_by_type": dict(sorted(counts.items())),
        "trigger_status_count": dict(sorted(status_counts.items())),
        "trigger_deduplicated": sum(int(row.duplicate_count or 0) for row in rows),
        "open_holdings_due": len(due),
        "max_overdue_age_seconds": max(overdue_ages, default=0),
        "capacity_deferrals": sum(
            1 for item in coverage if item["review_status"] == "DEFERRED_CAPACITY"
        ),
        "never_reviewed_holdings": sum(
            1 for item in coverage if item["last_successful_review_at"] is None
        ),
        "fairness_order": [
            item["symbol"] for item in sorted(
                coverage,
                key=lambda item: (
                    item["last_successful_review_at"] is not None,
                    item["last_successful_review_at"] or "",
                    item["symbol"],
                ),
            )
        ],
        "starvation_signals": [
            item["symbol"] for item in coverage
            if item["review_status"] == "DEFERRED_CAPACITY"
            and int(item["deferred_count"]) > 0
        ],
        "data_availability": dict(Counter(item.availability_status for item in evidence)),
        "data_freshness": dict(Counter(item.freshness_status for item in evidence)),
        "data_fallback_count": sum(1 for item in evidence if item.fallback_from),
        "data_conflict_count": sum(1 for item in evidence if item.conflict_refs),
        "evidence_unavailable": sum(
            1 for item in evidence if item.availability_status in {"UNAVAILABLE", "UNKNOWN"}
        ),
    }
