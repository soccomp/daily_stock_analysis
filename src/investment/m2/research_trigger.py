"""Durable PALLAS-004 trigger ledger and holdings-review coverage projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import asc, desc, select

from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.contracts.research_trigger import ResearchTrigger
from src.investment.m2.selection import select_m2_research_objects
from src.storage import (
    DatabaseManager,
    HoldingsReviewCoverageRecord,
    ResearchTriggerLedgerRecord,
    to_utc_naive_datetime,
    utc_naive_now,
)


TRIGGER_POLICY_VERSION = "pallas-004-research-trigger-v1"
TRIGGER_STATUSES = frozenset(
    {"FIRED", "DEDUPLICATED", "SUPPRESSED_COOLDOWN", "SUPERSEDED", "BLOCKED"}
)
REVIEW_STATUSES = frozenset(
    {
        "NOT_DUE",
        "DUE",
        "IN_PROGRESS",
        "COMPLETED",
        "DEFERRED_CAPACITY",
        "BLOCKED_DATA",
        "BLOCKED_RUNTIME",
        "CLOSED",
    }
)


class _UnboundedSelectionConfig:
    """Expose the existing selector's full candidate set before trigger capacity."""

    def __init__(self, config: Any) -> None:
        self._config = config

    def __getattr__(self, name: str) -> Any:
        if name == "single_brain_m2_max_symbols":
            return 50
        if name == "single_brain_m2_holdings_limit":
            return 50
        return getattr(self._config, name)


class ResearchTriggerConflictError(RuntimeError):
    """An idempotency key was reused with different immutable trigger content."""


@dataclass(frozen=True)
class TriggerEnqueueResult:
    trigger: ResearchTrigger
    status: str
    created: bool
    duplicate_count: int


