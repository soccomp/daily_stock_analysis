"""Persistence for immutable Single Decision Scorecards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.storage import DatabaseManager, SingleDecisionScorecardRecord


class DecisionScorecardConflictError(RuntimeError):
    """A decision_id already exists with different immutable content."""


@dataclass(frozen=True)
class DecisionScorecardCreateResult:
    row: SingleDecisionScorecardRecord
    created: bool


class DecisionScorecardRepository:
    """Add once, read many; scorecard payloads are never updated in place."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def create_if_absent(
        self,
        *,
        decision_id: str,
        trace_id: str,
        account_id: str,
        symbol: str,
        action: str,
        payload_hash: str,
        payload_json: str,
    ) -> DecisionScorecardCreateResult:
        with self.db.get_session() as session:
            existing = session.execute(
                select(SingleDecisionScorecardRecord)
                .where(SingleDecisionScorecardRecord.decision_id == decision_id)
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                self._assert_same(existing, payload_hash, payload_json)
                return DecisionScorecardCreateResult(existing, False)
            row = SingleDecisionScorecardRecord(
                decision_id=decision_id,
                trace_id=trace_id,
                account_id=account_id,
                symbol=symbol,
                action=action,
                payload_hash=payload_hash,
                payload_json=payload_json,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.execute(
                    select(SingleDecisionScorecardRecord)
                    .where(SingleDecisionScorecardRecord.decision_id == decision_id)
                    .limit(1)
                ).scalar_one_or_none()
                if existing is None:
                    raise
                self._assert_same(existing, payload_hash, payload_json)
                return DecisionScorecardCreateResult(existing, False)
            session.refresh(row)
            return DecisionScorecardCreateResult(row, True)

    def get(self, decision_id: str) -> SingleDecisionScorecardRecord | None:
        with self.db.get_session() as session:
            return session.execute(
                select(SingleDecisionScorecardRecord)
                .where(SingleDecisionScorecardRecord.decision_id == decision_id)
                .limit(1)
            ).scalar_one_or_none()

    @staticmethod
    def _assert_same(
        row: SingleDecisionScorecardRecord,
        payload_hash: str,
        payload_json: str,
    ) -> None:
        if row.payload_hash != payload_hash or row.payload_json != payload_json:
            raise DecisionScorecardConflictError(
                "decision_id already has a different immutable scorecard"
            )
