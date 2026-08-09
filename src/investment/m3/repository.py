"""Durable DSA-side dispatch checkpoint; Athena remains portfolio authority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.investment.contracts.base import canonical_json_bytes, canonicalize
from src.investment.contracts.execution_mandate import ExecutionMandate
from src.investment.contracts.execution_result import ExecutionResult
from src.investment.contracts.investment_decision import InvestmentDecision
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.contracts.research_bundle import ResearchBundle
from src.investment.contracts.risk_policy import RiskPolicy
from src.storage import (
    DatabaseManager,
    SingleBrainM3ExecutionRecord,
    utc_naive_now,
)


TERMINAL_EXECUTION_STATUSES = {
    "FILLED",
    "BLOCKED",
    "BROKER_REJECTED",
    "EXPIRED",
    "CANCELLED",
}


def _contract_json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


@dataclass(frozen=True)
class M3DecisionLineage:
    source_report_id: int
    research_bundle: ResearchBundle
    portfolio_snapshot_a: PortfolioSnapshot
    risk_policy: RiskPolicy
    investment_decision: InvestmentDecision
    decision_signal: dict[str, Any]

    def to_json(self) -> str:
        return _contract_json({
            "source_report_id": self.source_report_id,
            "research_bundle": self.research_bundle,
            "portfolio_snapshot_a": self.portfolio_snapshot_a,
            "risk_policy": self.risk_policy,
            "investment_decision": self.investment_decision,
            "decision_signal": self.decision_signal,
        })

    @classmethod
    def from_json(cls, value: str) -> "M3DecisionLineage":
        payload = json.loads(value)
        if set(payload) != {
            "source_report_id",
            "research_bundle",
            "portfolio_snapshot_a",
            "risk_policy",
            "investment_decision",
            "decision_signal",
        }:
            raise ValueError("M3 decision lineage fields mismatch")
        return cls(
            source_report_id=payload["source_report_id"],
            research_bundle=ResearchBundle.model_validate_json(
                _contract_json(payload["research_bundle"])
            ),
            portfolio_snapshot_a=PortfolioSnapshot.model_validate_json(
                _contract_json(payload["portfolio_snapshot_a"])
            ),
            risk_policy=RiskPolicy.model_validate_json(
                _contract_json(payload["risk_policy"])
            ),
            investment_decision=InvestmentDecision.model_validate_json(
                _contract_json(payload["investment_decision"])
            ),
            decision_signal=canonicalize(payload["decision_signal"]),
        )


@dataclass(frozen=True)
class M3ExecutionCheckpoint:
    decision_id: str
    cycle_id: str
    symbol: str
    status: str
    lineage: M3DecisionLineage
    mandate: ExecutionMandate
    results: tuple[ExecutionResult, ...]
    portfolio_snapshot_b: PortfolioSnapshot | None
    dispatch_attempt_count: int
    last_error: str | None


class M3ExecutionRepository:
    """One durable dispatch claim per decision; repeated claims never resubmit."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def prepare(
        self,
        *,
        lineage: M3DecisionLineage,
        mandate: ExecutionMandate,
    ) -> M3ExecutionCheckpoint:
        decision = lineage.investment_decision
        mandate.assert_matches_decision(decision)
        now = utc_naive_now()
        row = SingleBrainM3ExecutionRecord(
            decision_id=decision.decision_id,
            cycle_id=decision.decision_cycle_id,
            symbol=decision.symbol,
            status="PREPARED",
            source_report_id=lineage.source_report_id,
            mandate_id=mandate.mandate_id,
            mandate_hash=mandate.content_hash,
            idempotency_key=mandate.idempotency_key,
            mandate_json=mandate.canonical_json(),
            lineage_json=lineage.to_json(),
            results_json="[]",
            dispatch_attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        with self.db.get_session() as session:
            existing = session.get(SingleBrainM3ExecutionRecord, decision.decision_id)
            if existing is None:
                session.add(row)
                try:
                    session.commit()
                    return self._checkpoint(row)
                except IntegrityError:
                    session.rollback()
                    existing = session.get(
                        SingleBrainM3ExecutionRecord,
                        decision.decision_id,
                    )
                    if existing is None:
                        raise
            self._validate_same(existing, row)
            return self._checkpoint(existing)

    def claim_dispatch(self, decision_id: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                update(SingleBrainM3ExecutionRecord)
                .where(
                    SingleBrainM3ExecutionRecord.decision_id == decision_id,
                    SingleBrainM3ExecutionRecord.status == "PREPARED",
                    SingleBrainM3ExecutionRecord.dispatch_attempt_count == 0,
                )
                .values(
                    status="DISPATCHING",
                    dispatch_attempt_count=1,
                    updated_at=utc_naive_now(),
                )
            )
            return result.rowcount == 1

    def record_observation(
        self,
        *,
        decision_id: str,
        result: ExecutionResult,
        snapshot_b: PortfolioSnapshot,
    ) -> M3ExecutionCheckpoint:
        with self.db.session_scope() as session:
            row = session.get(SingleBrainM3ExecutionRecord, decision_id)
            if row is None:
                raise RuntimeError("M3 execution checkpoint is unavailable")
            mandate = ExecutionMandate.model_validate_json(row.mandate_json)
            if (
                result.decision_id != decision_id
                or result.mandate_id != mandate.mandate_id
                or result.mandate_hash != mandate.content_hash
                or result.portfolio_snapshot_after_id != snapshot_b.snapshot_id
                or result.portfolio_snapshot_after_hash != snapshot_b.content_hash
            ):
                raise ValueError("M3 execution observation lineage mismatch")
            payloads = json.loads(row.results_json)
            if not any(item.get("result_id") == result.result_id for item in payloads):
                payloads.append(json.loads(result.canonical_json()))
            row.results_json = _contract_json(payloads)
            row.snapshot_b_id = snapshot_b.snapshot_id
            row.snapshot_b_hash = snapshot_b.content_hash
            row.snapshot_b_json = snapshot_b.canonical_json()
            row.status = (
                "COMPLETED"
                if result.status in TERMINAL_EXECUTION_STATUSES
                else "PENDING_RECONCILIATION"
            )
            row.last_error = None
            row.updated_at = utc_naive_now()
            if row.status == "COMPLETED":
                row.completed_at = row.updated_at
        return self.get(decision_id)

    def record_uncertain(self, *, decision_id: str, reason: str) -> None:
        with self.db.session_scope() as session:
            row = session.get(SingleBrainM3ExecutionRecord, decision_id)
            if row is None:
                raise RuntimeError("M3 execution checkpoint is unavailable")
            row.status = "PENDING_RECONCILIATION"
            row.last_error = str(reason)[:2000]
            row.updated_at = utc_naive_now()

    def get(self, decision_id: str) -> M3ExecutionCheckpoint:
        with self.db.get_session() as session:
            row = session.get(SingleBrainM3ExecutionRecord, decision_id)
            if row is None:
                raise KeyError(decision_id)
            return self._checkpoint(row)

    def pending(self) -> tuple[M3ExecutionCheckpoint, ...]:
        with self.db.get_session() as session:
            rows = tuple(
                session.execute(
                    select(SingleBrainM3ExecutionRecord)
                    .where(
                        SingleBrainM3ExecutionRecord.status.in_((
                            "DISPATCHING",
                            "PENDING_RECONCILIATION",
                        ))
                    )
                    .order_by(SingleBrainM3ExecutionRecord.created_at)
                ).scalars()
            )
            return tuple(self._checkpoint(row) for row in rows)

    def readiness(self) -> dict[str, Any]:
        with self.db.get_session() as session:
            rows = tuple(
                session.execute(
                    select(SingleBrainM3ExecutionRecord)
                    .order_by(SingleBrainM3ExecutionRecord.created_at.desc())
                    .limit(20)
                ).scalars()
            )
        pending = sum(
            row.status in {"DISPATCHING", "PENDING_RECONCILIATION"}
            for row in rows
        )
        latest = rows[0] if rows else None
        return {
            "pending_execution_count": pending,
            "latest_execution_state": None if latest is None else latest.status,
            "latest_execution_decision_id": None if latest is None else latest.decision_id,
            "latest_execution_mandate_id": None if latest is None else latest.mandate_id,
            "latest_dispatch_attempt_count": (
                None if latest is None else int(latest.dispatch_attempt_count or 0)
            ),
        }

    @staticmethod
    def _validate_same(existing, proposed) -> None:
        for name in (
            "cycle_id",
            "symbol",
            "source_report_id",
            "mandate_id",
            "mandate_hash",
            "idempotency_key",
            "mandate_json",
            "lineage_json",
        ):
            if getattr(existing, name) != getattr(proposed, name):
                raise ValueError("M3 immutable execution checkpoint mismatch")

    @staticmethod
    def _checkpoint(row) -> M3ExecutionCheckpoint:
        mandate = ExecutionMandate.model_validate_json(row.mandate_json)
        lineage = M3DecisionLineage.from_json(row.lineage_json)
        results_payload = json.loads(row.results_json)
        results = tuple(
            ExecutionResult.model_validate_json(_contract_json(item))
            for item in results_payload
        )
        snapshot_b = (
            None
            if not row.snapshot_b_json
            else PortfolioSnapshot.model_validate_json(row.snapshot_b_json)
        )
        if (
            mandate.decision_id != row.decision_id
            or mandate.content_hash != row.mandate_hash
            or mandate.idempotency_key != row.idempotency_key
            or lineage.investment_decision.decision_id != row.decision_id
        ):
            raise ValueError("persisted M3 checkpoint metadata mismatch")
        return M3ExecutionCheckpoint(
            decision_id=row.decision_id,
            cycle_id=row.cycle_id,
            symbol=row.symbol,
            status=row.status,
            lineage=lineage,
            mandate=mandate,
            results=results,
            portfolio_snapshot_b=snapshot_b,
            dispatch_attempt_count=int(row.dispatch_attempt_count or 0),
            last_error=row.last_error,
        )