class ResearchTriggerLedgerRepository:
    """Persist trigger facts and outcomes without owning investment decisions."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def enqueue(self, trigger: ResearchTrigger) -> TriggerEnqueueResult:
        if not isinstance(trigger, ResearchTrigger):
            raise TypeError("ResearchTrigger is required")
        now = utc_naive_now()
        with self.db.session_scope() as session:
            row = session.execute(
                select(ResearchTriggerLedgerRecord).where(
                    ResearchTriggerLedgerRecord.dedup_key == trigger.dedup_key
                )
            ).scalar_one_or_none()
            if row is None:
                row = ResearchTriggerLedgerRecord(
                    research_trigger_id=trigger.research_trigger_id,
                    trigger_type=trigger.trigger_type,
                    trigger_source=trigger.trigger_source,
                    symbol=trigger.symbol,
                    market=trigger.market,
                    priority=trigger.priority,
                    created_at=to_utc_naive_datetime(trigger.created_at),
                    source_event_time=to_utc_naive_datetime(trigger.source_event_time)
                    if trigger.source_event_time is not None
                    else None,
                    effective_at=to_utc_naive_datetime(trigger.effective_at),
                    scheduled_for=to_utc_naive_datetime(trigger.scheduled_for),
                    dedup_key=trigger.dedup_key,
                    policy_version=trigger.policy_version,
                    evidence_refs_json=json.dumps(
                        list(trigger.evidence_refs), ensure_ascii=False, separators=(",", ":")
                    ),
                    strategy_evidence_json=(
                        json.dumps(
                            trigger.strategy_evidence.model_dump(mode="json"),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if trigger.strategy_evidence is not None
                        else None
                    ),
                    screening_scheduler_run_id=trigger.screening_scheduler_run_id,
                    screening_run_id=trigger.screening_run_id,
                    portfolio_snapshot_id=trigger.portfolio_snapshot_id,
                    supersedes_trigger_id=trigger.supersedes_trigger_id,
                    content_hash=trigger.content_hash,
                    status="FIRED",
                    status_history_json=json.dumps(["FIRED"]),
                    duplicate_count=0,
                    created_at_ledger=now,
                    last_seen_at=now,
                )
                session.add(row)
                return TriggerEnqueueResult(trigger, "FIRED", True, 0)
            if row.content_hash != trigger.content_hash:
                raise ResearchTriggerConflictError(
                    f"dedup_key reused with different trigger content: {trigger.dedup_key}"
                )
            row.duplicate_count = int(row.duplicate_count or 0) + 1
            if row.processed_at is not None:
                row.status = "DEDUPLICATED"
            history = self._history(row.status_history_json)
            history.append("DEDUPLICATED")
            row.status_history_json = json.dumps(history, separators=(",", ":"))
            row.last_seen_at = now
            return TriggerEnqueueResult(
                trigger,
                "DEDUPLICATED",
                False,
                int(row.duplicate_count or 0),
            )

    def mark_processed(self, trigger_id: str, *, status: str = "FIRED") -> None:
        if status not in TRIGGER_STATUSES:
            raise ValueError(f"unsupported trigger status: {status}")
        with self.db.session_scope() as session:
            row = session.get(ResearchTriggerLedgerRecord, trigger_id)
            if row is None:
                raise ResearchTriggerConflictError(f"unknown trigger: {trigger_id}")
            row.status = status
            row.processed_at = utc_naive_now()
            history = self._history(row.status_history_json)
            if not history or history[-1] != status:
                history.append(status)
            row.status_history_json = json.dumps(history, separators=(",", ":"))

    def mark_blocked(self, trigger_id: str) -> None:
        self.mark_processed(trigger_id, status="BLOCKED")

    def suppress_cooldown(
        self,
        trigger_id: str,
        *,
        cooldown_until: datetime,
        policy_version: str,
    ) -> None:
        """Record only a versioned cooldown window; never invent a hidden timer."""

        with self.db.session_scope() as session:
            row = session.get(ResearchTriggerLedgerRecord, trigger_id)
            if row is None:
                raise ResearchTriggerConflictError(f"unknown trigger: {trigger_id}")
            if row.policy_version != policy_version:
                raise ResearchTriggerConflictError("cooldown policy version mismatch")
            row.status = "SUPPRESSED_COOLDOWN"
            row.cooldown_until = to_utc_naive_datetime(cooldown_until)
            history = self._history(row.status_history_json)
            history.append("SUPPRESSED_COOLDOWN")
            row.status_history_json = json.dumps(history, separators=(",", ":"))

    def release_cooldowns(self, *, now: datetime) -> int:
        """Release only persisted cooldowns whose explicit window has elapsed."""

        now_naive = to_utc_naive_datetime(now)
        released = 0
        with self.db.session_scope() as session:
            rows = tuple(
                session.execute(
                    select(ResearchTriggerLedgerRecord).where(
                        ResearchTriggerLedgerRecord.status == "SUPPRESSED_COOLDOWN",
                        ResearchTriggerLedgerRecord.cooldown_until <= now_naive,
                    )
                ).scalars()
            )
            for row in rows:
                row.status = "FIRED"
                row.cooldown_until = None
                history = self._history(row.status_history_json)
                history.append("FIRED")
                row.status_history_json = json.dumps(history, separators=(",", ":"))
                released += 1
        return released

    def supersede(self, trigger_id: str, *, superseded_by: str) -> None:
        with self.db.session_scope() as session:
            row = session.get(ResearchTriggerLedgerRecord, trigger_id)
            if row is None:
                raise ResearchTriggerConflictError(f"unknown trigger: {trigger_id}")
            row.status = "SUPERSEDED"
            row.processed_at = utc_naive_now()
            history = self._history(row.status_history_json)
            history.append("SUPERSEDED")
            row.status_history_json = json.dumps(history, separators=(",", ":"))
            successor = session.get(ResearchTriggerLedgerRecord, superseded_by)
            if successor is not None and successor.supersedes_trigger_id != trigger_id:
                raise ResearchTriggerConflictError(
                    "successor trigger does not point to the superseded trigger"
                )

    def latest_for_symbol(
        self,
        *,
        symbol: str,
        effective_at: datetime,
        exclude_dedup_key: str | None = None,
    ) -> ResearchTrigger | None:
        """Return the prior durable episode without rewriting its history."""

        predicates = [
            ResearchTriggerLedgerRecord.symbol == symbol,
            ResearchTriggerLedgerRecord.effective_at <= to_utc_naive_datetime(effective_at),
        ]
        if exclude_dedup_key is not None:
            predicates.append(ResearchTriggerLedgerRecord.dedup_key != exclude_dedup_key)
        with self.db.get_session() as session:
            row = session.execute(
                select(ResearchTriggerLedgerRecord)
                .where(*predicates)
                .order_by(
                    desc(ResearchTriggerLedgerRecord.effective_at),
                    desc(ResearchTriggerLedgerRecord.created_at),
                )
                .limit(1)
            ).scalar_one_or_none()
        return None if row is None else self._to_trigger(row)

    def pending(self, *, now: datetime | None = None) -> tuple[ResearchTrigger, ...]:
        reference = to_utc_naive_datetime(now or datetime.now(timezone.utc))
        with self.db.get_session() as session:
            rows = tuple(
                session.execute(
                    select(ResearchTriggerLedgerRecord)
                    .where(
                        ResearchTriggerLedgerRecord.processed_at.is_(None),
                        ResearchTriggerLedgerRecord.status == "FIRED",
                        ResearchTriggerLedgerRecord.scheduled_for <= reference,
                    )
                    .order_by(
                        asc(ResearchTriggerLedgerRecord.priority),
                        asc(ResearchTriggerLedgerRecord.created_at),
                        asc(ResearchTriggerLedgerRecord.symbol),
                    )
                ).scalars()
            )
        return tuple(self._to_trigger(row) for row in rows)

    def get(self, trigger_id: str) -> ResearchTrigger | None:
        with self.db.get_session() as session:
            row = session.get(ResearchTriggerLedgerRecord, trigger_id)
        return None if row is None else self._to_trigger(row)

    def get_by_dedup_key(self, dedup_key: str) -> ResearchTrigger | None:
        with self.db.get_session() as session:
            row = session.execute(
                select(ResearchTriggerLedgerRecord).where(
                    ResearchTriggerLedgerRecord.dedup_key == dedup_key
                )
            ).scalar_one_or_none()
        return None if row is None else self._to_trigger(row)

    @staticmethod
    def _history(raw: str | None) -> list[str]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            value = []
        return [str(item) for item in value] if isinstance(value, list) else []

    @staticmethod
    def _to_trigger(row: ResearchTriggerLedgerRecord) -> ResearchTrigger:
        evidence = json.loads(row.evidence_refs_json)
        strategy_evidence = (
            json.loads(row.strategy_evidence_json)
            if row.strategy_evidence_json
            else None
        )
        return ResearchTrigger.build(
            research_trigger_id=row.research_trigger_id,
            trigger_type=row.trigger_type,
            trigger_source=row.trigger_source,
            symbol=row.symbol,
            market=row.market,
            priority=int(row.priority),
            created_at=row.created_at.replace(tzinfo=timezone.utc),
            source_event_time=(
                row.source_event_time.replace(tzinfo=timezone.utc)
                if row.source_event_time is not None
                else None
            ),
            effective_at=row.effective_at.replace(tzinfo=timezone.utc),
            scheduled_for=row.scheduled_for.replace(tzinfo=timezone.utc),
            dedup_key=row.dedup_key,
            policy_version=row.policy_version,
            evidence_refs=tuple(evidence),
            strategy_evidence=strategy_evidence,
            screening_scheduler_run_id=row.screening_scheduler_run_id,
            screening_run_id=row.screening_run_id,
            portfolio_snapshot_id=row.portfolio_snapshot_id,
            supersedes_trigger_id=row.supersedes_trigger_id,
        )


class HoldingsReviewCoverageRepository:
    """Durable per-symbol review coverage with deterministic fair rotation."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def materialize(
        self,
        *,
        snapshot: PortfolioSnapshot,
        now: datetime,
        interval_minutes: int,
        policy_version: str,
    ) -> tuple[dict[str, Any], ...]:
        if interval_minutes <= 0:
            raise ValueError("review interval must be positive")
        now_naive = to_utc_naive_datetime(now)
        holdings = tuple(
            sorted(
                {
                    str(position.symbol).split(".")[-1]
                    for position in snapshot.positions
                    if position.quantity > 0 and str(position.market).upper() == "CN"
                }
            )
        )
        with self.db.session_scope() as session:
            existing_rows = tuple(
                session.execute(select(HoldingsReviewCoverageRecord)).scalars()
            )
            for row in existing_rows:
                if row.symbol not in holdings:
                    row.review_status = "CLOSED"
                    row.updated_at = now_naive
            for symbol in holdings:
                row = session.execute(
                    select(HoldingsReviewCoverageRecord).where(
                        HoldingsReviewCoverageRecord.symbol == symbol
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = HoldingsReviewCoverageRecord(
                        symbol=symbol,
                        portfolio_snapshot_id=snapshot.snapshot_id,
                        last_successful_review_id=None,
                        last_successful_review_at=None,
                        next_review_due_at=now_naive,
                        review_priority=3,
                        review_policy_version=policy_version,
                        review_status="DUE",
                        deferred_count=0,
                        updated_at=now_naive,
                    )
                    session.add(row)
                    continue
                row.portfolio_snapshot_id = snapshot.snapshot_id
                row.review_policy_version = policy_version
                if row.last_successful_review_at is None:
                    row.review_status = "DUE"
                    row.review_priority = 3
                    row.next_review_due_at = row.next_review_due_at or now_naive
                elif row.next_review_due_at is not None and row.next_review_due_at <= now_naive:
                    row.review_status = "DUE"
                    row.review_priority = 3
                elif row.review_status in {"DUE", "DEFERRED_CAPACITY", "BLOCKED_RUNTIME"}:
                    row.review_status = "NOT_DUE"
                    row.review_priority = 4
                row.updated_at = now_naive
            session.flush()
            rows = tuple(
                session.execute(
                    select(HoldingsReviewCoverageRecord)
                    .where(HoldingsReviewCoverageRecord.symbol.in_(holdings))
                    .order_by(asc(HoldingsReviewCoverageRecord.symbol))
                ).scalars()
            )
            payload = tuple(self._payload(row) for row in rows)
        return payload

    def due(self, *, now: datetime) -> tuple[dict[str, Any], ...]:
        now_naive = to_utc_naive_datetime(now)
        with self.db.get_session() as session:
            rows = tuple(
                session.execute(
                    select(HoldingsReviewCoverageRecord)
                    .where(
                        HoldingsReviewCoverageRecord.review_status.in_(("DUE", "DEFERRED_CAPACITY")),
                        HoldingsReviewCoverageRecord.next_review_due_at <= now_naive,
                    )
                    .order_by(
                        HoldingsReviewCoverageRecord.last_successful_review_at.is_(None).desc(),
                        asc(HoldingsReviewCoverageRecord.last_successful_review_at),
                        asc(HoldingsReviewCoverageRecord.symbol),
                    )
                ).scalars()
            )
            payload = tuple(self._payload(row) for row in rows)
        return payload

    def mark_selected(self, symbols: set[str], *, now: datetime) -> None:
        now_naive = to_utc_naive_datetime(now)
        with self.db.session_scope() as session:
            rows = tuple(session.execute(select(HoldingsReviewCoverageRecord)).scalars())
            for row in rows:
                if row.review_status not in {"DUE", "DEFERRED_CAPACITY"}:
                    continue
                if row.symbol in symbols:
                    row.review_status = "IN_PROGRESS"
                else:
                    row.review_status = "DEFERRED_CAPACITY"
                    row.deferred_count = int(row.deferred_count or 0) + 1
                row.updated_at = now_naive

    def mark_completed(
        self,
        *,
        symbol: str,
        review_id: str,
        reviewed_at: datetime,
        interval_minutes: int,
    ) -> None:
        if interval_minutes <= 0:
            raise ValueError("review interval must be positive")
        reviewed_naive = to_utc_naive_datetime(reviewed_at)
        with self.db.session_scope() as session:
            row = session.execute(
                select(HoldingsReviewCoverageRecord).where(
                    HoldingsReviewCoverageRecord.symbol == symbol
                )
            ).scalar_one()
            row.last_successful_review_id = review_id
            row.last_successful_review_at = reviewed_naive
            row.next_review_due_at = reviewed_naive + timedelta(minutes=interval_minutes)
            row.review_status = "COMPLETED"
            row.review_priority = 4
            row.updated_at = reviewed_naive

    def mark_blocked(self, *, symbol: str, now: datetime) -> None:
        with self.db.session_scope() as session:
            row = session.execute(
                select(HoldingsReviewCoverageRecord).where(
                    HoldingsReviewCoverageRecord.symbol == symbol
                )
            ).scalar_one_or_none()
            if row is not None:
                row.review_status = "BLOCKED_RUNTIME"
                row.updated_at = to_utc_naive_datetime(now)

    def mark_deferred(self, *, symbol: str, now: datetime) -> None:
        """Return an admitted holding to the fair queue without consuming it."""

        with self.db.session_scope() as session:
            row = session.execute(
                select(HoldingsReviewCoverageRecord).where(
                    HoldingsReviewCoverageRecord.symbol == symbol
                )
            ).scalar_one_or_none()
            if row is not None:
                row.review_status = "DEFERRED_CAPACITY"
                row.deferred_count = int(row.deferred_count or 0) + 1
                row.updated_at = to_utc_naive_datetime(now)

    def projection(self) -> tuple[dict[str, Any], ...]:
        with self.db.get_session() as session:
            rows = tuple(
                session.execute(
                    select(HoldingsReviewCoverageRecord).order_by(
                        asc(HoldingsReviewCoverageRecord.symbol)
                    )
                ).scalars()
            )
            payload = tuple(self._payload(row) for row in rows)
        return payload

    @staticmethod
    def _payload(row: HoldingsReviewCoverageRecord) -> dict[str, Any]:
        def iso(value: datetime | None) -> str | None:
            return None if value is None else value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        return {
            "symbol": row.symbol,
            "portfolio_snapshot_id": row.portfolio_snapshot_id,
            "last_successful_review_id": row.last_successful_review_id,
            "last_successful_review_at": iso(row.last_successful_review_at),
            "next_review_due_at": iso(row.next_review_due_at),
            "review_priority": int(row.review_priority),
            "review_policy_version": row.review_policy_version,
            "review_status": row.review_status,
            "deferred_count": int(row.deferred_count or 0),
        }


class ResearchTriggerCoordinator:
    """Materialize triggers and fair holding coverage for the canonical DSA path."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        screening_candidate_source: Any | None = None,
    ) -> None:
        self.db = db_manager or DatabaseManager.get_instance()
        self.ledger = ResearchTriggerLedgerRepository(self.db)
        self.coverage = HoldingsReviewCoverageRepository(self.db)
        self._screening_candidate_source = screening_candidate_source

    def enqueue(self, trigger: ResearchTrigger | dict[str, Any]) -> TriggerEnqueueResult:
        """Enqueue one externally produced trigger through the canonical ledger.

        The coordinator remains the DSA authority for durable trigger identity
        and deduplication.  External callers cannot bypass the immutable
        ``ResearchTrigger`` contract or write the ledger directly.
        """
        return self.ledger.enqueue(self._coerce_trigger(trigger))

    def plan(
        self,
        *,
        config: Any,
        snapshot: PortfolioSnapshot,
        screening_candidates: list[dict[str, Any]] | None,
        cycle_id: str,
        now: datetime,
    ) -> list[dict[str, Any]]:
        interval = int(getattr(config, "single_brain_m2_interval_minutes", 60))
        policy_version = str(
            getattr(config, "single_brain_m2_review_policy_version", TRIGGER_POLICY_VERSION)
            or TRIGGER_POLICY_VERSION
        )
        self.coverage.materialize(
            snapshot=snapshot,
            now=now,
            interval_minutes=interval,
            policy_version=policy_version,
        )
        due = {item["symbol"]: item for item in self.coverage.due(now=now)}
        base_scopes = select_m2_research_objects(
            config=_UnboundedSelectionConfig(config),
            snapshot=snapshot,
            screening_candidates=screening_candidates,
        )
        scopes: list[dict[str, Any]] = []
        pending = self.ledger.pending(now=now)
        pending_keys: set[tuple[str, str, str | None]] = set()
        current_holdings = {
            str(position.symbol).split(".")[-1]
            for position in snapshot.positions
            if position.quantity > 0 and str(position.market).upper() == "CN"
        }
        for item in pending:
            source = self._source_for_trigger(item)
            if item.trigger_type == "SCHEDULED_HOLDING_REVIEW" and item.symbol not in current_holdings:
                self.ledger.mark_blocked(item.research_trigger_id)
                continue
            matching_scope = self._matching_scope_for_pending(item, base_scopes)
            if item.trigger_type == "SCHEDULED_SCREENING" and matching_scope is None:
                matching_scope = self._persisted_screening_scope(item)
                if matching_scope is None:
                    self.ledger.mark_blocked(item.research_trigger_id)
                    continue
            pending_keys.add(self._pending_key(item))
            scope = {
                **(matching_scope or {"symbol": item.symbol, "source": source}),
                "source": source,
                "research_trigger": item.model_dump(mode="json"),
                "_priority": item.priority,
                "_fairness": self._fairness_for_pending(item, due),
            }
            scopes.append(scope)
        for scope in base_scopes:
            symbol = str(scope["symbol"])
            source = str(scope.get("source") or "")
            if source in {"HOLDING", "BOTH"}:
                if ("SCHEDULED_HOLDING_REVIEW", symbol, None) in pending_keys:
                    continue
                if symbol not in due:
                    continue
                item = due[symbol]
                trigger = self._scheduled_holding_trigger(
                    symbol=symbol,
                    snapshot=snapshot,
                    cycle_id=cycle_id,
                    now=now,
                    scheduled_for=now,
                    priority=int(item["review_priority"]),
                    policy_version=policy_version,
                )
                result = self.ledger.enqueue(trigger)
                if result.status == "DEDUPLICATED" and self._processed(trigger.research_trigger_id):
                    continue
                scopes.append({
                    **scope,
                    "research_trigger": trigger.model_dump(mode="json"),
                    "_priority": trigger.priority,
                    "_fairness": (
                        0 if item["last_successful_review_at"] is None else 1,
                        item["last_successful_review_at"] or "",
                        symbol,
                    ),
                })
                continue
            if source == "SCREENING":
                screening_key = (
                    "SCHEDULED_SCREENING",
                    symbol,
                    str(scope.get("screening_run_id") or ""),
                )
                if screening_key in pending_keys:
                    continue
                trigger = self._screening_trigger(
                    scope=scope,
                    snapshot=snapshot,
                    cycle_id=cycle_id,
                    now=now,
                    policy_version=policy_version,
                )
                result = self.ledger.enqueue(trigger)
                if result.status == "DEDUPLICATED" and self._processed(trigger.research_trigger_id):
                    continue
                scopes.append({
                    **scope,
                    "research_trigger": trigger.model_dump(mode="json"),
                    "_priority": trigger.priority,
                    "_fairness": (2, "", symbol),
                })
                continue
            trigger = self._manual_trigger(
                symbol=symbol,
                snapshot=snapshot,
                cycle_id=cycle_id,
                now=now,
                policy_version=policy_version,
            )
            result = self.ledger.enqueue(trigger)
            if result.status == "DEDUPLICATED" and self._processed(trigger.research_trigger_id):
                continue
            scopes.append({
                **scope,
                "research_trigger": trigger.model_dump(mode="json"),
                "_priority": trigger.priority,
                "_fairness": (3, "", symbol),
            })
        max_symbols = min(50, max(1, int(getattr(config, "single_brain_m2_max_symbols", 10))))
        selected = self._select_scopes(
            scopes=scopes,
            max_symbols=max_symbols,
            now=now,
            interval_minutes=interval,
        )
        selected_holding_symbols = {
            item["symbol"]
            for item in selected
            if item["research_trigger"].get("trigger_type") == "SCHEDULED_HOLDING_REVIEW"
        }
        self.coverage.mark_selected(selected_holding_symbols, now=now)
        for item in selected:
            item.pop("_priority", None)
            item.pop("_fairness", None)
        return selected

    def mark_success(
        self,
        *,
        trigger: ResearchTrigger | dict[str, Any],
        research_id: str,
        proposal_id: str,
        reviewed_at: datetime,
        interval_minutes: int,
    ) -> None:
        value = self._coerce_trigger(trigger)
        self.ledger.mark_processed(value.research_trigger_id)
        if value.trigger_type == "SCHEDULED_HOLDING_REVIEW":
            self.coverage.mark_completed(
                symbol=value.symbol,
                review_id=str(research_id),
                reviewed_at=reviewed_at,
                interval_minutes=interval_minutes,
            )

    def mark_failure(self, *, trigger: ResearchTrigger | dict[str, Any], now: datetime) -> None:
        value = self._coerce_trigger(trigger)
        self.ledger.mark_blocked(value.research_trigger_id)
        if value.trigger_type == "SCHEDULED_HOLDING_REVIEW":
            self.coverage.mark_blocked(symbol=value.symbol, now=now)

    def mark_deferred_budget(
        self, *, trigger: ResearchTrigger | dict[str, Any], now: datetime
    ) -> None:
        """Keep the durable FIRED trigger eligible for a later legal cycle."""

        value = self._coerce_trigger(trigger)
        if value.trigger_type == "SCHEDULED_HOLDING_REVIEW":
            self.coverage.mark_deferred(symbol=value.symbol, now=now)

    def enqueue_material_event(
        self, *, symbol: str, event_id: str, effective_at: datetime, evidence_refs: tuple[str, ...], snapshot_id: str | None = None,
        supersedes_trigger_id: str | None = None,
    ) -> TriggerEnqueueResult:
        dedup_key = f"MATERIAL_EVENT_REVIEW:{event_id}:{symbol}"
        existing = self.ledger.get_by_dedup_key(dedup_key)
        if existing is not None:
            return self.ledger.enqueue(existing)
        predecessor = supersedes_trigger_id or self._predecessor_id(
            symbol=symbol, effective_at=effective_at, dedup_key=dedup_key,
        )
        result = self.ledger.enqueue(self._external_trigger(
            trigger_type="MATERIAL_EVENT_REVIEW", trigger_source="external-material-event", priority=2,
            symbol=symbol, event_id=event_id, effective_at=effective_at, evidence_refs=evidence_refs,
            snapshot_id=snapshot_id, supersedes_trigger_id=predecessor,
        ))
        if result.created and predecessor:
            self.ledger.supersede(predecessor, superseded_by=result.trigger.research_trigger_id)
        return result

    def enqueue_defensive_risk(
        self, *, symbol: str, risk_event_id: str, effective_at: datetime, evidence_refs: tuple[str, ...], snapshot_id: str | None = None,
        supersedes_trigger_id: str | None = None,
    ) -> TriggerEnqueueResult:
        dedup_key = f"DEFENSIVE_RISK_REVIEW:{risk_event_id}:{symbol}"
        existing = self.ledger.get_by_dedup_key(dedup_key)
        if existing is not None:
            return self.ledger.enqueue(existing)
        predecessor = supersedes_trigger_id
        result = self.ledger.enqueue(self._external_trigger(
            trigger_type="DEFENSIVE_RISK_REVIEW", trigger_source="external-defensive-risk", priority=1,
            symbol=symbol, event_id=risk_event_id, effective_at=effective_at, evidence_refs=evidence_refs,
            snapshot_id=snapshot_id, supersedes_trigger_id=predecessor,
        ))
        if result.created and predecessor:
            self.ledger.supersede(predecessor, superseded_by=result.trigger.research_trigger_id)
        return result

    def _processed(self, trigger_id: str) -> bool:
        with self.db.get_session() as session:
            row = session.get(ResearchTriggerLedgerRecord, trigger_id)
            return bool(row is not None and row.processed_at is not None)

    def _predecessor_id(
        self, *, symbol: str, effective_at: datetime, dedup_key: str,
    ) -> str | None:
        predecessor = self.ledger.latest_for_symbol(
            symbol=symbol, effective_at=effective_at, exclude_dedup_key=dedup_key,
        )
        return None if predecessor is None else predecessor.research_trigger_id

    @staticmethod
    def _source_for_trigger(trigger: ResearchTrigger) -> str:
        return {
            "SCHEDULED_SCREENING": "SCREENING",
            "SCHEDULED_HOLDING_REVIEW": "HOLDING",
            "MATERIAL_EVENT_REVIEW": "MATERIAL_EVENT",
            "DEFENSIVE_RISK_REVIEW": "DEFENSIVE_RISK",
            "MANUAL_OWNER_REVIEW": "ALLOWLIST",
        }[trigger.trigger_type]

    @staticmethod
    def _pending_key(trigger: ResearchTrigger) -> tuple[str, str, str | None]:
        return (
            trigger.trigger_type,
            trigger.symbol,
            trigger.screening_run_id if trigger.trigger_type == "SCHEDULED_SCREENING" else None,
        )

    @staticmethod
    def _matching_scope_for_pending(
        trigger: ResearchTrigger, scopes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for scope in scopes:
            if str(scope.get("symbol")) != trigger.symbol:
                continue
            source = str(scope.get("source") or "")
            if trigger.trigger_type == "SCHEDULED_HOLDING_REVIEW" and source in {"HOLDING", "BOTH"}:
                return scope
            if (
                trigger.trigger_type == "SCHEDULED_SCREENING"
                and source == "SCREENING"
                and str(scope.get("screening_run_id") or "") == str(trigger.screening_run_id or "")
            ):
                return scope
        return None

    def _persisted_screening_scope(self, trigger: ResearchTrigger) -> dict[str, Any] | None:
        source = self._screening_candidate_source
        lookup = getattr(source, "by_run", None)
        if not callable(lookup):
            return None
        candidate = lookup(
            screening_run_id=str(trigger.screening_run_id or ""),
            symbol=trigger.symbol,
        )
        return None if candidate is None else candidate.as_scope()

    @staticmethod
    def _fairness_for_pending(
        trigger: ResearchTrigger, due: dict[str, dict[str, Any]],
    ) -> tuple[int, str, str]:
        item = due.get(trigger.symbol)
        if trigger.trigger_type == "SCHEDULED_HOLDING_REVIEW" and item is not None:
            return (
                0 if item["last_successful_review_at"] is None else 1,
                item["last_successful_review_at"] or "",
                trigger.symbol,
            )
        return (0, "", trigger.symbol)

    @classmethod
    def _scope_sort_key(
        cls,
        *,
        item: dict[str, Any],
        now: datetime,
        interval_minutes: int,
    ) -> tuple[int, int, tuple[int, str, str], str]:
        """Keep lower-priority screening work from starving behind holdings.

        A screening trigger that has waited one normal M2 interval is promoted
        to the holding-review priority tier.  Safety/material-event priorities
        remain ahead of it, while the explicit overdue group makes the
        promotion deterministic when it ties with a holding trigger.
        """

        trigger = item["research_trigger"]
        priority = int(item["_priority"])
        overdue_group = 1
        if cls._screening_trigger_is_overdue(
            trigger,
            now=now,
            interval_minutes=interval_minutes,
        ):
            priority = min(priority, 3)
            overdue_group = 0
        return (priority, overdue_group, item["_fairness"], item["symbol"])

    @classmethod
    def _select_scopes(
        cls,
        *,
        scopes: list[dict[str, Any]],
        max_symbols: int,
        now: datetime,
        interval_minutes: int,
    ) -> list[dict[str, Any]]:
        """Select work without allowing aged screening to starve holdings.

        Material-event and defensive-risk work remains ahead of the bounded
        screening/holding fairness rule.  When both due holdings and overdue
        screening exist and at least two slots remain, reserve one slot for
        each cohort and let the oldest overdue screening advance first.
        """

        ordered = sorted(
            scopes,
            key=lambda item: cls._scope_sort_key(
                item=item,
                now=now,
                interval_minutes=interval_minutes,
            ),
        )
        if max_symbols <= 0:
            return []

        safety_types = {"MATERIAL_EVENT_REVIEW", "DEFENSIVE_RISK_REVIEW"}
        safety_items = [
            item
            for item in ordered
            if item["research_trigger"].get("trigger_type") in safety_types
        ][:max_symbols]
        selected_ids = {id(item) for item in safety_items}
        if len(safety_items) == max_symbols:
            return safety_items

        remaining_items = [item for item in ordered if id(item) not in selected_ids]
        remaining_capacity = max_symbols - len(selected_ids)

        holdings = [
            item
            for item in remaining_items
            if item["research_trigger"].get("trigger_type") == "SCHEDULED_HOLDING_REVIEW"
        ]
        overdue_screenings = sorted(
            (
                item
                for item in remaining_items
                if cls._screening_trigger_is_overdue(
                    item["research_trigger"],
                    now=now,
                    interval_minutes=interval_minutes,
                )
            ),
            key=lambda item: (
                str(item["research_trigger"].get("scheduled_for") or ""),
                str(item["research_trigger"].get("created_at") or ""),
                str(item["symbol"]),
            ),
        )

        if holdings and overdue_screenings:
            if remaining_capacity >= 2:
                selected_ids.add(id(overdue_screenings[0]))
                selected_ids.update(id(item) for item in holdings[: remaining_capacity - 1])
            else:
                selected_ids.add(id(overdue_screenings[0]))
        else:
            selected_ids.update(id(item) for item in remaining_items[:remaining_capacity])

        if len(selected_ids) < max_symbols:
            for item in remaining_items:
                if len(selected_ids) >= max_symbols:
                    break
                selected_ids.add(id(item))

        return [item for item in ordered if id(item) in selected_ids][:max_symbols]

    @staticmethod
    def _screening_trigger_is_overdue(
        trigger: dict[str, Any],
        *,
        now: datetime,
        interval_minutes: int,
    ) -> bool:
        if trigger.get("trigger_type") != "SCHEDULED_SCREENING":
            return False
        raw_scheduled_for = trigger.get("scheduled_for")
        try:
            scheduled_for = datetime.fromisoformat(str(raw_scheduled_for))
        except (TypeError, ValueError):
            return False
        if scheduled_for.tzinfo is None or scheduled_for.utcoffset() is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc) - scheduled_for.astimezone(timezone.utc) >= timedelta(
            minutes=max(1, int(interval_minutes))
        )

    @staticmethod
    def _coerce_trigger(trigger: ResearchTrigger | dict[str, Any]) -> ResearchTrigger:
        if isinstance(trigger, ResearchTrigger):
            return trigger
        return ResearchTrigger.model_validate_json(json.dumps(trigger))

    @staticmethod
    def _trigger_id(dedup_key: str) -> str:
        return f"research-trigger-{hashlib.sha256(dedup_key.encode()).hexdigest()[:32]}"

    def _scheduled_holding_trigger(self, *, symbol: str, snapshot: PortfolioSnapshot, cycle_id: str, now: datetime, scheduled_for: datetime, priority: int, policy_version: str) -> ResearchTrigger:
        dedup_key = f"holding-review:{symbol}:{scheduled_for.astimezone(timezone.utc).isoformat()}"
        return ResearchTrigger.build(
            research_trigger_id=self._trigger_id(dedup_key), trigger_type="SCHEDULED_HOLDING_REVIEW",
            trigger_source="single_brain_holdings_review", symbol=symbol, market="CN", priority=priority,
            created_at=now, source_event_time=now, effective_at=now, scheduled_for=scheduled_for,
            dedup_key=dedup_key, policy_version=policy_version,
            evidence_refs=(f"portfolio-snapshot:{snapshot.snapshot_id}", f"cycle:{cycle_id}"),
            portfolio_snapshot_id=snapshot.snapshot_id,
        )

    def _screening_trigger(self, *, scope: dict[str, Any], snapshot: PortfolioSnapshot, cycle_id: str, now: datetime, policy_version: str) -> ResearchTrigger:
        screening_run = str(scope.get("screening_run_id") or "")
        dedup_key = f"screening:{screening_run}:{scope['symbol']}"
        return ResearchTrigger.build(
            research_trigger_id=self._trigger_id(dedup_key), trigger_type="SCHEDULED_SCREENING",
            trigger_source="single_brain_screening_scheduler", symbol=str(scope["symbol"]), market="CN", priority=5,
            created_at=now, source_event_time=now, effective_at=now, scheduled_for=now,
            dedup_key=dedup_key, policy_version=policy_version,
            evidence_refs=(f"screening-run:{screening_run}", f"cycle:{cycle_id}"),
            screening_scheduler_run_id=str(scope.get("screening_scheduler_run_id") or screening_run),
            screening_run_id=screening_run,
            portfolio_snapshot_id=snapshot.snapshot_id,
        )

    def _manual_trigger(self, *, symbol: str, snapshot: PortfolioSnapshot, cycle_id: str, now: datetime, policy_version: str) -> ResearchTrigger:
        dedup_key = f"manual-owner-review:{cycle_id}:{symbol}"
        return ResearchTrigger.build(
            research_trigger_id=self._trigger_id(dedup_key), trigger_type="MANUAL_OWNER_REVIEW",
            trigger_source="manual-owner-allowlist", symbol=symbol, market="CN", priority=6,
            created_at=now, source_event_time=now, effective_at=now, scheduled_for=now,
            dedup_key=dedup_key, policy_version=policy_version,
            evidence_refs=(f"manual-allowlist:{symbol}", f"cycle:{cycle_id}"),
            portfolio_snapshot_id=snapshot.snapshot_id,
        )

    def _external_trigger(self, *, trigger_type: str, trigger_source: str, priority: int, symbol: str, event_id: str, effective_at: datetime, evidence_refs: tuple[str, ...], snapshot_id: str | None, supersedes_trigger_id: str | None = None) -> ResearchTrigger:
        dedup_key = f"{trigger_type}:{event_id}:{symbol}"
        return ResearchTrigger.build(
            research_trigger_id=self._trigger_id(dedup_key), trigger_type=trigger_type,
            trigger_source=trigger_source, symbol=symbol, market="CN", priority=priority,
            created_at=effective_at, source_event_time=effective_at, effective_at=effective_at,
            scheduled_for=effective_at, dedup_key=dedup_key, policy_version=TRIGGER_POLICY_VERSION,
            evidence_refs=tuple(dict.fromkeys(evidence_refs)), portfolio_snapshot_id=snapshot_id,
            supersedes_trigger_id=supersedes_trigger_id,
        )
