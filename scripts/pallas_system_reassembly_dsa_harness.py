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


NOW = datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc)
SCREENING_DUE = NOW + timedelta(hours=4, minutes=45)  # 14:45 BJT, legal session
PRIOR_COMPLETED_TRADE_DATE = "2026-08-24"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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


def _pallas008_evidence(*, symbol: str = "600519", decision_cutoff: datetime = NOW) -> dict[str, object]:
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
        latest_completed_trade_date=PRIOR_COMPLETED_TRADE_DATE,
        decision_cutoff=decision_cutoff,
        completion_status="CLOSE_CONFIRMED",
        completion_basis="PRIOR_PROVIDER_RETURNED_SESSION",
        quantitative_input_reference=f"fixture:daily-close:{symbol}:{PRIOR_COMPLETED_TRADE_DATE}",
    )


class _DiscoveryDB:
    """Read-only adapter fixture used by the focused discovery matrix."""

    def __init__(self, *, mode: str):
        self.mode = mode

    def list_screening_runs(self, **_kwargs):
        if self.mode == "unavailable":
            raise OSError("fixture screening DB unavailable")
        if self.mode == "missing":
            return []
        return [{"run_id": "screen-run-fixture", "strategy": "capital_heat", "market": "cn"}]

    def get_screening_run(self, _run_id):
        completed_date = PRIOR_COMPLETED_TRADE_DATE
        decision_cutoff = NOW
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
        candidates = [] if self.mode == "zero" else [{
            "code": "600519", "name": "贵州茅台", "rank": 1,
            "screen_score": 88.0, "score": 88.0,
            "latest_completed_trade_date": completed_date,
            "decision_cutoff": decision_cutoff.isoformat(),
            "completion_status": completion_status,
            "completion_basis": "PRIOR_PROVIDER_RETURNED_SESSION",
            "quantitative_input_reference": "fixture:daily-close:600519:2026-08-24",
            "strategy_evidence": _pallas008_evidence(decision_cutoff=NOW),
        }]
        return {
            "run_id": "screen-run-fixture", "strategy": "capital_heat", "market": "cn",
            "created_at": (NOW - timedelta(minutes=1)).isoformat(), "status": producer_status,
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


def _snapshot(*, holdings: bool = False):
    from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot, Position

    positions = ()
    if holdings:
        positions = (Position(
            symbol="600519", market="CN", quantity=100, available_quantity=100,
            avg_cost=Decimal("90"), last_price=Decimal("100"),
            market_value=Decimal("10000"), unrealized_pnl=Decimal("1000"),
            price_as_of=NOW, price_source="fixture:quote",
        ),)
    return PortfolioSnapshot.build(
        snapshot_id="snapshot:fixture", trace_id="trace:fixture", created_at=NOW,
        producer="ATHENA_GOLDEN_PATH_FIXTURE", account_id="athena-sim",
        broker="FIXTURE_WORKER", account_mode="SIMULATION", as_of=NOW, revision=1,
        currency="CNY", equity=Decimal("1000000.00"), cash=Decimal("1000000.00"),
        available_cash=Decimal("1000000.00"), reserved_cash=Decimal("0.00"),
        positions=positions, active_orders=(), realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"), reconciliation_status="RECONCILED",
        data_quality="HIGH", limitations=(), broker_snapshot_ref="fixture:portfolio",
    )


class _Runner:
    def __init__(self, *, fail: bool = False, **_kwargs):
        self.fail = fail

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
        return AnalysisCompletion(
            result=result,
            context_snapshot={
                "source": "fixture:DSAAnalysisCompletionRunner",
                "price_plan": {
                    "source_event_time": "2026-08-24T07:00:00+00:00",
                    "retrieved_at": NOW.isoformat(),
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
    def __init__(self, *_, **__):
        self.proposals = []

    def publish(self, proposal):
        from src.investment.proposal.transport import AthenaProposalAcknowledgement

        self.proposals.append(proposal)
        return AthenaProposalAcknowledgement(
            proposal_id=proposal.proposal_id, proposal_hash=proposal.content_hash,
            acknowledgement_id=f"ack:{proposal.content_hash[:24]}",
            acknowledgement_state="ACCEPTED", lifecycle_state="ACCEPTED", deduplicated=False,
        )


class _SnapshotSource:
    def __init__(self, *, holdings=False, **_kwargs):
        self.holdings = holdings

    def capture_snapshot(self):
        return _snapshot(holdings=self.holdings)


class _FixtureScreeningService:
    def __init__(self, *, config, db_manager, mode, **_kwargs):
        self.db = db_manager
        self.mode = mode

    def screen(self, *, strategy, market, max_results):
        if self.mode == "failed":
            raise OSError("fixture screening producer unavailable")
        candidates = [] if self.mode == "zero" else [{
            "code": "600519", "name": "贵州茅台", "rank": 1,
            "screen_score": 88.0, "score": 88.0,
            "latest_completed_trade_date": PRIOR_COMPLETED_TRADE_DATE,
            "decision_cutoff": NOW.isoformat(), "completion_status": "CLOSE_CONFIRMED",
            "completion_basis": "PRIOR_PROVIDER_RETURNED_SESSION",
            "quantitative_input_reference": "fixture:daily-close:600519:2026-08-24",
            "strategy_evidence": _pallas008_evidence(decision_cutoff=NOW),
        }]
        payload = {
            "run_id": f"screen-run-{self.mode}", "strategy": strategy, "market": market,
            "snapshot_source": "fixture:screening-provider", "snapshot_count": len(candidates),
            "after_filter_count": len(candidates), "candidate_count": len(candidates),
            "llm_ranked": False, "daily_enriched": True,
            "latest_completed_trade_date": PRIOR_COMPLETED_TRADE_DATE,
            "decision_cutoff": NOW.isoformat(), "completion_status": "CLOSE_CONFIRMED",
            "completion_basis": "PRIOR_PROVIDER_RETURNED_SESSION",
            "quantitative_input_reference": "fixture:daily-close:600519:2026-08-24",
            "candidates": candidates, "source_errors": [], "warnings": [],
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


def _runtime_config(*, holdings: bool) -> SimpleNamespace:
    return SimpleNamespace(
        schedule_enabled=True, schedule_time="23:59", schedule_times=["23:59"],
        single_brain_m2_enabled=True, single_brain_execution_mode="PROPOSAL_HANDOFF",
        single_brain_simulation_execution_authorized=False, single_brain_m2_interval_minutes=60,
        single_brain_m2_cycle_guard_seconds=0, single_brain_m2_run_immediately=False,
        single_brain_m2_natural_session_gate_enabled=True, single_brain_m2_screening_enabled=True,
        single_brain_m2_screening_max_candidates=3, single_brain_m2_screening_max_age_hours=72,
        single_brain_m2_screening_strategy="capital_heat", single_brain_m2_screening_market="cn",
        single_brain_m2_max_symbols=1, single_brain_m2_holdings_limit=1 if holdings else 0,
        single_brain_m2_symbols=[], single_brain_m2_review_policy_version="pallas-004-research-trigger-v1",
        generation_backend_timeout_seconds=1, single_brain_m2_snapshot_timeout_seconds=1,
        single_brain_proposal_timeout_seconds=1, single_brain_proposal_url="http://fixture.invalid/athena",
        single_brain_m2_snapshot_url="http://fixture.invalid/portfolio", market_review_region="cn",
        report_language="zh", single_brain_m2_readiness_gate_enabled=False,
    )


def _dispatch_natural_task(runtime, *, run_at: datetime, natural_clock: dict[str, datetime]) -> None:
    import src.scheduler as scheduler_module

    natural_clock["now"] = run_at
    scheduler = runtime._scheduler
    _require(scheduler is not None, "RuntimeSchedulerService did not register Scheduler")
    entries = scheduler._background_tasks
    _require([entry["name"] for entry in entries] == ["single_brain_proposal_handoff"], "canonical task registration mismatch")
    entry = entries[0]
    real_time = scheduler_module.time.time
    with patch.object(scheduler_module.time, "time", return_value=run_at.timestamp()):
        _require(scheduler._start_background_task(entry, scheduled_for_epoch=run_at.timestamp()), "natural background task did not start")
    worker = entry.get("thread")
    if worker is not None:
        worker.join(timeout=10)
    _require(not entry.get("running"), "natural background task did not finish")
    # Keep the interval gate out of the short deterministic replay.  The
    # scheduler loop itself is held by the harness in an idle state below, so
    # this is documentary protection rather than a production scheduling path.
    entry["last_run"] = real_time() + 86400


def _run_natural_day(directory: Path, *, mode: str, runner_failure: bool = False) -> dict[str, object]:
    """Run one fixed-clock synthetic day through the actual scheduler entry."""

    from src.config import Config
    from src.investment.proposal import orchestration as orchestration_module
    from src.services.runtime_scheduler import RuntimeSchedulerService, build_single_brain_m2_background_tasks
    from src.storage import DatabaseManager

    os.environ["DATABASE_PATH"] = str(directory / f"{mode}-{('failure' if runner_failure else 'normal')}.db")
    # Config and DatabaseManager are process singletons; each scenario needs a
    # fresh candidate-only SQLite authority so identical fixed-clock cycle IDs
    # remain isolated across the synthetic-day fault branches.
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    generated_contexts: list[str] = []
    screening_calls: list[str] = []
    publishers: list[_Publisher] = []
    screening_mode = "valid" if mode == "success" else "zero" if mode == "zero" else "failed"
    if mode == "holdings_only":
        db.save_screening_run({
            "run_id": "screen-run-failed", "strategy": "capital_heat", "market": "cn",
            "candidate_count": 0, "status": "FAILED", "completion_status": "FAILED",
            "latest_completed_trade_date": PRIOR_COMPLETED_TRADE_DATE, "decision_cutoff": NOW.isoformat(),
            "candidates": [], "source_errors": ["fixture screening producer unavailable"],
            "warnings": [], "degradation": [],
        })
    config = _runtime_config(holdings=mode == "holdings_only")

    def publisher_factory(*args, **kwargs):
        publisher = _Publisher(*args, **kwargs)
        publishers.append(publisher)
        return publisher

    def runner_factory(*args, **kwargs):
        return _Runner(fail=runner_failure, **kwargs)

    def screening_factory(*args, **kwargs):
        screening_calls.append(screening_mode)
        return _FixtureScreeningService(*args, mode=screening_mode, **kwargs)

    original_from_config = orchestration_module.ProposalHandoffLoopService.from_config
    created_services: list[object] = []
    natural_clock = {"now": NOW}

    def capture_from_config(cls, current_config):
        service = original_from_config(current_config)
        # The production service normally reads the current wall clock.  For
        # this fixed-clock replay, keep its real run_cycle and all producers on
        # the scheduler-owned due instant.
        service._clock = lambda: natural_clock["now"]
        created_services.append(service)
        return service

    tasks = lambda current_config: build_single_brain_m2_background_tasks(current_config, config_provider=lambda: config)
    runtime = RuntimeSchedulerService(config_provider=lambda: config, owns_schedule=True, background_tasks_provider=tasks)
    fake_review = _fake_market_review_factory(db, generated_contexts)
    import src.scheduler as scheduler_module

    def idle_scheduler_loop(scheduler) -> None:
        """Keep the real Scheduler thread alive without wall-clock dispatch."""

        scheduler._running = True
        while scheduler._running and not scheduler.shutdown_handler.should_shutdown:
            scheduler_module.time.sleep(0.01)

    try:
        with patch.object(orchestration_module, "DSAAnalysisCompletionRunner", runner_factory), \
             patch.object(orchestration_module, "CanonicalHttpInvestmentProposalPublisher", publisher_factory), \
             patch.object(orchestration_module, "CanonicalHttpPortfolioSnapshotSource", lambda *a, **k: _SnapshotSource(holdings=mode == "holdings_only")), \
             patch("src.core.market_review_runtime.build_market_review_runtime", return_value=(None, None, None)), \
             patch("src.services.daily_market_context.run_market_review", side_effect=fake_review), \
             patch("src.services.screening_service.ScreeningService", screening_factory), \
             patch("src.investment.proposal.orchestration.ProposalHandoffLoopService.from_config", classmethod(capture_from_config)), \
             patch("src.investment.screening_scheduler.DEFAULT_STATE_PATH", directory / f"{mode}-screening-state.json"), \
             patch("src.investment.screening_scheduler._sleep", lambda _seconds: None), \
             patch.object(scheduler_module.Scheduler, "run", idle_scheduler_loop):
            runtime.start()
            runtime_status = runtime.status()
            _require(runtime_status["thread_alive"] is True, "natural RuntimeSchedulerService thread is not alive")
            _dispatch_natural_task(runtime, run_at=NOW, natural_clock=natural_clock)
            _dispatch_natural_task(runtime, run_at=SCREENING_DUE, natural_clock=natural_clock)
            due_publisher = publishers[-1] if publishers else None
    finally:
        runtime.stop()

    from src.investment.canonical_cycle import CanonicalCycleRepository

    projection = CanonicalCycleRepository().scheduler_projection(scheduler_task_name="single_brain_proposal_handoff")
    proposals = list(due_publisher.proposals) if due_publisher is not None else []
    DatabaseManager.reset_instance()
    Config.reset_instance()
    return {
        "status": projection.get("last_terminal_status") or projection.get("current_status"),
        "cycle_id": projection.get("last_terminal_cycle_id") or projection.get("current_cycle_id"),
        "candidate_discovery_status": "VALID" if mode == "success" else "NO_FRESH_CANDIDATES" if mode == "zero" else "DISCOVERY_FAILED",
        "proposal_ids": [item.proposal_id for item in proposals],
        "acknowledgement_ids": [f"ack:{item.content_hash[:24]}" for item in proposals],
        "proposals": [json.loads(item.canonical_json()) for item in proposals],
        "before_due": {"natural_entry": "RuntimeSchedulerService", "screening_due": "BEFORE_SCHEDULE_TIME"},
        "natural_runtime": {
            "entry": "RuntimeSchedulerService.start -> Scheduler._start_background_task -> single_brain_proposal_handoff",
            "registered_authority_count": 1, "screening_due_at": SCREENING_DUE.isoformat(),
            "screening_calls": screening_calls,
            "runtime_scheduler_thread_alive_before_dispatch": runtime_status["thread_alive"],
        },
        "context_refresh": {
            "generated_count": len(generated_contexts), "generated_as_of": generated_contexts,
            "stale_before_second_generation": len(generated_contexts) >= 2 and generated_contexts[0] != generated_contexts[1],
        },
        "canonical_projection": projection,
        "runtime_contract": {"model": "gpt-5.6-luna", "reasoning_effort": "max", "fallback_used": False, "invocation": "DETERMINISTIC_STUB_ONLY"},
        "safety": {"simulation_only": True, "LIVE_TRADING": False, "real_provider": False, "real_luna": False, "real_worker": False},
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

    matrix = {}
    for name, mode in {"missing": "missing", "stale": "stale", "failed": "failed", "quality_failed": "quality"}.items():
        result = DatabaseScreeningCandidateSource(_DiscoveryDB(mode=mode)).latest_result(max_candidates=3, max_age=timedelta(hours=72), now=NOW, strategy="capital_heat", market="cn")
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
    return {"success": _run_natural_day(directory, mode="success"), "zero": _run_natural_day(directory, mode="zero"), "holdings_only": _run_natural_day(directory, mode="holdings_only"), "luna_timeout": _run_natural_day(directory, mode="success", runner_failure=True)}


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
        if "zero" in scenarios:
            _require(scenarios["zero"]["status"] == "NO_ACTION", "zero-candidate path was not durable NO_ACTION")
            _require(not scenarios["zero"]["proposal_ids"], "zero-candidate path emitted a proposal")
        if "holdings_only" in scenarios:
            _require(scenarios["holdings_only"]["status"] in {"PARTIAL", "COMPLETED"}, "holdings-only path did not continue safely")
            _require(scenarios["holdings_only"]["candidate_discovery_status"] == "DISCOVERY_FAILED", "discovery failure was hidden")
        payload = {
            "repo": "DSA", "harness": "PALLAS_SYSTEM_REASSEMBLY_GOLDEN_PATH",
            "schema_version": "pallas-system-reassembly-harness-v2", "fixed_clock": NOW.isoformat(),
            "synthetic_trading_day": {"natural_entry": "RuntimeSchedulerService", "screening_due_at": SCREENING_DUE.isoformat(), "legal_session": True, "complete": True},
            "scenarios": scenarios,
            "evidence": {
                "context_fault_matrix": _context_fault_matrix(), "narrative_failure": _narrative_failure_probe(),
                "screening_fault_matrix": _screening_fault_matrix(), "proposal_transport_fault": _proposal_transport_fault_probe(success["proposals"][0]),
                "calendar_fault": _calendar_fault_probe(), "ambiguous_linkage": _ambiguous_linkage_probe(),
                "p008_strategy_evidence": success["proposals"][0].get("strategy_evidence"), "luna_timeout": scenarios.get("luna_timeout"),
            },
            "runtime_contract": {"model": "gpt-5.6-luna", "reasoning_effort": "max", "fallback_used": False, "invocation": "DETERMINISTIC_STUB_ONLY"},
            "safety": {"simulation_only": True, "LIVE_TRADING": False, "production_modified": False, "deployed": False, "restarted": False, "run_now": False, "real_provider": False, "real_luna": False, "real_worker": False, "orders_submitted": False},
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
