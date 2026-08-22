"""Repository for durable, read-only market-review terminal outcomes."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from src.storage import DatabaseManager, MarketReviewOutcomeRecord, to_utc_naive_datetime


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class MarketReviewOutcomeConflictError(RuntimeError):
    """Raised when a stable outcome identity is reused with different evidence."""


class MarketReviewOutcomeRepository:
    """Persist and read terminal market-review outcomes without execution authority."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def persist_no_action(
        self,
        *,
        source_task_id: str,
        trade_date: date,
        reason: str,
        candidate_count: int = 0,
        persisted_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        source_task_id = str(source_task_id or "").strip()
        reason = str(reason or "").strip()
        if not source_task_id:
            raise ValueError("source_task_id is required")
        if not isinstance(trade_date, date):
            raise TypeError("trade_date must be a date")
        if int(candidate_count) != 0:
            raise ValueError("NO_ACTION requires candidate_count=0")
        if not reason:
            raise ValueError("NO_ACTION reason is required")

        now = persisted_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("persisted_at must be timezone-aware")
        persisted_utc = now.astimezone(timezone.utc)
        identity_body = {
            "source_task_id": source_task_id,
            "trade_date": trade_date.isoformat(),
            "outcome": "NO_ACTION",
            "candidate_count": 0,
            "reason": reason,
        }
        outcome_id = f"market-review-no-action-{hashlib.sha256(_canonical(identity_body)).hexdigest()[:32]}"
        provenance = {
            "source": "DSA.ProposalHandoffLoopService",
            "source_task_id": source_task_id,
            "record_type": "canonical_market_review_outcome",
            "integrity_method": "sha256-canonical-json-v1",
            "execution_authority": False,
            "simulation_only": True,
            "LIVE_TRADING": False,
        }
        content_body = {
            **identity_body,
            "outcome_id": outcome_id,
            "persisted_at": persisted_utc.isoformat(),
            "provenance": provenance,
        }
        content_hash = hashlib.sha256(_canonical(content_body)).hexdigest()
        with self.db.session_scope() as session:
            existing = session.get(MarketReviewOutcomeRecord, outcome_id)
            if existing is not None:
                if (
                    existing.source_task_id != source_task_id
                    or existing.trade_date != trade_date
                    or existing.outcome != "NO_ACTION"
                    or int(existing.candidate_count or 0) != 0
                    or existing.reason != reason
                ):
                    raise MarketReviewOutcomeConflictError(
                        f"outcome_id was reused with different content: {outcome_id}"
                    )
                return existing.to_dict()
            record = MarketReviewOutcomeRecord(
                outcome_id=outcome_id,
                source_task_id=source_task_id,
                trade_date=trade_date,
                outcome="NO_ACTION",
                candidate_count=0,
                reason=reason,
                persisted_at=to_utc_naive_datetime(persisted_utc),
                provenance_json=json.dumps(
                    provenance,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                content_hash=content_hash,
            )
            session.add(record)
            session.flush()
            return record.to_dict()

    def get_no_action(
        self,
        *,
        source_task_id: str,
        trade_date: date,
    ) -> Optional[dict[str, Any]]:
        with self.db.session_scope() as session:
            record = (
                session.query(MarketReviewOutcomeRecord)
                .filter(
                    MarketReviewOutcomeRecord.source_task_id == str(source_task_id),
                    MarketReviewOutcomeRecord.trade_date == trade_date,
                    MarketReviewOutcomeRecord.outcome == "NO_ACTION",
                )
                .one_or_none()
            )
            return record.to_dict() if record is not None else None
