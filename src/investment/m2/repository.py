"""Small durable operational journal for M2 cycle dedupe and recovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError

from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.storage import (
    DatabaseManager,
    SingleBrainM2CycleRecord,
    SingleBrainM2SymbolRecord,
    to_utc_naive_datetime,
    utc_naive_now,
)


class M2InputConflictError(RuntimeError):
    """The same deterministic cycle was observed with different authority inputs."""


@dataclass(frozen=True)
class CycleClaim:
    cycle_id: str
    status: str
    created: bool
    duplicate_trigger_count: int
    recovery_count: int


@dataclass(frozen=True)
class SymbolClaim:
    status: str
    created: bool
    decision_id: str | None


@dataclass(frozen=True)
class AuthorityMirror:
    snapshot_json: str
    risk_policy_json: str
    input_hash: str
    symbols: tuple[dict[str, str], ...]


class M2OperationalRepository:
    """Persist scheduler checkpoints without duplicating scorecard lineage."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def claim_cycle(
        self,
        *,
        cycle_id: str,
        account_id: str,
        scheduled_for: datetime,
    ) -> CycleClaim:
        scheduled = to_utc_naive_datetime(scheduled_for)
        now = utc_naive_now()
        with self.db.get_session() as session:
            row = session.get(SingleBrainM2CycleRecord, cycle_id)
            if row is None:
                row = SingleBrainM2CycleRecord(
                    cycle_id=cycle_id,
                    account_id=account_id,
                    scheduled_for=scheduled,
                    status="STARTED",
                    symbols_json="[]",
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                try:
                    session.commit()
                    return CycleClaim(cycle_id, "STARTED", True, 0, 0)
                except IntegrityError:
                    session.rollback()
                    row = session.get(SingleBrainM2CycleRecord, cycle_id)
                    if row is None:
                        raise
            if row.account_id != account_id or row.scheduled_for != scheduled:
                raise M2InputConflictError("cycle identity metadata mismatch")
            row.duplicate_trigger_count = int(row.duplicate_trigger_count or 0) + 1
            if row.status != "COMPLETED":
                row.recovery_count = int(row.recovery_count or 0) + 1
            row.updated_at = now
            session.commit()
            return CycleClaim(
                cycle_id,
                str(row.status),
                False,
                int(row.duplicate_trigger_count or 0),
                int(row.recovery_count or 0),
            )

    def bind_authority_inputs(
        self,
        *,
        cycle_id: str,
        input_hash: str,
        snapshot_id: str,
        snapshot_hash: str,
        snapshot_json: str,
        snapshot_as_of: datetime,
        reconciliation_status: str,
        risk_policy_id: str,
        risk_policy_version: str,
        risk_policy_hash: str,
        risk_policy_json: str,
        symbols: list[dict[str, str]],
    ) -> None:
        symbols_json = json.dumps(
            symbols,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self.db.session_scope() as session:
            row = session.get(SingleBrainM2CycleRecord, cycle_id)
            if row is None:
                raise RuntimeError("M2 cycle is not claimed")
            if row.input_hash and row.input_hash != input_hash:
                raise M2InputConflictError(
                    "authoritative snapshot or RiskPolicy changed inside one cycle"
                )
            if row.input_hash:
                if (
                    row.snapshot_id != snapshot_id
                    or row.snapshot_hash != snapshot_hash
                    or row.snapshot_json != snapshot_json
                    or row.risk_policy_id != risk_policy_id
                    or row.risk_policy_version != risk_policy_version
                    or row.risk_policy_hash != risk_policy_hash
                    or row.risk_policy_json != risk_policy_json
                    or row.symbols_json != symbols_json
                ):
                    raise M2InputConflictError(
                        "immutable M2 authority mirror or symbol set changed"
                    )
                row.status = "RUNNING"
                row.failure_reason = None
                row.updated_at = utc_naive_now()
                return
            row.input_hash = input_hash
            row.snapshot_id = snapshot_id
            row.snapshot_hash = snapshot_hash
            row.snapshot_json = snapshot_json
            row.snapshot_as_of = to_utc_naive_datetime(snapshot_as_of)
            row.reconciliation_status = reconciliation_status
            row.risk_policy_id = risk_policy_id
            row.risk_policy_version = risk_policy_version
            row.risk_policy_hash = risk_policy_hash
            row.risk_policy_json = risk_policy_json
            row.symbols_json = symbols_json
            row.status = "RUNNING"
            row.failure_reason = None
            row.updated_at = utc_naive_now()

    def load_authority_mirror(self, cycle_id: str) -> AuthorityMirror | None:
        with self.db.get_session() as session:
            row = session.get(SingleBrainM2CycleRecord, cycle_id)
            if (
                row is None
                or not row.input_hash
                or not row.snapshot_json
                or not row.risk_policy_json
            ):
                return None
            try:
                symbols = json.loads(row.symbols_json)
            except (TypeError, json.JSONDecodeError) as exc:
                raise M2InputConflictError("persisted M2 symbol set is invalid") from exc
            if not isinstance(symbols, list) or any(not isinstance(item, dict) for item in symbols):
                raise M2InputConflictError("persisted M2 symbol set is invalid")
            return AuthorityMirror(
                snapshot_json=row.snapshot_json,
                risk_policy_json=row.risk_policy_json,
                input_hash=row.input_hash,
                symbols=tuple(dict(item) for item in symbols),
            )

    def claim_symbol(
        self,
        *,
        cycle_id: str,
        symbol: str,
        source_kind: str,
        analysis_query_id: str,
    ) -> SymbolClaim:
        now = utc_naive_now()
        with self.db.get_session() as session:
            row = session.execute(
                select(SingleBrainM2SymbolRecord).where(
                    SingleBrainM2SymbolRecord.cycle_id == cycle_id,
                    SingleBrainM2SymbolRecord.symbol == symbol,
                )
            ).scalar_one_or_none()
            if row is None:
                row = SingleBrainM2SymbolRecord(
                    cycle_id=cycle_id,
                    symbol=symbol,
                    source_kind=source_kind,
                    status="STARTED",
                    analysis_query_id=analysis_query_id,
                    updated_at=now,
                )
                session.add(row)
                try:
                    session.commit()
                    return SymbolClaim("STARTED", True, None)
                except IntegrityError:
                    session.rollback()
                    row = session.execute(
                        select(SingleBrainM2SymbolRecord).where(
                            SingleBrainM2SymbolRecord.cycle_id == cycle_id,
                            SingleBrainM2SymbolRecord.symbol == symbol,
                        )
                    ).scalar_one()
            if row.analysis_query_id != analysis_query_id:
                raise M2InputConflictError("symbol analysis identity mismatch")
            return SymbolClaim(str(row.status), False, row.decision_id)

    def mark_symbol_analyzed(
        self,
        *,
        cycle_id: str,
        symbol: str,
        source_report_id: int,
    ) -> None:
        self._update_symbol(
            cycle_id,
            symbol,
            status="ANALYZED",
            source_report_id=source_report_id,
            failure_reason=None,
        )

    def mark_symbol_persisted(
        self,
        *,
        cycle_id: str,
        symbol: str,
        source_report_id: int,
        research_id: str,
        decision_id: str,
        decision_action: str,
        rationale_summary: str,
    ) -> None:
        self._update_symbol(
            cycle_id,
            symbol,
            status="PERSISTED",
            source_report_id=source_report_id,
            research_id=research_id,
            decision_id=decision_id,
            decision_action=decision_action,
            rationale_summary=rationale_summary[:2000],
            failure_reason=None,
            persisted_at=utc_naive_now(),
        )

    def mark_symbol_failed(
        self,
        *,
        cycle_id: str,
        symbol: str,
        status: str,
        reason: str,
    ) -> None:
        self._update_symbol(
            cycle_id,
            symbol,
            status=status,
            failure_reason=str(reason)[:2000],
        )

    def close_cycle(self, *, cycle_id: str) -> str:
        with self.db.session_scope() as session:
            cycle = session.get(SingleBrainM2CycleRecord, cycle_id)
            if cycle is None:
                raise RuntimeError("M2 cycle is not claimed")
            statuses = list(
                session.execute(
                    select(SingleBrainM2SymbolRecord.status).where(
                        SingleBrainM2SymbolRecord.cycle_id == cycle_id
                    )
                ).scalars()
            )
            persisted = sum(status == "PERSISTED" for status in statuses)
            if statuses and persisted == len(statuses):
                cycle.status = "COMPLETED"
                cycle.failure_reason = None
            elif persisted:
                cycle.status = "PARTIAL"
                cycle.failure_reason = "one or more symbols failed closed"
            else:
                cycle.status = "FAILED_CLOSED"
                cycle.failure_reason = "no shadow decision lineage was persisted"
            cycle.completed_at = utc_naive_now()
            cycle.updated_at = cycle.completed_at
            return str(cycle.status)

    def fail_cycle(self, *, cycle_id: str, reason: str) -> None:
        with self.db.session_scope() as session:
            row = session.get(SingleBrainM2CycleRecord, cycle_id)
            if row is None:
                return
            row.status = "FAILED_CLOSED"
            row.failure_reason = str(reason)[:2000]
            row.completed_at = utc_naive_now()
            row.updated_at = row.completed_at

    def readiness(self) -> dict[str, Any]:
        with self.db.get_session() as session:
            cycle = session.execute(
                select(SingleBrainM2CycleRecord)
                .order_by(desc(SingleBrainM2CycleRecord.scheduled_for))
                .limit(1)
            ).scalar_one_or_none()
            if cycle is None:
                return {
                    "latest_cycle": None,
                    "latest_completed_cycle": None,
                    "symbols": [],
                    "last_successful_shadow_persistence_at": None,
                }
            completed_cycle = session.execute(
                select(SingleBrainM2CycleRecord)
                .where(
                    SingleBrainM2CycleRecord.status.in_(("COMPLETED", "PARTIAL"))
                )
                .order_by(desc(SingleBrainM2CycleRecord.scheduled_for))
                .limit(1)
            ).scalar_one_or_none()
            symbol_cycle_id = (
                completed_cycle.cycle_id
                if completed_cycle is not None
                else cycle.cycle_id
            )
            symbols = list(
                session.execute(
                    select(SingleBrainM2SymbolRecord)
                    .where(SingleBrainM2SymbolRecord.cycle_id == symbol_cycle_id)
                    .order_by(SingleBrainM2SymbolRecord.symbol)
                ).scalars()
            )
            latest_persisted = session.execute(
                select(SingleBrainM2SymbolRecord.persisted_at)
                .where(SingleBrainM2SymbolRecord.persisted_at.is_not(None))
                .order_by(desc(SingleBrainM2SymbolRecord.persisted_at))
                .limit(1)
            ).scalar_one_or_none()
            return {
                "latest_cycle": self._cycle_payload(cycle),
                "latest_completed_cycle": (
                    None
                    if completed_cycle is None
                    else self._cycle_payload(completed_cycle)
                ),
                "symbols": [self._symbol_payload(row) for row in symbols],
                "last_successful_shadow_persistence_at": self._iso(latest_persisted),
            }

    def latest_authoritative_snapshot(self) -> PortfolioSnapshot | None:
        """Return the newest immutable Athena mirror used by any M2 cycle."""

        with self.db.get_session() as session:
            row = session.execute(
                select(SingleBrainM2CycleRecord)
                .where(SingleBrainM2CycleRecord.snapshot_json.is_not(None))
                .order_by(
                    desc(SingleBrainM2CycleRecord.snapshot_as_of),
                    desc(SingleBrainM2CycleRecord.scheduled_for),
                )
                .limit(1)
            ).scalar_one_or_none()
            if row is None or not row.snapshot_json:
                return None
            try:
                snapshot = PortfolioSnapshot.model_validate_json(row.snapshot_json)
            except Exception as exc:
                raise M2InputConflictError(
                    "persisted M2 authoritative snapshot mirror is invalid"
                ) from exc
            if (
                snapshot.snapshot_id != row.snapshot_id
                or snapshot.content_hash != row.snapshot_hash
            ):
                raise M2InputConflictError(
                    "persisted M2 authoritative snapshot metadata mismatch"
                )
            return snapshot

    def _update_symbol(self, cycle_id: str, symbol: str, **values: Any) -> None:
        with self.db.session_scope() as session:
            row = session.execute(
                select(SingleBrainM2SymbolRecord).where(
                    SingleBrainM2SymbolRecord.cycle_id == cycle_id,
                    SingleBrainM2SymbolRecord.symbol == symbol,
                )
            ).scalar_one()
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_naive_now()

    @classmethod
    def _cycle_payload(cls, row: SingleBrainM2CycleRecord) -> dict[str, Any]:
        return {
            "decision_cycle_id": row.cycle_id,
            "account_id": row.account_id,
            "scheduled_for": cls._iso(row.scheduled_for),
            "status": row.status,
            "snapshot_id": row.snapshot_id,
            "snapshot_hash": row.snapshot_hash,
            "snapshot_as_of": cls._iso(row.snapshot_as_of),
            "reconciliation_status": row.reconciliation_status,
            "risk_policy_id": row.risk_policy_id,
            "risk_policy_version": row.risk_policy_version,
            "risk_policy_hash": row.risk_policy_hash,
            "failure_reason": row.failure_reason,
            "duplicate_trigger_count": int(row.duplicate_trigger_count or 0),
            "recovery_count": int(row.recovery_count or 0),
            "completed_at": cls._iso(row.completed_at),
        }

    @classmethod
    def _symbol_payload(cls, row: SingleBrainM2SymbolRecord) -> dict[str, Any]:
        return {
            "symbol": row.symbol,
            "source": row.source_kind,
            "status": row.status,
            "analysis_query_id": row.analysis_query_id,
            "source_report_id": row.source_report_id,
            "research_id": row.research_id,
            "decision_id": row.decision_id,
            "action": row.decision_action,
            "rationale_summary": row.rationale_summary,
            "failure_reason": row.failure_reason,
            "persisted_at": cls._iso(row.persisted_at),
        }

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
