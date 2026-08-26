#!/usr/bin/env python3
"""Deterministic DSA system-reassembly harness.

The Golden Path enters through the real ``RuntimeSchedulerService`` task
registration and scheduler background-task dispatcher. Only provider, Luna,
transport, portfolio and screening inputs are local deterministic fixtures.
The existing MarketContext service, screening scheduler, candidate reader,
trigger coordinator, proposal builder and canonical cycle repository remain
on the path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo


NOW = datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc)
SCREENING_DUE = NOW + timedelta(hours=4, minutes=45)  # 14:45 BJT, legal session
START_OPEN = datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc)  # 08:00 BJT
START_EARLY = datetime(2026, 8, 25, 2, 17, tzinfo=timezone.utc)  # 10:17 BJT
START_LUNCH = datetime(2026, 8, 25, 3, 31, tzinfo=timezone.utc)  # 11:31 BJT
START_MID = datetime(2026, 8, 25, 5, 17, tzinfo=timezone.utc)  # 13:17 BJT
START_NEAR_DUE = datetime(2026, 8, 25, 6, 44, tzinfo=timezone.utc)  # 14:44 BJT
START_POST_DUE = datetime(2026, 8, 25, 6, 46, tzinfo=timezone.utc)  # 14:46 BJT
START_AFTER_CUTOFF = datetime(2026, 8, 25, 7, 1, tzinfo=timezone.utc)  # 15:01 BJT
PRIOR_COMPLETED_TRADE_DATE = "2026-08-24"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _parse_time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AssertionError(f"scheduler timestamp is not timezone-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


def _context(*, as_of: datetime = NOW, lineage: str = "fixture", quality: str = "complete") -> dict[str, object]:
    iso = as_of.isoformat()
    provenance = {
        component: {"status": "PIT_VALIDATED", "observed_at": iso, "reference": f"fixture:{component}"}
        for component in ("indices", "breadth", "sectors", "concepts")
    }
    identity = f"{lineage}:{as_of.astimezone(timezone.utc).strftime('%H%M%S')}"
    return {
        "schema_version": "pallas-009-market-context-v1",
        "context_id": f"market-context:{identity}",
        "market_review_id": f"market-review:{identity}",
        "source_task_id": f"market-review:{identity}",
        "market": "cn",
        "trade_date": as_of.astimezone(timezone.utc).date().isoformat(),
        "as_of": iso,
        "decision_as_of": iso,
        "summary": "deterministic structured market context",
        "source_completeness": {
            "requested": ["indices", "breadth", "sectors", "concepts"],
            "available": ["indices", "breadth", "sectors", "concepts"],
            "missing": [], "failed": [], "status": quality,
        },
        "component_timing_status": "PIT_VALIDATED",
        "component_provenance": provenance,
        "provenance": {"source_task_id": f"market-review:{identity}"},
        "narrative": {"status": "FAILED_CLOSED_STRUCTURED_CONTEXT_USABLE", "machine_authority": "STRUCTURED_MARKET_DATA"},
    }


def _pallas008_evidence(
    *,
    symbol: str = "600519",
    decision_cutoff: datetime = NOW,
    latest_completed_trade_date: str = PRIOR_COMPLETED_TRADE_DATE,
) -> dict[str, object]:
    from src.investment.contracts.strategy_evidence import build_pallas008_strategy_evidence

    return build_pallas008_strategy_evidence(
        strategy_id="PALLAS-008-A-SHARE-AUTONOMOUS-V1",
        strategy_version="1.0",
        ranking_method="PALLAS_008_QUANTITATIVE_EVIDENCE",
        ranking_score="0.800000",
        discovery_rank=1,
        ranking_components={
            "momentum_20": "0.800000", "momentum_60": "0.800000",
            "trend_strength": "0.800000", "liquidity_ratio": "0.800000",
            "market_strength": "0.800000",
        },
        market_strength_raw="0.030000",
        latest_completed_trade_date=latest_completed_trade_date,
        decision_cutoff=decision_cutoff,
        completion_status="CLOSE_CONFIRMED",
        completion_basis="PRIOR_PROVIDER_RETURNED_SESSION",
        quantitative_input_reference=f"fixture:daily-close:{symbol}:{PRIOR_COMPLETED_TRADE_DATE}",
    )


class _DiscoveryDB:
    """Read-only adapter fixture used by the focused discovery matrix."""

    def __init__(self, *, mode: str, observed_at: datetime = NOW):
        self.mode = mode
        self.observed_at = observed_at

    def list_screening_runs(self, **_kwargs):
        if self.mode == "unavailable":
            raise OSError("fixture screening DB unavailable")
        if self.mode == "missing":
            return []
        return [{"run_id": "screen-run-fixture", "strategy": "capital_heat", "market": "cn"}]

    def get_screening_run(self, _run_id):
        completed_date = PRIOR_COMPLETED_TRADE_DATE
        decision_cutoff = self.observed_at
        completion_status = "CLOSE_CONFIRMED"
        producer_status = "COMPLETED"
        source_errors = []
        if self.mode == "stale":
            completed_date = (NOW - timedelta(days=4)).date().isoformat()
            decision_cutoff = NOW - timedelta(days=4)
        elif self.mode == "failed":
            completion_status = "FAILED"
            producer_status = "FAILED"
        elif self.mode == "quality":
            source_errors = ["fixture source failed"]
        elif self.mode == "future":
            completed_date = self.observed_at.astimezone(timezone.utc).date().isoformat()
        elif self.mode == "holiday_prior_close":
            completed_date = "2026-09-30"
        elif self.mode == "holiday_one_session_older":
            completed_date = "2026-09-29"
        candidates = [] if self.mode == "zero" else [{
            "code": "600519", "name": "贵州茅台", "rank": 1,
            "screen_score": 88.0, "score": 88.0,
            "latest_completed_trade_date": completed_date,
            "decision_cutoff": decision_cutoff.isoformat(),
            "completion_status": completion_status,
            "completion_basis": "PRIOR_PROVIDER_RETURNED_SESSION",
            "quantitative_input_reference": "fixture:daily-close:600519:2026-08-24",
            "strategy_evidence": _pallas008_evidence(
                decision_cutoff=decision_cutoff,
                latest_completed_trade_date=completed_date,
            ),
        }]
        return {
            "run_id": "screen-run-fixture", "strategy": "capital_heat", "market": "cn",
            "created_at": (self.observed_at - timedelta(minutes=1)).isoformat(), "status": producer_status,
            "result": {
                "candidates": candidates, "candidate_count": len(candidates),
                "strategy": "capital_heat", "market": "cn",
                "latest_completed_trade_date": completed_date,
                "decision_cutoff": decision_cutoff.isoformat(),
                "completion_status": completion_status,
                "completion_basis": "PRIOR_PROVIDER_RETURNED_SESSION",
                "quantitative_input_reference": "fixture:daily-close:600519:2026-08-24",
                "source_errors": source_errors, "warnings": [], "degradation": [],
            },
        }


def _snapshot(*, holdings: bool = False, as_of: datetime = NOW):
    from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot, Position

    positions = ()
    if holdings:
        positions = (Position(
            symbol="600519", market="CN", quantity=100, available_quantity=100,
            avg_cost=Decimal("90"), last_price=Decimal("100"),
            market_value=Decimal("10000"), unrealized_pnl=Decimal("1000"),
            price_as_of=as_of, price_source="fixture:quote",
        ),)
    return PortfolioSnapshot.build(
        snapshot_id="snapshot:fixture", trace_id="trace:fixture", created_at=as_of,
        producer="ATHENA_GOLDEN_PATH_FIXTURE", account_id="athena-sim",
        broker="FIXTURE_WORKER", account_mode="SIMULATION", as_of=as_of, revision=1,
        currency="CNY", equity=Decimal("1000000.00"), cash=Decimal("1000000.00"),
        available_cash=Decimal("1000000.00"), reserved_cash=Decimal("0.00"),
        positions=positions, active_orders=(), realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"), reconciliation_status="RECONCILED",
        data_quality="HIGH", limitations=(), broker_snapshot_ref="fixture:portfolio",
    )


class _Runner:
    def __init__(
        self,
        *,
        fail: bool = False,
        completion_events: list[datetime] | None = None,
        **_kwargs,
    ):
        self.fail = fail
        self.completion_events = completion_events if completion_events is not None else []

    def complete(self, *, symbol, current_time, **_kwargs):
        if self.fail:
            raise TimeoutError("fixture Luna research timeout")
        from src.analyzer import AnalysisResult
        from src.investment.m2.orchestration import AnalysisCompletion

        result = AnalysisResult(
            code=symbol, name="贵州茅台", sentiment_score=76,
            trend_prediction="中期上行趋势", operation_advice="买入",
            decision_type="buy", confidence_level="高", action="buy",
            technical_analysis="fixture technical", fundamental_analysis="fixture fundamental",
            analysis_summary="fixture completed Luna Max research", risk_warning="fixture risk",
            model_used="gpt-5.6-luna",
            dashboard={"battle_plan": {"sniper_points": {
                "ideal_buy": 95, "secondary_buy": 100, "stop_loss": 80, "take_profit": 130,
            }}},
        )
        self.completion_events.append(current_time)
        return AnalysisCompletion(
            result=result,
            context_snapshot={
                "source": "fixture:DSAAnalysisCompletionRunner",
                "price_plan": {
                    "source_event_time": "2026-08-24T07:00:00+00:00",
                    "retrieved_at": current_time.isoformat(),
                    "provider": "fixture:daily-close",
                    "source_reference": "fixture:daily-close:600519:2026-08-24",
                    "completion_status": "CLOSE_CONFIRMED",
                },
            },
            source_report_id=42,
            recovered=False,
            completed_at=current_time,
        )


class _Publisher:
    def __init__(
        self,
        *,
        clock=None,
        publish_events: list[datetime] | None = None,
        **_kwargs,
    ):
        self.proposals = []
        self.clock = clock or (lambda: NOW)
        self.publish_events = publish_events if publish_events is not None else []

    def publish(self, proposal):
        from src.investment.proposal.transport import AthenaProposalAcknowledgement

        self.proposals.append(proposal)
        self.publish_events.append(self.clock())
        return AthenaProposalAcknowledgement(
            proposal_id=proposal.proposal_id, proposal_hash=proposal.content_hash,
            acknowledgement_id=f"ack:{proposal.content_hash[:24]}",
            acknowledgement_state="ACCEPTED", lifecycle_state="ACCEPTED", deduplicated=False,
        )


class _SnapshotSource:
    def __init__(self, *, holdings=False, clock=None, **_kwargs):
        self.holdings = holdings
        self.clock = clock or (lambda: NOW)

    def capture_snapshot(self):
        return _snapshot(holdings=self.holdings, as_of=self.clock())


class _FixtureScreeningService:
    def __init__(
        self,
        *,
        config,
        db_manager,
        mode,
        attempt_number=1,
        attempt_events=None,
        screening_calls=None,
        observed_at=NOW,
        **_kwargs,
    ):
        self.db = db_manager
        self.mode = mode
        self.attempt_number = attempt_number
        self.attempt_events = attempt_events if attempt_events is not None else []
        self.screening_calls = screening_calls if screening_calls is not None else []
        self.observed_at = observed_at

    def screen(self, *, strategy, market, max_results):
        attempt_number = self.attempt_number
        self.attempt_number += 1
        attempt_at = self.observed_at
        self.screening_calls.append({
            "attempt": attempt_number,
            "mode": self.mode,
            "at": attempt_at.astimezone(timezone.utc).isoformat(),
            "at_bjt": attempt_at.isoformat(),
        })
        self.attempt_events.append({
            "attempt": attempt_number,
            "mode": self.mode,
            "at": attempt_at.astimezone(timezone.utc).isoformat(),
            "at_bjt": attempt_at.isoformat(),
        })
        retry_target = int(self.mode.rsplit("_", 1)[-1]) if self.mode.startswith("retry_") else None
        if self.mode == "failed" or (
            self.mode == "transient_recovery" and attempt_number == 1
        ) or (
            retry_target is not None and attempt_number < retry_target
        ):
            raise OSError("fixture screening producer unavailable")
        candidates = [] if self.mode == "zero" else [{
            "code": "600519", "name": "贵州茅台", "rank": 1,
            "screen_score": 88.0, "score": 88.0,
            "latest_completed_trade_date": PRIOR_COMPLETED_TRADE_DATE,
            "decision_cutoff": attempt_at.isoformat(), "completion_status": "CLOSE_CONFIRMED",
            "completion_basis": "PRIOR_PROVIDER_RETURNED_SESSION",
            "quantitative_input_reference": "fixture:daily-close:600519:2026-08-24",
            "strategy_evidence": _pallas008_evidence(decision_cutoff=attempt_at),
        }]
        source_errors = []
        if self.mode == "quality_recovery" and attempt_number == 1:
            source_errors = ["fixture provider quality failed"]
        payload = {
            "run_id": f"screen-run-{self.mode}-{attempt_number}",
            "strategy": strategy, "market": market,
            "snapshot_source": "fixture:screening-provider", "snapshot_count": len(candidates),
            "after_filter_count": len(candidates), "candidate_count": len(candidates),
            "llm_ranked": False, "daily_enriched": True,
            "latest_completed_trade_date": PRIOR_COMPLETED_TRADE_DATE,
            "decision_cutoff": self.observed_at.isoformat(), "completion_status": "CLOSE_CONFIRMED",
            "completion_basis": "PRIOR_PROVIDER_RETURNED_SESSION",
            "quantitative_input_reference": "fixture:daily-close:600519:2026-08-24",
            "candidates": candidates, "source_errors": source_errors, "warnings": [],
            "degradation": [], "status": "COMPLETED",
        }
        self.db.save_screening_run(payload)
        return {**payload, "persistence_status": "PERSISTED"}


def _persist_market_context(db, context: dict[str, object], *, query_id: str) -> None:
    from src.storage import AnalysisHistory

    created_at = datetime.fromisoformat(str(context["as_of"])).astimezone(timezone.utc).replace(tzinfo=None)
    payload = {"market_context": context, "summary": "deterministic structured market context"}
    with db.session_scope() as session:
        session.add(AnalysisHistory(
            query_id=query_id[:64], code="__market_review__", name="Fixture Market Review",
            report_type="market_review", sentiment_score=50, operation_advice="fixture",
            trend_prediction="fixture", analysis_summary="deterministic structured market context",
            raw_result=json.dumps(payload, sort_keys=True), news_content="fixture",
            context_snapshot=json.dumps({"market_review_region": "cn", "market_review_payload": payload}, sort_keys=True),
            created_at=created_at,
        ))


def _fake_market_review_factory(db, generated: list[str]):
    def fake_run_market_review(**kwargs):
        as_of = kwargs.get("context_as_of") or NOW
        if isinstance(as_of, str):
            as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        query_id = str(kwargs.get("query_id") or "fixture-market-review")
        context = _context(as_of=as_of, lineage=hashlib.sha1(query_id.encode()).hexdigest()[:12])
        _persist_market_context(db, context, query_id=query_id)
        generated.append(str(context["as_of"]))
        return SimpleNamespace(
            market_review_payload={"market_context": context, "summary": "deterministic structured market context"},
            report="deterministic structured market context", persistence_status="PERSISTED",
        )
    return fake_run_market_review


def _market_context_refresh_probe(db, *, config) -> dict[str, object]:
    """Exercise the real context cache/history path across a stale cutoff."""

    from src.services.daily_market_context import DailyMarketContextService

    service = DailyMarketContextService(
        db_manager=db,
        today_fn=lambda: NOW.date(),
    )
    first = service.get_context(
        region="cn", config=config, notifier=SimpleNamespace(),
        analyzer=None, search_service=None, force_refresh=True,
        decision_as_of=NOW, max_age_seconds=3600,
    )
    second_cutoff = NOW + timedelta(hours=2)
    second = service.get_context(
        region="cn", config=config, notifier=SimpleNamespace(),
        analyzer=None, search_service=None, force_refresh=False,
        decision_as_of=second_cutoff, max_age_seconds=3600,
    )
    return {
        "first_generated": first is not None,
        "second_generated_after_stale_cutoff": second is not None,
        "first_decision_as_of": first.decision_as_of if first is not None else None,
        "second_decision_as_of": second.decision_as_of if second is not None else None,
        "stale_recovery": (
            first is not None and second is not None
            and first.decision_as_of != second.decision_as_of
        ),
    }


def _runtime_config(*, holdings: bool) -> SimpleNamespace:
    return SimpleNamespace(
        schedule_enabled=True, schedule_time="23:59", schedule_times=["23:59"],
        single_brain_m2_enabled=True, single_brain_execution_mode="PROPOSAL_HANDOFF",
        single_brain_simulation_execution_authorized=False, single_brain_m2_interval_minutes=10,
        single_brain_m2_cycle_guard_seconds=120, single_brain_m2_run_immediately=False,
        single_brain_m2_natural_session_gate_enabled=True, single_brain_m2_screening_enabled=True,
        single_brain_m2_screening_max_candidates=3, single_brain_m2_screening_max_age_hours=72,
        single_brain_m2_screening_strategy="capital_heat", single_brain_m2_screening_market="cn",
        single_brain_m2_max_symbols=1, single_brain_m2_holdings_limit=1 if holdings else 0,
        single_brain_m2_symbols=[], single_brain_m2_review_policy_version="pallas-004-research-trigger-v1",
        generation_backend_timeout_seconds=300, single_brain_m2_snapshot_timeout_seconds=5,
        single_brain_proposal_timeout_seconds=5, single_brain_proposal_url="http://fixture.invalid/athena",
        single_brain_m2_snapshot_url="http://fixture.invalid/portfolio", market_review_region="cn",
        report_language="zh", single_brain_m2_readiness_gate_enabled=False,
    )


def _timing_contract(config: object) -> dict[str, object]:
    from src.investment.m2.natural_admission import build_cycle_budget

    budget = build_cycle_budget(
        started_at=NOW,
        scheduled_for=SCREENING_DUE,
        config=config,
    )
    return {
        "interval_seconds": budget.interval_seconds,
        "cycle_guard_seconds": budget.guard_seconds,
        "usable_cycle_budget_seconds": budget.usable_cycle_budget_seconds,
        "required_candidate_reserve_seconds": int(budget.candidate_reserve_seconds),
        "generation_backend_timeout_seconds": int(getattr(config, "generation_backend_timeout_seconds")),
        "snapshot_timeout_seconds": float(getattr(config, "single_brain_m2_snapshot_timeout_seconds")),
        "proposal_timeout_seconds": float(getattr(config, "single_brain_proposal_timeout_seconds")),
        "configuration_admissible": budget.configuration_admissible,
    }


def _scheduler_poll(
    runtime,
    *,
    observed_at: datetime,
    natural_clock: dict[str, datetime],
) -> dict[str, object]:
    """Drive one real scheduler-loop poll with a fixed clock."""

    import src.scheduler as scheduler_module

    natural_clock["now"] = observed_at
    scheduler = runtime._scheduler
    _require(scheduler is not None, "RuntimeSchedulerService did not register Scheduler")
    entries = scheduler._background_tasks
    _require(
        [entry["name"] for entry in entries]
        == ["single_brain_proposal_handoff", "single_brain_screening_producer"],
        "canonical task registration mismatch",
    )
    before = {
        id(entry): (
            float(entry.get("last_run") or 0.0),
            entry.get("scheduled_for_epoch"),
        )
        for entry in entries
    }
    with patch.object(scheduler_module.time, "time", return_value=observed_at.timestamp()):
        scheduler._run_background_tasks()
    for entry in entries:
        worker = entry.get("thread")
        if worker is not None:
            worker.join(timeout=10)
        _require(not entry.get("running"), f"natural task did not finish: {entry['name']}")
    events = []
    for entry in entries:
        before_last_run, before_due = before[id(entry)]
        after_last_run = float(entry.get("last_run") or 0.0)
        after_due = entry.get("scheduled_for_epoch")
        dispatched = after_last_run != before_last_run or after_due != before_due
        if not dispatched:
            continue
        events.append({
            "task_name": entry["name"],
            "observed_at": observed_at.isoformat(),
            "dispatched": True,
            "scheduled_for": (
                datetime.fromtimestamp(float(after_due), tz=timezone.utc).isoformat()
                if after_due is not None else None
            ),
            "started_at": (
                datetime.fromtimestamp(float(entry["started_at_epoch"]), tz=timezone.utc).isoformat()
                if entry.get("started_at_epoch") is not None else None
            ),
            "interval_seconds": entry["interval_seconds"],
            "phase_locked": entry.get("phase_locked", False),
        })
    return {
        "observed_at": observed_at.isoformat(),
        "events": events,
    }


def _run_scheduler_until_dispatch(
    runtime,
    *,
    start_at: datetime,
    natural_clock: dict[str, datetime],
    dispatch_target: int,
    dispatch_log: list[dict[str, object]],
    task_name: str = "single_brain_proposal_handoff",
    all_dispatch_log: list[dict[str, object]] | None = None,
) -> None:
    """Replay only the existing 30-second scheduler poll, never the callback."""

    observed_at = start_at
    while observed_at <= SCREENING_DUE + timedelta(minutes=30):
        poll = _scheduler_poll(
            runtime,
            observed_at=observed_at,
            natural_clock=natural_clock,
        )
        for event in poll["events"]:
            if all_dispatch_log is not None:
                all_dispatch_log.append(event)
            if event["task_name"] == task_name:
                dispatch_log.append(event)
            if len(dispatch_log) >= dispatch_target:
                return
        observed_at += timedelta(seconds=30)
    raise AssertionError(
        f"scheduler did not naturally dispatch {dispatch_target} task(s): {dispatch_log}"
    )


def _run_scheduler_until_post_screening(
    runtime,
    *,
    start_at: datetime,
    natural_clock: dict[str, datetime],
    proposal_dispatch_log: list[dict[str, object]],
    screening_dispatch_log: list[dict[str, object]],
    screening_attempts: list[dict[str, object]],
    all_dispatch_log: list[dict[str, object]],
    required_screening_attempts: int | None = None,
) -> None:
    """Drive the one authority through screening due and the next proposal."""

    observed_at = start_at
    while observed_at <= SCREENING_DUE + timedelta(minutes=30):
        poll = _scheduler_poll(
            runtime,
            observed_at=observed_at,
            natural_clock=natural_clock,
        )
        for event in poll["events"]:
            all_dispatch_log.append(event)
            if event["task_name"] == "single_brain_proposal_handoff":
                proposal_dispatch_log.append(event)
            elif event["task_name"] == "single_brain_screening_producer":
                screening_dispatch_log.append(event)
        if (
            required_screening_attempts is not None
            and len(screening_attempts) >= required_screening_attempts
        ):
            return
        if required_screening_attempts is None and screening_dispatch_log and proposal_dispatch_log:
            latest_proposal = proposal_dispatch_log[-1]
            eligible_screening = [
                event for event in screening_dispatch_log
                if event["scheduled_for"] is not None
                and latest_proposal["scheduled_for"] is not None
                and _parse_time(event["scheduled_for"])
                <= _parse_time(latest_proposal["scheduled_for"])
            ]
            latest_screening = eligible_screening[-1] if eligible_screening else None
            if (
                latest_screening is not None
                and latest_proposal["scheduled_for"] is not None
                and latest_screening["scheduled_for"] is not None
                and _parse_time(latest_proposal["scheduled_for"])
                >= _parse_time(latest_screening["scheduled_for"])
                and _parse_time(latest_proposal["scheduled_for"]) >= SCREENING_DUE
            ):
                return
        observed_at += timedelta(seconds=30)
    raise AssertionError(
        "scheduler did not naturally reach screening and the following proposal"
    )


def _causal_timeline(
    *,
    dispatch_log: list[dict[str, object]],
    research_completions: list[datetime],
    proposal_raw: dict[str, object] | None,
    proposal_publications: list[datetime],
) -> dict[str, str] | None:
    if proposal_raw is None:
        return None
    _require(dispatch_log, "proposal exists without a natural scheduler dispatch")
    _require(research_completions, "proposal exists without a research completion event")
    _require(proposal_publications, "proposal exists without a publication observation")

    def parse(value: object) -> datetime:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    proposal_produced_at = parse(proposal_raw["created_at"])
    eligible_dispatches = [
        event for event in dispatch_log
        if parse(event["scheduled_for"]) <= proposal_produced_at
    ]
    _require(eligible_dispatches, "proposal timestamp has no preceding scheduler dispatch")
    dispatch = eligible_dispatches[-1]
    scheduler_scheduled_for = parse(dispatch["scheduled_for"])
    scheduler_started_at = parse(dispatch["started_at"])
    eligible_research = [event for event in research_completions if event <= proposal_produced_at]
    _require(eligible_research, "proposal timestamp has no preceding research completion")
    research_completed_at = eligible_research[-1]
    proposal_published_at = proposal_publications[-1]
    ordered = (
        scheduler_scheduled_for,
        scheduler_started_at,
        research_completed_at,
        proposal_produced_at,
        proposal_published_at,
    )
    _require(
        all(left <= right for left, right in zip(ordered, ordered[1:])),
        "DSA causal timeline is not monotonic",
    )
    return {
        "scheduler_scheduled_for": scheduler_scheduled_for.isoformat(),
        "scheduler_started_at": scheduler_started_at.isoformat(),
        "research_completed_at": research_completed_at.isoformat(),
        "proposal_produced_at": proposal_produced_at.isoformat(),
        "proposal_published_at": proposal_published_at.isoformat(),
    }


def _run_natural_day(
    directory: Path,
    *,
    mode: str,
    runner_failure: bool = False,
    start_at: datetime = START_EARLY,
    dispatches: int = 1,
    restart_between_attempts: bool = False,
    scenario_label: str | None = None,
) -> dict[str, object]:
    """Run one fixed-clock day through real scheduler interval/due decisions."""

    from src.config import Config
    from src.investment.proposal import orchestration as orchestration_module
    from src.services.runtime_scheduler import RuntimeSchedulerService, build_single_brain_m2_background_tasks
    from src.storage import DatabaseManager

    label = scenario_label or mode
    database_path = directory / f"{label}-{('failure' if runner_failure else 'normal')}.db"
    state_path = directory / f"{label}-screening-state.json"
    os.environ["DATABASE_PATH"] = str(database_path)
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db_ref = {"db": DatabaseManager.get_instance()}
    generated_contexts: list[str] = []
    screening_calls: list[dict[str, object]] = []
    screening_attempts: list[dict[str, object]] = []
    research_completions: list[datetime] = []
    proposal_publications: list[datetime] = []
    publishers: list[_Publisher] = []
    screening_mode = {
        "success": "valid", "zero": "zero", "holdings_only": "failed",
        "transient_recovery": "transient_recovery",
        "quality_recovery": "quality_recovery",
        "retry_2": "retry_2", "retry_3": "retry_3", "retry_4": "retry_4",
    }.get(mode, "failed")
    if mode == "holdings_only":
        db_ref["db"].save_screening_run({
            "run_id": "screen-run-failed", "strategy": "capital_heat", "market": "cn",
            "candidate_count": 0, "status": "FAILED", "completion_status": "FAILED",
            "latest_completed_trade_date": PRIOR_COMPLETED_TRADE_DATE,
            "decision_cutoff": NOW.isoformat(), "candidates": [],
            "source_errors": ["fixture screening producer unavailable"],
            "warnings": [], "degradation": [],
        })
    config = _runtime_config(holdings=mode == "holdings_only")
    timing_contract = _timing_contract(config)
    _require(
        timing_contract["configuration_admissible"] is True,
        "natural harness target timing configuration is inadmissible before work",
    )
    _require(
        timing_contract == {
            "interval_seconds": 600,
            "cycle_guard_seconds": 120,
            "usable_cycle_budget_seconds": 480,
            "required_candidate_reserve_seconds": 310,
            "generation_backend_timeout_seconds": 300,
            "snapshot_timeout_seconds": 5.0,
            "proposal_timeout_seconds": 5.0,
            "configuration_admissible": True,
        },
        f"harness timing contract drifted: {timing_contract}",
    )

    def publisher_factory(*args, **kwargs):
        publisher = _Publisher(
            *args,
            clock=lambda: natural_clock["now"],
            publish_events=proposal_publications,
            **kwargs,
        )
        publishers.append(publisher)
        return publisher

    def runner_factory(*args, **kwargs):
        return _Runner(
            fail=runner_failure,
            completion_events=research_completions,
            **kwargs,
        )

    def screening_factory(*args, **kwargs):
        attempt_number = len(screening_attempts) + 1
        return _FixtureScreeningService(
            *args,
            mode=screening_mode,
            attempt_number=attempt_number,
            attempt_events=screening_attempts,
            screening_calls=screening_calls,
            observed_at=natural_clock["now"],
            **kwargs,
        )

    original_from_config = orchestration_module.ProposalHandoffLoopService.from_config
    created_services: list[object] = []
    natural_clock = {"now": start_at}

    def capture_from_config(cls, current_config):
        service = original_from_config(current_config)
        service._clock = lambda: natural_clock["now"]
        created_services.append(service)
        return service

    def fake_review(**kwargs):
        return _fake_market_review_factory(db_ref["db"], generated_contexts)(**kwargs)

    def make_runtime():
        tasks = lambda current_config: build_single_brain_m2_background_tasks(
            current_config, config_provider=lambda: config
        )
        return RuntimeSchedulerService(
            config_provider=lambda: config,
            owns_schedule=True,
            background_tasks_provider=tasks,
        )

    runtime = make_runtime()
    dispatch_log: list[dict[str, object]] = []
    screening_dispatch_log: list[dict[str, object]] = []
    all_dispatch_log: list[dict[str, object]] = []
    runtime_status: dict[str, object] = {}
    restart_status: dict[str, object] | None = None
    context_refresh_probe: dict[str, object] = {}
    import src.scheduler as scheduler_module

    def idle_scheduler_loop(scheduler) -> None:
        """Keep the real Scheduler thread alive while the fixed clock polls it."""

        scheduler._running = True
        while scheduler._running and not scheduler.shutdown_handler.should_shutdown:
            scheduler_module.time.sleep(0.01)

    try:
        with patch.object(orchestration_module, "DSAAnalysisCompletionRunner", runner_factory), \
             patch.object(orchestration_module, "CanonicalHttpInvestmentProposalPublisher", publisher_factory), \
             patch.object(orchestration_module, "CanonicalHttpPortfolioSnapshotSource", lambda *a, **k: _SnapshotSource(holdings=mode == "holdings_only", clock=lambda: natural_clock["now"])), \
             patch("src.core.market_review_runtime.build_market_review_runtime", return_value=(None, None, None)), \
             patch("src.services.daily_market_context.run_market_review", side_effect=fake_review), \
             patch("src.services.screening_service.ScreeningService", screening_factory), \
             patch("src.investment.proposal.orchestration.ProposalHandoffLoopService.from_config", classmethod(capture_from_config)), \
             patch("src.investment.screening_scheduler.DEFAULT_STATE_PATH", state_path), \
             patch("src.investment.screening_scheduler._utcnow", lambda: natural_clock["now"].astimezone(timezone.utc)), \
             patch.object(scheduler_module.Scheduler, "run", idle_scheduler_loop):
            with patch.object(scheduler_module.time, "time", return_value=start_at.timestamp()):
                runtime.start()
            runtime_status = runtime.status()
            _require(
                runtime_status["thread_alive"] is True,
                "natural RuntimeSchedulerService thread is not alive",
            )
            _run_scheduler_until_dispatch(
                runtime,
                start_at=start_at,
                natural_clock=natural_clock,
                dispatch_target=1,
                dispatch_log=dispatch_log,
                all_dispatch_log=all_dispatch_log,
            )
            screening_dispatch_log.extend(
                event for event in all_dispatch_log
                if event["task_name"] == "single_brain_screening_producer"
            )
            if dispatches > 1:
                if restart_between_attempts:
                    runtime.stop()
                    restart_at = datetime.fromisoformat(
                        str(dispatch_log[-1]["observed_at"])
                    ) + timedelta(minutes=5)
                    runtime = make_runtime()
                    with patch.object(
                        scheduler_module.time,
                        "time",
                        return_value=restart_at.timestamp(),
                    ):
                        runtime.start()
                    restart_status = runtime.status()
                    _run_scheduler_until_dispatch(
                        runtime,
                        start_at=restart_at,
                        natural_clock=natural_clock,
                        dispatch_target=dispatches,
                        dispatch_log=dispatch_log,
                        all_dispatch_log=all_dispatch_log,
                    )
                else:
                    next_poll = datetime.fromisoformat(
                        str(dispatch_log[-1]["observed_at"])
                    ) + timedelta(seconds=30)
                    _run_scheduler_until_dispatch(
                        runtime,
                        start_at=next_poll,
                        natural_clock=natural_clock,
                        dispatch_target=dispatches,
                        dispatch_log=dispatch_log,
                        all_dispatch_log=all_dispatch_log,
                    )
                screening_dispatch_log[:] = [
                    event for event in all_dispatch_log
                    if event["task_name"] == "single_brain_screening_producer"
                ]
            next_poll = datetime.fromisoformat(
                str(all_dispatch_log[-1]["observed_at"])
            ) + timedelta(seconds=30)
            _run_scheduler_until_post_screening(
                runtime,
                start_at=next_poll,
                natural_clock=natural_clock,
                proposal_dispatch_log=dispatch_log,
                screening_dispatch_log=screening_dispatch_log,
                screening_attempts=screening_attempts,
                all_dispatch_log=all_dispatch_log,
                required_screening_attempts=(
                    int(mode.rsplit("_", 1)[-1])
                    if mode.startswith("retry_") else None
                ),
            )
            context_refresh_probe = _market_context_refresh_probe(
                db_ref["db"], config=config
            )
    finally:
        runtime.stop()

    from src.investment.canonical_cycle import CanonicalCycleRepository

    projection = CanonicalCycleRepository().scheduler_projection(
        scheduler_task_name="single_brain_proposal_handoff"
    )
    try:
        screening_state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        screening_state = {}
    screening_run_key = (
        f"{natural_clock['now'].astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()}"
        ":capital_heat:cn"
    )
    screening_run_state = (screening_state.get("runs") or {}).get(screening_run_key)
    due_publisher = publishers[-1] if publishers else None
    proposals = list(due_publisher.proposals) if due_publisher is not None else []
    causal_timeline = _causal_timeline(
        dispatch_log=dispatch_log,
        research_completions=research_completions,
        proposal_raw=json.loads(proposals[-1].canonical_json()) if proposals else None,
        proposal_publications=proposal_publications,
    )
    lunch_gate = None
    if start_at == START_LUNCH and dispatch_log:
        from src.services.runtime_scheduler import _proposal_handoff_cycle_identity

        scheduled_for = _parse_time(dispatch_log[0]["scheduled_for"])
        cycle_id, _, _ = _proposal_handoff_cycle_identity(config, scheduled_for)
        cycle = CanonicalCycleRepository().get_cycle(cycle_id)
        lunch_gate = {
            "scheduled_for": dispatch_log[0]["scheduled_for"],
            "cycle_id": cycle_id,
            "status": cycle.get("status") if cycle else None,
            "terminal_reason_code": cycle.get("terminal_reason_code") if cycle else None,
            "current_work_state": cycle.get("current_work_state") if cycle else None,
            "persisted": cycle is not None,
        }
    registered_responsibilities = [
        {
            key: entry.get(key)
            for key in (
                "name", "interval_seconds", "run_immediately",
                "daily_due_time", "daily_due_timezone",
            )
            if key in entry
        }
        for entry in build_single_brain_m2_background_tasks(
            config, config_provider=lambda: config
        )
    ]
    candidate_status = {
        "success": "VALID", "zero": "NO_FRESH_CANDIDATES",
        "holdings_only": "DISCOVERY_FAILED", "transient_recovery": "VALID",
        "quality_recovery": "VALID",
        "retry_2": "VALID", "retry_3": "VALID", "retry_4": "VALID",
        "post_due": "VALID", "post_cutoff": "NOT_ENTERED",
    }.get(mode, "DISCOVERY_FAILED")
    DatabaseManager.reset_instance()
    Config.reset_instance()
    return {
        "status": projection.get("last_terminal_status") or projection.get("current_status"),
        "cycle_id": projection.get("last_terminal_cycle_id") or projection.get("current_cycle_id"),
        "candidate_discovery_status": candidate_status,
        "screening_run_state": screening_run_state,
        "proposal_ids": [item.proposal_id for item in proposals],
        "acknowledgement_ids": [f"ack:{item.content_hash[:24]}" for item in proposals],
        "proposals": [json.loads(item.canonical_json()) for item in proposals],
        "timing_contract": timing_contract,
        "causal_timeline": causal_timeline,
        "before_due": {
            "natural_entry": "RuntimeSchedulerService",
            "screening_due": "BEFORE_SCHEDULE_TIME",
            "start_at": start_at.isoformat(),
        },
        "natural_runtime": {
            "entry": "RuntimeSchedulerService.start -> Scheduler._run_background_tasks -> single_brain_proposal_handoff",
            "registered_authority_count": 1,
            "configured_interval_seconds": config.single_brain_m2_interval_minutes * 60,
            "screening_due_at": SCREENING_DUE.isoformat(),
            "screening_calls": screening_calls,
            "screening_attempts": screening_attempts,
            "screening_dispatch_log": screening_dispatch_log,
            "all_dispatch_log": all_dispatch_log,
            "dispatch_log": dispatch_log,
            "registered_responsibilities": registered_responsibilities,
            "lunch_gate": lunch_gate,
            "runtime_scheduler_thread_alive_before_dispatch": runtime_status["thread_alive"],
            "restart_thread_alive": restart_status.get("thread_alive") if restart_status else None,
            "restart_state_path_reused": bool(restart_between_attempts),
        },
        "context_refresh": {
            **context_refresh_probe,
            "generated_count": len(generated_contexts),
            "generated_as_of": generated_contexts,
            "stale_before_second_generation": context_refresh_probe.get(
                "stale_recovery", False
            ),
        },
        "canonical_projection": projection,
        "runtime_contract": {
            "model": "gpt-5.6-luna", "reasoning_effort": "max",
            "fallback_used": False, "invocation": "DETERMINISTIC_STUB_ONLY",
        },
        "safety": {
            "simulation_only": True, "LIVE_TRADING": False,
            "real_provider": False, "real_luna": False,
            "real_worker": False,
        },
    }


def _context_fault_matrix() -> dict[str, dict[str, object]]:
    from src.market_review_contract import validate_market_context_for_slot

    cases = {
        "fresh_complete": _context(), "stale": _context(as_of=NOW - timedelta(hours=2)),
        "future_dated": _context(as_of=NOW + timedelta(hours=1)), "degraded_structural": _context(quality="degraded"),
        "missing_structural": {**_context(), "source_completeness": {"requested": ["indices", "breadth", "sectors", "concepts"], "available": ["indices", "breadth", "concepts"], "missing": ["sectors"], "failed": [], "status": "degraded"}},
        "invalid_pit": {**_context(), "component_timing_status": "PIT_PARTIAL"},
        "persistence_failed": {**_context(), "persistence_status": "PERSISTENCE_FAILED"},
        "identity_conflict": {**_context(), "market_review_id": "fixture-review-other"},
    }
    matrix = {}
    for name, value in cases.items():
        valid, reason = validate_market_context_for_slot(value, trade_date=NOW.date(), as_of=NOW, max_age_seconds=3600)
        matrix[name] = {"valid": valid, "reason": reason}
    return matrix


def _narrative_failure_probe() -> dict[str, object]:
    from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview

    analyzer = MarketAnalyzer(search_service=None, analyzer=None, region="cn", config=SimpleNamespace(report_language="en", market_review_color_scheme="green_up"))
    overview = MarketOverview(
        date=NOW.date().isoformat(), indices=[MarketIndex(code="sh000001", name="SSE Composite", current=3000.0, change_pct=0.5)],
        up_count=2000, down_count=1000, flat_count=500, limit_up_count=40, limit_down_count=10, total_amount=9000.0,
        top_sectors=[{"name": "Fixture Leaders"}], bottom_sectors=[{"name": "Fixture Laggards"}], top_concepts=[{"name": "Fixture Theme"}], bottom_concepts=[{"name": "Fixture Risk"}],
        indices_data_status="available", breadth_data_status="available", sector_data_status="available", concept_data_status="available",
    )
    analyzer.get_market_overview = lambda: overview
    analyzer.search_market_news = lambda: []
    result = analyzer.run_structured_market_review_with_snapshot(narrative_reason="LUNA_TIMEOUT")
    payload = result.structured_payload
    narrative = payload.get("narrative") or {}
    return {"status": narrative.get("status"), "machine_authority": narrative.get("machine_authority"), "structured_quality": (payload.get("data_quality") or {}).get("status"), "machine_context_usable": narrative.get("status") == "FAILED_CLOSED_STRUCTURED_CONTEXT_USABLE" and narrative.get("machine_authority") == "STRUCTURED_MARKET_DATA" and (payload.get("data_quality") or {}).get("status") == "complete"}


def _screening_fault_matrix() -> dict[str, dict[str, object]]:
    from src.investment.m2.screening_candidates import DatabaseScreeningCandidateSource

    holiday_reopen = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)
    matrix = {}
    cases = {
        "missing": ("missing", NOW),
        "stale": ("stale", NOW),
        "failed": ("failed", NOW),
        "quality_failed": ("quality", NOW),
        "current_session_intraday": ("future", NOW),
        "holiday_prior_close_over_72h": ("holiday_prior_close", holiday_reopen),
        "holiday_one_session_older": ("holiday_one_session_older", holiday_reopen),
    }
    for name, (mode, observed_at) in cases.items():
        result = DatabaseScreeningCandidateSource(
            _DiscoveryDB(mode=mode, observed_at=observed_at)
        ).latest_result(
            max_candidates=3,
            # Deliberately smaller than the legacy 72h window: canonical
            # acceptance must be driven by the completed CN session/PIT close.
            max_age=timedelta(seconds=1),
            now=observed_at,
            strategy="capital_heat",
            market="cn",
        )
        matrix[name] = {"status": result.status, "reason": result.reason}
    return matrix


def _proposal_transport_fault_probe(proposal_raw: dict[str, object]) -> dict[str, object]:
    from src.investment.contracts.investment_proposal import InvestmentProposal
    from src.investment.proposal.transport import CanonicalHttpInvestmentProposalPublisher, ProposalTransportUncertain

    class _UnavailableOpener:
        def __init__(self): self.methods: list[str] = []
        def __call__(self, request, **_kwargs):
            self.methods.append(request.get_method())
            raise OSError("fixture Athena endpoint unavailable")

    opener = _UnavailableOpener()
    publisher = CanonicalHttpInvestmentProposalPublisher(url="http://127.0.0.1:8088/api/investment-proposals", timeout_seconds=1, opener=opener)
    try:
        publisher.publish(
            InvestmentProposal.model_validate_json(
                json.dumps(proposal_raw, ensure_ascii=False)
            )
        )
    except ProposalTransportUncertain as exc:
        return {"status": "PENDING_RECONCILIATION", "reason": str(exc), "methods": opener.methods, "post_attempts": opener.methods.count("POST"), "blind_retry_forbidden": opener.methods.count("POST") == 1}
    return {"status": "FAILED_OPEN", "reason": "fixture transport unexpectedly acknowledged", "methods": opener.methods, "post_attempts": opener.methods.count("POST"), "blind_retry_forbidden": False}


def _calendar_fault_probe() -> dict[str, object]:
    from src.investment.m2.natural_admission import evaluate_natural_cycle_admission
    admission = evaluate_natural_cycle_admission(datetime(2026, 8, 25, 2, 0))
    return {"allowed": admission.allowed, "reason": admission.reason_code}


def _unsafe_budget_probe() -> dict[str, object]:
    from src.investment.proposal.orchestration import ProposalHandoffLoopService

    unsafe_values = vars(_runtime_config(holdings=False)).copy()
    unsafe_values["single_brain_m2_cycle_guard_seconds"] = 300
    unsafe = SimpleNamespace(**unsafe_values)
    calls = {"snapshot": 0, "research": 0}
    result = ProposalHandoffLoopService(
        config=unsafe,
        analysis_runner=SimpleNamespace(
            complete=lambda **_kwargs: calls.__setitem__("research", calls["research"] + 1)
        ),
        publisher=SimpleNamespace(publish=lambda _proposal: None),
        snapshot_source=SimpleNamespace(
            capture_snapshot=lambda: calls.__setitem__("snapshot", calls["snapshot"] + 1)
        ),
        clock=lambda: NOW,
    ).run_cycle(scheduled_for=NOW)
    return {
        "timing_contract": _timing_contract(unsafe),
        "status": result.status,
        "blocked_reasons": list(result.blocked_reasons),
        "work_started": calls,
    }


def _ambiguous_linkage_probe() -> dict[str, object]:
    from src.analyzer import AnalysisResult
    from src.repositories.market_review_linkage_repo import MarketReviewLinkageRepository
    from src.storage import DatabaseManager

    db = DatabaseManager.get_instance()
    first = _context()
    second = {**first, "context_id": "market-context:fixture-other", "market_review_id": "fixture-review-other", "source_task_id": "fixture-review-other", "provenance": {"source_task_id": "fixture-review-other"}}
    for query_id, context in (("ambiguous-a", first), ("ambiguous-b", second)):
        db.save_analysis_history(result=AnalysisResult(code="__market_review__", name="Fixture Market Review", sentiment_score=50, trend_prediction="fixture", operation_advice="fixture", analysis_summary="fixture"), query_id=query_id, report_type="market_review", news_content="fixture", context_snapshot={"market_review_payload": {"market_context": context}}, save_snapshot=True)
    context, reason = MarketReviewLinkageRepository(db).resolve_market_context(trade_date=NOW.date(), as_of=NOW, max_age_seconds=3600)
    return {"context_resolved": context is not None, "reason": reason}


def _run_scenarios(directory: Path) -> dict[str, dict[str, object]]:
    return {
        "success": _run_natural_day(directory, mode="success", start_at=START_OPEN),
        "zero": _run_natural_day(directory, mode="zero", scenario_label="zero"),
        "holdings_only": _run_natural_day(directory, mode="holdings_only"),
        "luna_timeout": _run_natural_day(directory, mode="success", runner_failure=True, scenario_label="luna_timeout"),
        "transient_recovery": _run_natural_day(
            directory, mode="transient_recovery", dispatches=2,
        ),
        "quality_recovery": _run_natural_day(
            directory, mode="quality_recovery", dispatches=2,
        ),
        "retry_success_2": _run_natural_day(
            directory, mode="retry_2", scenario_label="retry_success_2",
        ),
        "retry_success_3": _run_natural_day(
            directory, mode="retry_3", scenario_label="retry_success_3",
        ),
        "retry_success_4": _run_natural_day(
            directory, mode="retry_4", scenario_label="retry_success_4",
        ),
        "restart_recovery": _run_natural_day(
            directory, mode="transient_recovery", dispatches=2,
            restart_between_attempts=True, scenario_label="restart_recovery",
        ),
        "restart_10_17": _run_natural_day(
            directory, mode="success", start_at=START_EARLY,
            scenario_label="restart_10_17",
        ),
        "lunch_start": _run_natural_day(
            directory, mode="success", start_at=START_LUNCH,
            scenario_label="lunch_start",
        ),
        "afternoon_restart": _run_natural_day(
            directory, mode="success",
            start_at=datetime(2026, 8, 25, 4, 57, tzinfo=timezone.utc),
            scenario_label="afternoon_restart",
        ),
        "start_phase_mid": _run_natural_day(
            directory, mode="success", start_at=START_MID,
            scenario_label="start_phase_mid",
        ),
        "start_phase_near_due": _run_natural_day(
            directory, mode="success", start_at=START_NEAR_DUE,
            scenario_label="start_phase_near_due",
        ),
        "post_due": _run_natural_day(
            directory, mode="success", start_at=START_POST_DUE,
            scenario_label="post_due",
        ),
        "post_cutoff": _run_natural_day(
            directory, mode="success", start_at=START_AFTER_CUTOFF,
            scenario_label="post_cutoff",
        ),
    }


def _proposal_cadence_matrix() -> dict[str, dict[str, object]]:
    """Prove the real Scheduler phase grid without invoking a callback."""

    from src.scheduler import Scheduler

    cases = {
        "08:00": START_OPEN,
        "10:17": START_EARLY,
        "11:31": START_LUNCH,
        "12:57": datetime(2026, 8, 25, 4, 57, tzinfo=timezone.utc),
        "14:44": START_NEAR_DUE,
    }
    expected = {
        "08:00": "09:30",
        "10:17": "10:20",
        "11:31": "11:40",
        "12:57": "13:00",
        "14:44": "14:50",
    }
    matrix = {}
    for label, registration in cases.items():
        last_run = Scheduler._initial_background_last_run(
            registration.timestamp(),
            interval_seconds=600,
            daily_due_time="09:30",
            daily_due_timezone="Asia/Shanghai",
        )
        due = datetime.fromtimestamp(last_run + 600, tz=timezone.utc)
        local_due = due.astimezone(ZoneInfo("Asia/Shanghai"))
        _require(local_due.strftime("%H:%M") == expected[label], f"proposal cadence drifted for {label}")
        matrix[label] = {
            "registration": registration.isoformat(),
            "next_natural_due": due.isoformat(),
            "next_natural_due_bjt": local_due.strftime("%H:%M"),
            "expected": expected[label],
            "screening_due_bjt": "14:45",
            "screening_phase_lock": False,
            "lunch_outcome": "SESSION_GATED_ZERO_WORK" if label == "11:31" else None,
        }
    return matrix


def _screening_retry_contract() -> dict[str, object]:
    from src.investment.screening_scheduler import (
        RETRY_DELAYS_SECONDS,
        SESSION_CUTOFF_TIME,
        SCHEDULE_TIME,
    )

    due = datetime(2026, 8, 25, SCHEDULE_TIME.hour, SCHEDULE_TIME.minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    cumulative = 0
    attempts = []
    for attempt, delay in enumerate(RETRY_DELAYS_SECONDS, start=1):
        cumulative += delay if attempt > 1 else 0
        observed = due + timedelta(seconds=cumulative)
        attempts.append({"attempt": attempt, "delay_before_seconds": delay, "natural_at": observed.isoformat()})
    cutoff = due.replace(hour=SESSION_CUTOFF_TIME.hour, minute=SESSION_CUTOFF_TIME.minute)
    _require(all(_parse_time(item["natural_at"]) < cutoff.astimezone(timezone.utc) for item in attempts), "screening retry reaches beyond session cutoff")
    return {
        "due_bjt": SCHEDULE_TIME.strftime("%H:%M"),
        "cutoff_bjt": SESSION_CUTOFF_TIME.strftime("%H:%M"),
        "declared_delays_seconds": list(RETRY_DELAYS_SECONDS),
        "reachable_attempts": attempts,
        "post_close_catchup": "FORBIDDEN",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("system_day", "success", "zero", "holdings_only"), default="system_day")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pallas-dsa-system-day-") as temporary:
        directory = Path(temporary)
        scenarios = _run_scenarios(directory) if args.scenario == "system_day" else {args.scenario: _run_natural_day(directory, mode=args.scenario)}
        success = scenarios["success"]
        _require(success["status"] == "SUCCEEDED", "natural success path did not complete")
        _require(success["candidate_discovery_status"] == "VALID", "natural discovery was not valid")
        _require(success["proposal_ids"], "natural success path lacks proposal")
        _require(success["context_refresh"]["stale_before_second_generation"], "stale context was reused instead of refreshed")
        _require(success["natural_runtime"]["registered_authority_count"] == 1, "scheduler authority count changed")
        _require(
            success["natural_runtime"]["configured_interval_seconds"] == 600,
            "primary harness did not use the configured ten-minute proposal interval",
        )
        _require(
            [item["name"] for item in success["natural_runtime"]["registered_responsibilities"]]
            == ["single_brain_proposal_handoff", "single_brain_screening_producer"],
            "proposal and screening responsibilities did not share the single runtime authority",
        )
        _require(
            success["natural_runtime"]["registered_responsibilities"][0]["daily_due_time"] == "09:30"
            and success["natural_runtime"]["registered_responsibilities"][1]["daily_due_time"] == "14:45",
            "proposal and screening responsibilities did not retain independent due anchors",
        )
        _require(
            len(success["natural_runtime"]["dispatch_log"]) >= 1
            and all(item["dispatched"] for item in success["natural_runtime"]["dispatch_log"]),
            "primary harness did not use the natural interval/due dispatcher",
        )
        if "zero" in scenarios:
            _require(scenarios["zero"]["status"] == "NO_ACTION", "zero-candidate path was not durable NO_ACTION")
            _require(not scenarios["zero"]["proposal_ids"], "zero-candidate path emitted a proposal")
        if "holdings_only" in scenarios:
            _require(scenarios["holdings_only"]["status"] in {"PARTIAL", "COMPLETED"}, "holdings-only path did not continue safely")
            _require(scenarios["holdings_only"]["candidate_discovery_status"] == "DISCOVERY_FAILED", "discovery failure was hidden")
        for phase_name in ("start_phase_mid", "start_phase_near_due"):
            _require(
                scenarios[phase_name]["status"] == "SUCCEEDED"
                and scenarios[phase_name]["proposal_ids"],
                f"{phase_name} did not reach the natural proposal path",
            )
        _require(
            scenarios["restart_10_17"]["natural_runtime"]["dispatch_log"][0]["scheduled_for"]
            == "2026-08-25T02:20:00+00:00",
            "10:17 restart phase-locked the proposal task instead of using the 10-minute grid",
        )
        _require(
            scenarios["lunch_start"]["natural_runtime"]["lunch_gate"]["persisted"] is True
            and scenarios["lunch_start"]["natural_runtime"]["lunch_gate"]["status"] == "SKIPPED"
            and scenarios["lunch_start"]["natural_runtime"]["lunch_gate"]["terminal_reason_code"] == "OUTSIDE_TRADING_SESSION",
            "lunch session gate did not persist a truthful zero-work terminal cycle",
        )
        _require(
            scenarios["afternoon_restart"]["natural_runtime"]["dispatch_log"][0]["scheduled_for"]
            == "2026-08-25T05:00:00+00:00",
            "12:57 restart did not align to the next legal 13:00 grid slot",
        )
        for recovery_name in ("transient_recovery", "quality_recovery", "restart_recovery"):
            recovery = scenarios[recovery_name]
            _require(
                recovery["status"] == "SUCCEEDED"
                and recovery["proposal_ids"]
                and [item["attempt"] for item in recovery["natural_runtime"]["screening_attempts"]] == [1, 2]
                and [item["at"] for item in recovery["natural_runtime"]["screening_attempts"]]
                == ["2026-08-25T06:45:00+00:00", "2026-08-25T06:45:30+00:00"],
                f"{recovery_name} did not recover through later natural screening attempts",
            )
        expected_retry_times = [
            "2026-08-25T06:45:00+00:00",
            "2026-08-25T06:45:30+00:00",
            "2026-08-25T06:47:30+00:00",
            "2026-08-25T06:57:30+00:00",
        ]
        for retry_name, expected_attempts in (
            ("retry_success_2", 2),
            ("retry_success_3", 3),
            ("retry_success_4", 4),
        ):
            recovery = scenarios[retry_name]
            actual_attempts = recovery["natural_runtime"]["screening_attempts"]
            _require(
                recovery["screening_run_state"]
                and recovery["screening_run_state"]["status"] == "COMPLETED"
                and recovery["screening_run_state"]["attempts"] == expected_attempts
                and [item["attempt"] for item in actual_attempts]
                == list(range(1, expected_attempts + 1))
                and [item["at"] for item in actual_attempts]
                == expected_retry_times[:expected_attempts],
                f"{retry_name} was not accepted on the natural retry clock",
            )
        _require(
            scenarios["restart_recovery"]["natural_runtime"]["restart_state_path_reused"],
            "restart recovery did not reuse the persisted screening state",
        )
        _require(
            success["natural_runtime"]["dispatch_log"][0]["scheduled_for"] == "2026-08-25T01:30:00+00:00"
            and success["natural_runtime"]["dispatch_log"][0]["phase_locked"] is True,
            "primary dispatch did not prove the 09:30 anchored proposal grid",
        )
        cadence_matrix = _proposal_cadence_matrix()
        retry_contract = _screening_retry_contract()
        _require(
            {label: item["next_natural_due_bjt"] for label, item in cadence_matrix.items()}
            == {"08:00": "09:30", "10:17": "10:20", "11:31": "11:40", "12:57": "13:00", "14:44": "14:50"},
            "proposal cadence matrix did not use the session grid",
        )
        _require(
            retry_contract["due_bjt"] == "14:45"
            and retry_contract["cutoff_bjt"] == "15:00"
            and retry_contract["post_close_catchup"] == "FORBIDDEN"
            and retry_contract["reachable_attempts"][-1]["natural_at"] == "2026-08-25T14:57:30+08:00",
            "screening retry contract did not remain bounded before the session cutoff",
        )
        _require(
            success["timing_contract"] == {
                "interval_seconds": 600,
                "cycle_guard_seconds": 120,
                "usable_cycle_budget_seconds": 480,
                "required_candidate_reserve_seconds": 310,
                "generation_backend_timeout_seconds": 300,
                "snapshot_timeout_seconds": 5.0,
                "proposal_timeout_seconds": 5.0,
                "configuration_admissible": True,
            },
            "primary Golden Path did not use the exact admissible target timing contract",
        )
        for causal_name in (
            "success",
            "start_phase_mid",
            "start_phase_near_due",
            "post_due",
            "transient_recovery",
            "quality_recovery",
            "restart_recovery",
        ):
            _require(
                scenarios[causal_name]["causal_timeline"] is not None,
                f"{causal_name} lacks a monotonic causal timeline",
            )
        _require(
            scenarios["post_due"]["natural_runtime"]["dispatch_log"][-1]["scheduled_for"]
            == "2026-08-25T06:50:00+00:00"
            and scenarios["post_due"]["status"] == "SUCCEEDED"
            and scenarios["post_due"]["proposal_ids"],
            "post-due natural grid retry did not complete legally",
        )
        _require(
            scenarios["post_cutoff"]["status"] == "SKIPPED"
            and not scenarios["post_cutoff"]["proposal_ids"]
            and not scenarios["post_cutoff"]["natural_runtime"]["screening_attempts"]
            and scenarios["post_cutoff"]["canonical_projection"]["last_terminal_reason"]["code"]
            == "OUTSIDE_TRADING_SESSION",
            "post-cutoff natural entry did not persist a truthful zero-work outcome",
        )
        _require(
            all(
                recovery["natural_runtime"]["screening_attempts"][0]["attempt"] == 1
                and recovery["natural_runtime"]["screening_attempts"][1]["attempt"] == 2
                for recovery in (scenarios["transient_recovery"], scenarios["quality_recovery"], scenarios["restart_recovery"])
            ),
            "recovery scenarios did not preserve producer attempt identity across natural ticks",
        )
        screening_faults = _screening_fault_matrix()
        expected_screening_faults = {
            "missing": "DISCOVERY_MISSING",
            "stale": "DISCOVERY_STALE",
            "failed": "DISCOVERY_FAILED",
            "quality_failed": "DISCOVERY_QUALITY_FAILED",
            "current_session_intraday": "DISCOVERY_QUALITY_FAILED",
            "holiday_prior_close_over_72h": "VALID",
            "holiday_one_session_older": "DISCOVERY_STALE",
        }
        _require(
            {name: value["status"] for name, value in screening_faults.items()} == expected_screening_faults,
            "screening freshness/quality fault matrix did not fail closed by canonical session contract",
        )
        _require(
            scenarios["luna_timeout"]["status"] == "FAILED"
            and not scenarios["luna_timeout"]["proposal_ids"]
            and "TimeoutError" in str(scenarios["luna_timeout"]["canonical_projection"].get("last_error")),
            "Luna timeout did not terminate the cycle fail-closed",
        )
        unsafe_budget = _unsafe_budget_probe()
        _require(
            unsafe_budget["timing_contract"]["configuration_admissible"] is False
            and unsafe_budget["status"] == "FAILED_CLOSED"
            and unsafe_budget["work_started"] == {"snapshot": 0, "research": 0},
            "unsafe target timing configuration did not fail closed before work",
        )
        payload = {
            "repo": "DSA", "harness": "PALLAS_SYSTEM_REASSEMBLY_GOLDEN_PATH",
            "schema_version": "pallas-system-reassembly-harness-v5", "fixed_clock": NOW.isoformat(),
            "synthetic_trading_day": {
                "natural_entry": "RuntimeSchedulerService",
                "scheduler_dispatch_path": "Scheduler._run_background_tasks",
                "screening_due_at": SCREENING_DUE.isoformat(),
                "configured_interval_seconds": success["natural_runtime"]["configured_interval_seconds"],
                "phase_lock": {
                    "daily_due_time": "09:30",
                    "daily_due_timezone": "Asia/Shanghai",
                    "first_dispatch_is_scheduler_due": True,
                },
                "screening_responsibility": {
                    "task_name": "single_brain_screening_producer",
                    "daily_due_time": "14:45",
                    "daily_due_timezone": "Asia/Shanghai",
                    "same_runtime_authority": True,
                },
                "registered_responsibilities": success["natural_runtime"]["registered_responsibilities"],
                "proposal_cadence_matrix": cadence_matrix,
                "screening_retry_contract": retry_contract,
                "direct_callback_invocation": False,
                "manual_run_now": False,
                "legal_session": True, "complete": True,
            },
            "timing_contract": success["timing_contract"],
            "causal_timeline": success["causal_timeline"],
            "scenarios": scenarios,
            "evidence": {
                "context_fault_matrix": _context_fault_matrix(), "narrative_failure": _narrative_failure_probe(),
                "screening_fault_matrix": screening_faults, "proposal_transport_fault": _proposal_transport_fault_probe(success["proposals"][0]),
                "calendar_fault": _calendar_fault_probe(), "unsafe_budget": unsafe_budget,
                "ambiguous_linkage": _ambiguous_linkage_probe(),
                "p008_strategy_evidence": success["proposals"][0].get("strategy_evidence"), "luna_timeout": scenarios.get("luna_timeout"),
            },
            "runtime_contract": {"model": "gpt-5.6-luna", "reasoning_effort": "max", "fallback_used": False, "invocation": "DETERMINISTIC_STUB_ONLY"},
            "safety": {
                "simulation_only": True,
                "LIVE_TRADING": False,
                "production_modified": False,
                "production_restarted": False,
                "candidate_fixture_restart_recovery": True,
                "deployed": False,
                "run_now": False,
                "new_mission_created": False,
                "real_provider": False,
                "real_luna": False,
                "real_worker": False,
                "orders_submitted": False,
            },
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
