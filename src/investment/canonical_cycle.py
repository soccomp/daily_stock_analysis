"""Canonical durable lifecycle for proposal-handoff cycles.

Mission 1 uses this small repository as the source of truth for scheduler
state.  It is intentionally independent from the legacy M2 shadow journal and
does not create, infer, or rewrite downstream investment identities.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import desc, select

from src.storage import (
    CanonicalCycleRecord,
    CanonicalCycleStageRecord,
    DatabaseManager,
    to_utc_naive_datetime,
    utc_naive_now,
)


CANONICAL_CYCLE_SCHEMA_VERSION = "1.0"
CANONICAL_CYCLE_TASK = "single_brain_proposal_handoff"

CYCLE_NON_TERMINAL_STATES = frozenset({"SCHEDULED", "RUNNING"})
CYCLE_TERMINAL_STATES = frozenset(
    {"SUCCEEDED", "PARTIAL", "FAILED", "SKIPPED", "BLOCKED", "NO_ACTION"}
)
CYCLE_STATES = CYCLE_NON_TERMINAL_STATES | CYCLE_TERMINAL_STATES

CANONICAL_CYCLE_STAGES = (
    "SCHEDULER",
    "LOCK",
    "MARKET_REVIEW",
    "MARKET_CONTEXT",
    "RESEARCH_TRIGGER",
    "CANDIDATE_EVALUATION",
    "RESEARCH_BUNDLE",
    "INVESTMENT_PROPOSAL",
    "ATHENA_HANDOFF_ACK",
)
STAGE_STATES = frozenset(
    {"NOT_ENTERED", "ENTERED", "SUCCEEDED", "FAILED", "BLOCKED", "NO_ACTION", "SKIPPED", "PARTIAL"}
)
STAGE_TERMINAL_STATES = frozenset(
    {"SUCCEEDED", "FAILED", "BLOCKED", "NO_ACTION", "SKIPPED", "PARTIAL"}
)
CURRENT_WORK_STATES = frozenset(
    {"RUNNING", "SUCCEEDED", "FAILED", "BLOCKED", "DEFERRED", "NO_ACTION", "IDLE"}
)


class CanonicalCycleConflictError(RuntimeError):
    """A stable cycle or stage identity was reused with different facts."""


def _bounded_detail(value: object, *, limit: int = 1200) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized[:limit] or None


def _normalize_ids(values: Iterable[object]) -> tuple[str, ...]:
    normalized = tuple(str(value or "").strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError("canonical cycle IDs cannot contain blank values")
    if len(normalized) != len(set(normalized)):
        raise ValueError("canonical cycle IDs cannot contain duplicates")
    return normalized


class CanonicalCycleRepository:
    """Idempotent persistence and read projection for canonical cycles."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def start_cycle(
        self,
        *,
        cycle_id: str,
        scheduler_task_name: str,
        scheduled_for: datetime,
        source_runtime_identity: str,
        cycle_slot: datetime | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        cycle_id = self._required(cycle_id, "cycle_id")
        scheduler_task_name = self._required(scheduler_task_name, "scheduler_task_name")
        source_runtime_identity = self._required(
            source_runtime_identity, "source_runtime_identity"
        )
        scheduled = to_utc_naive_datetime(scheduled_for)
        slot = to_utc_naive_datetime(cycle_slot or scheduled_for)
        observed = to_utc_naive_datetime(now or datetime.now(timezone.utc))
        with self.db.session_scope() as session:
            row = session.get(CanonicalCycleRecord, cycle_id)
            if row is None:
                row = CanonicalCycleRecord(
                    cycle_id=cycle_id,
                    schema_version=CANONICAL_CYCLE_SCHEMA_VERSION,
                    scheduler_task_name=scheduler_task_name,
                    scheduled_for=scheduled,
                    cycle_slot=slot,
                    created_at=observed,
                    started_at=observed,
                    status="RUNNING",
                    research_trigger_ids_json="[]",
                    proposal_ids_json="[]",
                    acknowledgement_ids_json="[]",
                    candidate_outcomes_json="[]",
                    source_runtime_identity=source_runtime_identity,
                    updated_at=observed,
                )
                session.add(row)
            else:
                self._assert_cycle_identity(
                    row,
                    scheduler_task_name=scheduler_task_name,
                    cycle_slot=slot,
                    source_runtime_identity=source_runtime_identity,
                )
                if row.status in CYCLE_NON_TERMINAL_STATES:
                    row.status = "RUNNING"
                    row.started_at = row.started_at or observed
                    row.updated_at = observed
            return self._cycle_payload(row)

    def set_stage(
        self,
        *,
        cycle_id: str,
        stage: str,
        state: str,
        object_id: str | None = None,
        object_ids: Iterable[object] = (),
        parent_ref: str | None = None,
        reason_code: str | None = None,
        reason_detail: object | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        if stage not in CANONICAL_CYCLE_STAGES:
            raise ValueError(f"unsupported canonical cycle stage: {stage}")
        if state not in STAGE_STATES:
            raise ValueError(f"unsupported canonical cycle stage state: {state}")
        cycle_id = self._required(cycle_id, "cycle_id")
        object_id = str(object_id or "").strip() or None
        object_ids_tuple = _normalize_ids(object_ids)
        if object_id and object_ids_tuple:
            raise ValueError("canonical stage accepts object_id or object_ids, not both")
        parent_ref = str(parent_ref or "").strip() or None
        reason_code = str(reason_code or "").strip() or None
        bounded_reason = _bounded_detail(reason_detail)
        observed = to_utc_naive_datetime(at or datetime.now(timezone.utc))
        stage_event_id = f"{cycle_id}:{stage}"

        with self.db.session_scope() as session:
            cycle = session.get(CanonicalCycleRecord, cycle_id)
            if cycle is None:
                raise CanonicalCycleConflictError(f"unknown canonical cycle: {cycle_id}")
            row = session.get(CanonicalCycleStageRecord, stage_event_id)
            if row is None:
                row = CanonicalCycleStageRecord(
                    stage_event_id=stage_event_id,
                    cycle_id=cycle_id,
                    stage=stage,
                    state=state,
                    entered_at=observed,
                    completed_at=observed if state in STAGE_TERMINAL_STATES else None,
                    object_id=object_id,
                    object_ids_json=json.dumps(
                        list(object_ids_tuple), ensure_ascii=False, separators=(",", ":")
                    ),
                    parent_ref=parent_ref,
                    reason_code=reason_code,
                    reason_detail=bounded_reason,
                    created_at=observed,
                    updated_at=observed,
                )
                session.add(row)
            elif cycle.status in CYCLE_TERMINAL_STATES:
                if not self._same_stage_facts(
                    row,
                    state=state,
                    object_id=object_id,
                    object_ids=object_ids_tuple,
                    parent_ref=parent_ref,
                    reason_code=reason_code,
                ):
                    raise CanonicalCycleConflictError(
                        f"terminal cycle stage was reused with different facts: {stage_event_id}"
                    )
                return self._stage_payload(row)
            else:
                if row.state in STAGE_TERMINAL_STATES and row.state != state:
                    raise CanonicalCycleConflictError(
                        f"terminal stage cannot transition: {stage_event_id}"
                    )
                row.state = state
                row.completed_at = (
                    observed if state in STAGE_TERMINAL_STATES else row.completed_at
                )
                row.object_id = object_id or row.object_id
                if object_ids_tuple:
                    row.object_ids_json = json.dumps(
                        list(object_ids_tuple), ensure_ascii=False, separators=(",", ":")
                    )
                row.parent_ref = parent_ref or row.parent_ref
                row.reason_code = reason_code or row.reason_code
                row.reason_detail = bounded_reason or row.reason_detail
                row.updated_at = observed

            if state != "NOT_ENTERED":
                cycle.current_stage = stage
                cycle.current_stage_at = observed
                cycle.current_symbol_or_scope = None
                cycle.current_work_state = state
            cycle.updated_at = observed
            return self._stage_payload(row)

    def set_current_work(
        self,
        *,
        cycle_id: str,
        stage: str,
        symbol_or_scope: str | None,
        work_state: str,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist the live unit of work without rewriting stage facts."""

        if stage not in CANONICAL_CYCLE_STAGES:
            raise ValueError(f"unsupported canonical cycle stage: {stage}")
        if work_state not in CURRENT_WORK_STATES:
            raise ValueError(f"unsupported canonical current work state: {work_state}")
        observed = to_utc_naive_datetime(at or datetime.now(timezone.utc))
        normalized_scope = str(symbol_or_scope or "").strip() or None
        with self.db.session_scope() as session:
            row = session.get(CanonicalCycleRecord, self._required(cycle_id, "cycle_id"))
            if row is None:
                raise CanonicalCycleConflictError(f"unknown canonical cycle: {cycle_id}")
            if row.status in CYCLE_TERMINAL_STATES:
                return self._cycle_payload(row)
            row.current_stage = stage
            row.current_stage_at = observed
            row.current_symbol_or_scope = normalized_scope
            row.current_work_state = work_state
            row.updated_at = observed
            return self._cycle_payload(row)

    def update_identity_and_counts(
        self,
        *,
        cycle_id: str,
        market_review_id: str | None = None,
        market_context_id: str | None = None,
        candidate_count: int | None = None,
        proposal_count: int | None = None,
        ack_count: int | None = None,
        no_action_count: int | None = None,
        blocked_count: int | None = None,
        failed_count: int | None = None,
        deferred_count: int | None = None,
        cycle_deadline: datetime | None = None,
        candidate_reserve_seconds: int | None = None,
        research_trigger_ids: Iterable[object] | None = None,
        proposal_ids: Iterable[object] | None = None,
        acknowledgement_ids: Iterable[object] | None = None,
        candidate_outcomes: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self.db.session_scope() as session:
            row = session.get(CanonicalCycleRecord, self._required(cycle_id, "cycle_id"))
            if row is None:
                raise CanonicalCycleConflictError(f"unknown canonical cycle: {cycle_id}")
            if row.status in CYCLE_TERMINAL_STATES:
                return self._cycle_payload(row)
            if market_review_id is not None:
                row.market_review_id = str(market_review_id).strip() or None
            if market_context_id is not None:
                row.market_context_id = str(market_context_id).strip() or None
            for field, value in (
                ("candidate_count", candidate_count),
                ("proposal_count", proposal_count),
                ("ack_count", ack_count),
                ("no_action_count", no_action_count),
                ("blocked_count", blocked_count),
                ("failed_count", failed_count),
                ("deferred_count", deferred_count),
            ):
                if value is not None:
                    if int(value) < 0:
                        raise ValueError(f"{field} cannot be negative")
                    setattr(row, field, int(value))
            if cycle_deadline is not None:
                row.cycle_deadline = to_utc_naive_datetime(cycle_deadline)
            if candidate_reserve_seconds is not None:
                if int(candidate_reserve_seconds) < 0:
                    raise ValueError("candidate_reserve_seconds cannot be negative")
                row.candidate_reserve_seconds = int(candidate_reserve_seconds)
            for field, values in (
                ("research_trigger_ids_json", research_trigger_ids),
                ("proposal_ids_json", proposal_ids),
                ("acknowledgement_ids_json", acknowledgement_ids),
            ):
                if values is not None:
                    setattr(
                        row,
                        field,
                        json.dumps(
                            list(_normalize_ids(values)),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
            if candidate_outcomes is not None:
                bounded = []
                for outcome in candidate_outcomes:
                    if not isinstance(outcome, dict):
                        raise ValueError("candidate outcome must be an object")
                    bounded.append(
                        {
                            str(key): _bounded_detail(value, limit=500)
                            for key, value in outcome.items()
                        }
                    )
                row.candidate_outcomes_json = json.dumps(
                    bounded, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            row.updated_at = utc_naive_now()
            return self._cycle_payload(row)

    def record_lock(
        self,
        *,
        cycle_id: str,
        acquired_at: datetime | None = None,
        released_at: datetime | None = None,
    ) -> dict[str, Any]:
        with self.db.session_scope() as session:
            row = session.get(CanonicalCycleRecord, self._required(cycle_id, "cycle_id"))
            if row is None:
                raise CanonicalCycleConflictError(f"unknown canonical cycle: {cycle_id}")
            if row.status in CYCLE_TERMINAL_STATES:
                if acquired_at is not None:
                    acquired = to_utc_naive_datetime(acquired_at)
                    if row.lock_acquired_at not in (None, acquired):
                        raise CanonicalCycleConflictError(
                            f"lock acquisition fact cannot be rewritten: {row.cycle_id}"
                        )
                    row.lock_acquired_at = acquired
                if released_at is not None:
                    released = to_utc_naive_datetime(released_at)
                    if row.lock_acquired_at is None:
                        raise CanonicalCycleConflictError(
                            f"lock release requires acquisition fact: {row.cycle_id}"
                        )
                    if row.ended_at is not None and released < row.ended_at:
                        raise CanonicalCycleConflictError(
                            f"lock release precedes cycle end: {row.cycle_id}"
                        )
                    if row.lock_released_at not in (None, released):
                        raise CanonicalCycleConflictError(
                            f"lock release fact cannot be rewritten: {row.cycle_id}"
                        )
                    row.lock_released_at = released
                row.updated_at = utc_naive_now()
                return self._cycle_payload(row)
            if acquired_at is not None:
                row.lock_acquired_at = to_utc_naive_datetime(acquired_at)
            if released_at is not None:
                released = to_utc_naive_datetime(released_at)
                if row.lock_acquired_at is None:
                    raise CanonicalCycleConflictError(
                        f"lock release requires acquisition fact: {row.cycle_id}"
                    )
                row.lock_released_at = released
            row.updated_at = utc_naive_now()
            return self._cycle_payload(row)

    def finish_cycle(
        self,
        *,
        cycle_id: str,
        status: str,
        terminal_reason_code: str,
        terminal_reason_detail: object | None = None,
        ended_at: datetime | None = None,
        lock_released_at: datetime | None = None,
    ) -> dict[str, Any]:
        if status not in CYCLE_TERMINAL_STATES:
            raise ValueError(f"cycle status is not terminal: {status}")
        cycle_id = self._required(cycle_id, "cycle_id")
        reason_code = self._required(terminal_reason_code, "terminal_reason_code")
        ended = to_utc_naive_datetime(ended_at or datetime.now(timezone.utc))
        bounded_reason = _bounded_detail(terminal_reason_detail)
        with self.db.session_scope() as session:
            row = session.get(CanonicalCycleRecord, cycle_id)
            if row is None:
                raise CanonicalCycleConflictError(f"unknown canonical cycle: {cycle_id}")
            if row.status in CYCLE_TERMINAL_STATES:
                if row.status != status or row.terminal_reason_code != reason_code:
                    raise CanonicalCycleConflictError(
                        f"terminal cycle meaning cannot be rewritten: {cycle_id}"
                    )
                if lock_released_at is not None:
                    released = to_utc_naive_datetime(lock_released_at)
                    if row.lock_acquired_at is None:
                        raise CanonicalCycleConflictError(
                            f"lock release requires acquisition fact: {cycle_id}"
                        )
                    if row.ended_at is not None and released < row.ended_at:
                        raise CanonicalCycleConflictError(
                            f"lock release precedes cycle end: {cycle_id}"
                        )
                    if row.lock_released_at not in (None, released):
                        raise CanonicalCycleConflictError(
                            f"lock release fact cannot be rewritten: {cycle_id}"
                        )
                    row.lock_released_at = released
                    row.updated_at = utc_naive_now()
                return self._cycle_payload(row)
            row.status = status
            row.terminal_reason_code = reason_code
            row.terminal_reason_detail = bounded_reason
            row.ended_at = ended
            if lock_released_at is not None:
                released = to_utc_naive_datetime(lock_released_at)
                if row.lock_acquired_at is None:
                    raise CanonicalCycleConflictError(
                        f"lock release requires acquisition fact: {cycle_id}"
                    )
                if released < ended:
                    raise CanonicalCycleConflictError(
                        f"lock release precedes cycle end: {cycle_id}"
                    )
                row.lock_released_at = released
            row.updated_at = ended
            return self._cycle_payload(row)

    def get_cycle(self, cycle_id: str) -> dict[str, Any] | None:
        with self.db.get_session() as session:
            row = session.get(CanonicalCycleRecord, str(cycle_id))
            return None if row is None else self._cycle_payload(row)

    def stage_events(self, cycle_id: str) -> tuple[dict[str, Any], ...]:
        with self.db.get_session() as session:
            rows = tuple(
                session.execute(
                    select(CanonicalCycleStageRecord)
                    .where(CanonicalCycleStageRecord.cycle_id == str(cycle_id))
                    .order_by(CanonicalCycleStageRecord.created_at)
                ).scalars()
            )
        return tuple(self._stage_payload(row) for row in rows)

    def scheduler_projection(self, *, scheduler_task_name: str) -> dict[str, Any]:
        """Return a pure read model for scheduler/API consumers."""

        with self.db.get_session() as session:
            rows = tuple(
                session.execute(
                    select(CanonicalCycleRecord)
                    .where(
                        CanonicalCycleRecord.scheduler_task_name
                        == str(scheduler_task_name)
                    )
                    .order_by(desc(CanonicalCycleRecord.started_at), desc(CanonicalCycleRecord.created_at))
                ).scalars()
            )
        current = next(
            (row for row in rows if row.status in CYCLE_NON_TERMINAL_STATES), None
        )
        terminal = next(
            (row for row in rows if row.status in CYCLE_TERMINAL_STATES), None
        )
        latest = rows[0] if rows else None
        now = utc_naive_now()
        return {
            "current_cycle_id": current.cycle_id if current else None,
            "current_status": current.status if current else None,
            "current_stage": current.current_stage if current else None,
            "current_symbol_or_scope": (
                current.current_symbol_or_scope if current else None
            ),
            "current_work_state": current.current_work_state if current else None,
            "current_scheduled_for": (
                self._iso(current.scheduled_for) if current else None
            ),
            "current_cycle_slot": self._iso(current.cycle_slot) if current else None,
            "started_at": self._iso(current.started_at) if current else None,
            "elapsed_seconds": (
                max(0, int((now - current.started_at).total_seconds()))
                if current is not None and current.started_at is not None
                else None
            ),
            "cycle_deadline": self._iso(current.cycle_deadline) if current else None,
            "remaining_seconds": (
                max(0, int((current.cycle_deadline - now).total_seconds()))
                if current is not None and current.cycle_deadline is not None
                else None
            ),
            "candidate_count": int(current.candidate_count or 0) if current else 0,
            "proposal_count": int(current.proposal_count or 0) if current else 0,
            "deferred_count": int(current.deferred_count or 0) if current else 0,
            "failed_count": int(current.failed_count or 0) if current else 0,
            "last_terminal_cycle_id": terminal.cycle_id if terminal else None,
            "last_terminal_status": terminal.status if terminal else None,
            "last_terminal_reason": (
                None
                if terminal is None
                else {
                    "code": terminal.terminal_reason_code,
                    "detail": terminal.terminal_reason_detail,
                }
            ),
            "last_run_at": self._iso(latest.started_at) if latest else None,
            "last_success_at": self._iso(
                next(
                    (
                        row.ended_at
                        for row in rows
                        if row.status in {"SUCCEEDED", "NO_ACTION"}
                    ),
                    None,
                )
            ),
            "last_error": self._last_error(rows),
            "last_skipped_at": self._iso(
                next((row.ended_at for row in rows if row.status == "SKIPPED"), None)
            ),
            "last_skip_reason": self._skip_reason(rows),
        }

    @staticmethod
    def _required(value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} is required")
        return normalized

    @staticmethod
    def _assert_cycle_identity(
        row: CanonicalCycleRecord,
        *,
        scheduler_task_name: str,
        cycle_slot: datetime,
        source_runtime_identity: str,
    ) -> None:
        if (
            row.scheduler_task_name != scheduler_task_name
            or row.cycle_slot != cycle_slot
            or row.source_runtime_identity != source_runtime_identity
        ):
            raise CanonicalCycleConflictError(
                f"cycle identity metadata mismatch: {row.cycle_id}"
            )

    @staticmethod
    def _same_stage_facts(
        row: CanonicalCycleStageRecord,
        *,
        state: str,
        object_id: str | None,
        object_ids: tuple[str, ...],
        parent_ref: str | None,
        reason_code: str | None,
    ) -> bool:
        try:
            stored_ids = tuple(json.loads(row.object_ids_json or "[]"))
        except (TypeError, ValueError):
            stored_ids = ()
        return (
            row.state == state
            and row.object_id == object_id
            and stored_ids == object_ids
            and row.parent_ref == parent_ref
            and row.reason_code == reason_code
        )

    @classmethod
    def _cycle_payload(cls, row: CanonicalCycleRecord) -> dict[str, Any]:
        def _ids(value: str | None) -> list[str]:
            try:
                parsed = json.loads(value or "[]")
            except (TypeError, ValueError):
                return []
            return [str(item) for item in parsed] if isinstance(parsed, list) else []

        try:
            outcomes = json.loads(row.candidate_outcomes_json or "[]")
        except (TypeError, ValueError):
            outcomes = []
        return {
            "cycle_id": row.cycle_id,
            "schema_version": row.schema_version,
            "scheduler_task_name": row.scheduler_task_name,
            "scheduled_for": cls._iso(row.scheduled_for),
            "cycle_slot": cls._iso(row.cycle_slot),
            "created_at": cls._iso(row.created_at),
            "started_at": cls._iso(row.started_at),
            "ended_at": cls._iso(row.ended_at),
            "lock_acquired_at": cls._iso(row.lock_acquired_at),
            "lock_released_at": cls._iso(row.lock_released_at),
            "status": row.status,
            "terminal_reason_code": row.terminal_reason_code,
            "terminal_reason_detail": row.terminal_reason_detail,
            "current_stage": row.current_stage,
            "current_stage_at": cls._iso(row.current_stage_at),
            "current_symbol_or_scope": row.current_symbol_or_scope,
            "current_work_state": row.current_work_state,
            "last_error": row.last_error,
            "market_review_id": row.market_review_id,
            "market_context_id": row.market_context_id,
            "candidate_count": int(row.candidate_count or 0),
            "proposal_count": int(row.proposal_count or 0),
            "ack_count": int(row.ack_count or 0),
            "no_action_count": int(row.no_action_count or 0),
            "blocked_count": int(row.blocked_count or 0),
            "failed_count": int(row.failed_count or 0),
            "deferred_count": int(row.deferred_count or 0),
            "cycle_deadline": cls._iso(row.cycle_deadline),
            "candidate_reserve_seconds": row.candidate_reserve_seconds,
            "research_trigger_ids": _ids(row.research_trigger_ids_json),
            "proposal_ids": _ids(row.proposal_ids_json),
            "acknowledgement_ids": _ids(row.acknowledgement_ids_json),
            "candidate_outcomes": outcomes if isinstance(outcomes, list) else [],
            "source_runtime_identity": row.source_runtime_identity,
            "updated_at": cls._iso(row.updated_at),
        }

    @classmethod
    def _stage_payload(cls, row: CanonicalCycleStageRecord) -> dict[str, Any]:
        try:
            object_ids = json.loads(row.object_ids_json or "[]")
        except (TypeError, ValueError):
            object_ids = []
        return {
            "stage_event_id": row.stage_event_id,
            "cycle_id": row.cycle_id,
            "stage": row.stage,
            "state": row.state,
            "entered_at": cls._iso(row.entered_at),
            "completed_at": cls._iso(row.completed_at),
            "object_id": row.object_id,
            "object_ids": object_ids if isinstance(object_ids, list) else [],
            "parent_ref": row.parent_ref,
            "reason_code": row.reason_code,
            "reason_detail": row.reason_detail,
            "created_at": cls._iso(row.created_at),
            "updated_at": cls._iso(row.updated_at),
        }

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

    @classmethod
    def _last_error(cls, rows: tuple[CanonicalCycleRecord, ...]) -> str | None:
        for row in rows:
            if row.status in {"FAILED", "BLOCKED"}:
                return row.terminal_reason_detail or row.last_error
        return None

    @classmethod
    def _skip_reason(cls, rows: tuple[CanonicalCycleRecord, ...]) -> str | None:
        for row in rows:
            if row.status == "SKIPPED":
                return row.terminal_reason_code
        return None


def canonical_terminal_for_result(
    *,
    result_status: str,
    blocked_reasons: Iterable[object] = (),
) -> tuple[str, str]:
    """Map legacy handoff results to non-overlapping canonical terminal states."""

    reasons = tuple(str(reason or "") for reason in blocked_reasons)
    if result_status == "COMPLETED":
        return "SUCCEEDED", "PROPOSAL_HANDOFF_COMPLETE"
    if result_status == "NO_ACTION":
        return "NO_ACTION", "NO_CANDIDATE_OR_NO_ACTION_OUTCOME"
    if result_status == "PARTIAL":
        return "PARTIAL", "CANDIDATE_PROCESSING_PARTIAL"
    if result_status == "DISABLED":
        return "SKIPPED", "HANDOFF_DISABLED"
    if result_status == "FAILED_CLOSED":
        lowered = " ".join(reasons).lower()
        if "cycle_budget_overrun" in lowered:
            return "BLOCKED", "CYCLE_BUDGET_EXHAUSTED"
        if any(token in lowered for token in ("lock", "market review", "market context", "dependency", "required")):
            return "BLOCKED", "REQUIRED_DEPENDENCY_BLOCKED"
        return "FAILED", "CYCLE_FAILED_CLOSED"
    return "FAILED", "UNEXPECTED_RESULT_STATUS"
