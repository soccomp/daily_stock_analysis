"""Deterministic identities for restart-safe M2 cycles and analysis work."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from src.investment.contracts.base import canonical_json_bytes


def cycle_slot(value: datetime, *, interval_minutes: int) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("M2 cycle time must be timezone-aware")
    interval = max(1, int(interval_minutes))
    utc_value = value.astimezone(timezone.utc).replace(second=0, microsecond=0)
    minute_number = int(utc_value.timestamp() // 60)
    slot_number = minute_number - (minute_number % interval)
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=slot_number)


def cycle_id(*, account_id: str, scheduled_for: datetime) -> str:
    digest = _digest(
        {
            "account_id": account_id,
            "scheduled_for": scheduled_for,
            "mission": "SINGLE_BRAIN_M2",
        }
    )
    return f"m2-cycle-{digest[:40]}"


def analysis_query_id(*, cycle: str, symbol: str) -> str:
    return f"m2-analysis-{_digest({'cycle_id': cycle, 'symbol': symbol})[:40]}"


def decision_id(
    *,
    cycle: str,
    symbol: str,
    source_report_id: int,
    snapshot_hash: str,
    policy_hash: str,
) -> str:
    return f"decision-m2-{_digest({
        'cycle_id': cycle,
        'symbol': symbol,
        'source_report_id': source_report_id,
        'snapshot_hash': snapshot_hash,
        'policy_hash': policy_hash,
    })[:40]}"


def input_hash(
    *,
    snapshot_hash: str,
    policy_id: str,
    policy_version: str,
    policy_hash: str,
) -> str:
    return _digest(
        {
            "portfolio_snapshot_hash": snapshot_hash,
            "risk_policy_id": policy_id,
            "risk_policy_version": policy_version,
            "risk_policy_hash": policy_hash,
        }
    )


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
