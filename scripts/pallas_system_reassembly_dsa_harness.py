#!/usr/bin/env python3
"""Deterministic DSA half of the PALLAS system-reassembly harness.

This command is invoked by Athena's top-level harness.  It uses the real DSA
proposal handoff, contract builder, screening adapter, and MarketContext
admission validator, while every database/provider/transport dependency is an
isolated fixture or stub.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace


NOW = datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc)


def _context(*, as_of: datetime = NOW, quality: str = "complete") -> dict[str, object]:
    provenance = {
        component: {
            "status": "PIT_VALIDATED",
            "observed_at": as_of.isoformat(),
            "reference": f"fixture:{component}",
        }
        for component in ("indices", "breadth", "sectors", "concepts")
    }
    return {
        "schema_version": "pallas-009-market-context-v1",
        "context_id": "market-context:fixture-review",
        "market_review_id": "fixture-review",
        "source_task_id": "fixture-review",
        "market": "cn",
        "trade_date": as_of.date().isoformat(),
        "as_of": as_of.isoformat(),
        "decision_as_of": as_of.isoformat(),
        "source_completeness": {
            "requested": ["indices", "breadth", "sectors", "concepts"],
            "available": ["indices", "breadth", "sectors", "concepts"],
            "missing": [],
            "failed": [],
            "status": quality,
        },
        "component_timing_status": "PIT_VALIDATED",
        "component_provenance": provenance,
        "provenance": {"source_task_id": "fixture-review"},
        "narrative": {
            "status": "FAILED_CLOSED_STRUCTURED_CONTEXT_USABLE",
            "machine_authority": "STRUCTURED_MARKET_DATA",
        },
    }


class _ScreeningDB:
    def __init__(self, *, mode: str):
        self.mode = mode

    def list_screening_runs(self, **_kwargs):
        if self.mode == "unavailable":
            raise OSError("fixture screening DB unavailable")
        if self.mode == "missing":
            return []
        return [{"run_id": "screen-run-fixture", "strategy": "capital_heat", "market": "cn"}]

    def get_screening_run(self, _run_id):
        completed_date = NOW.date()
        decision_cutoff = NOW
        completion_status = "CLOSE_CONFIRMED"
        producer_status = "COMPLETED"
        source_errors = []
        if self.mode == "stale":
            completed_date = (NOW - timedelta(days=4)).date()
            decision_cutoff = NOW - timedelta(days=4)
        elif self.mode == "failed":
            completion_status = "FAILED"
            producer_status = "FAILED"
        elif self.mode == "quality":
            source_errors = ["fixture source failed"]
        if self.mode == "zero":
            candidates = []
        else:
            candidates = [{
                "code": "600519",
                "name": "贵州茅台",
                "rank": 1,
                "screen_score": 88.0,
                "score": 88.0,
                "latest_completed_trade_date": completed_date.isoformat(),
                "decision_cutoff": decision_cutoff.isoformat(),
                "completion_status": completion_status,
                "completion_basis": "fixture_close_confirmed",
                "quantitative_input_reference": "fixture:screening:close",
            }]
        detail = {
            "run_id": "screen-run-fixture",
            "strategy": "capital_heat",
            "market": "cn",
            "created_at": (NOW - timedelta(minutes=1)).isoformat(),
            "status": producer_status,
            "result": {
                "candidates": candidates,
                "candidate_count": len(candidates),
                "strategy": "capital_heat",
                "market": "cn",
                "latest_completed_trade_date": completed_date.isoformat(),
                "decision_cutoff": decision_cutoff.isoformat(),
                "completion_status": completion_status,
                "completion_basis": "fixture_close_confirmed",
                "quantitative_input_reference": "fixture:screening:close",
                "source_errors": source_errors,
                "warnings": [],
                "degradation": [],
            },
        }
        if self.mode == "failed":
            detail["result"]["status"] = "FAILED"
        return detail


def _snapshot():
    from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot

    return PortfolioSnapshot.build(
        snapshot_id="snapshot:fixture",
        trace_id="trace:fixture",
        created_at=NOW,
        producer="ATHENA_GOLDEN_PATH_FIXTURE",
        account_id="athena-sim",
        broker="FIXTURE_WORKER",
        account_mode="SIMULATION",
        as_of=NOW,
        revision=1,
        currency="CNY",
        equity=Decimal("1000000.00"),
        cash=Decimal("1000000.00"),
        available_cash=Decimal("1000000.00"),
        reserved_cash=Decimal("0.00"),
        positions=(),
        active_orders=(),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        reconciliation_status="RECONCILED",
        data_quality="HIGH",
        limitations=(),
        broker_snapshot_ref="fixture:portfolio",
    )


def _trigger(*, symbol: str, source: str, screening_run_id: str | None = None):
    from src.investment.contracts.research_trigger import ResearchTrigger

    return ResearchTrigger.build(
        research_trigger_id=f"trigger:fixture:{symbol}:{source.lower()}",
        trigger_type=("SCHEDULED_SCREENING" if source == "SCREENING" else "SCHEDULED_HOLDING_REVIEW"),
        trigger_source="pallas-system-reassembly-harness",
        symbol=symbol,
        market="CN",
        priority=50,
        created_at=NOW,
        effective_at=NOW,
        scheduled_for=NOW,
        dedup_key=f"fixture:{symbol}:{source}",
        policy_version="pallas-004-research-trigger-v1",
        evidence_refs=("fixture:market-context", "fixture:portfolio"),
        screening_run_id=screening_run_id,
    )


class _Coordinator:
    def __init__(self, *, mode: str):
        self.mode = mode
        self.successes: list[dict[str, object]] = []

    def plan(self, *, screening_candidates, **_kwargs):
        if self.mode == "zero":
            return []
        if self.mode == "holdings_only":
            trigger = _trigger(symbol="600519", source="HOLDING")
            return [{"symbol": "600519", "source": "HOLDING", "research_trigger": trigger.model_dump(mode="json")}]
        if not screening_candidates:
            return []
        candidate = dict(screening_candidates[0])
        trigger = _trigger(
            symbol=str(candidate["symbol"]),
            source="SCREENING",
            screening_run_id=str(candidate["screening_run_id"]),
        )
        candidate["research_trigger"] = trigger.model_dump(mode="json")
        return [candidate]

    def mark_success(self, **kwargs):
        self.successes.append(dict(kwargs))

    def mark_failure(self, **_kwargs):
        return None

    def mark_deferred_budget(self, **_kwargs):
        return None


class _Runner:
    def complete(self, *, cycle_id, symbol, current_time, **_kwargs):
        from src.analyzer import AnalysisResult
        from src.investment.m2.orchestration import AnalysisCompletion

        result = AnalysisResult(
            code=symbol,
            name="贵州茅台",
            sentiment_score=76,
            trend_prediction="中期上行趋势",
            operation_advice="买入",
            decision_type="buy",
            confidence_level="高",
            action="buy",
            technical_analysis="fixture technical",
            fundamental_analysis="fixture fundamental",
            analysis_summary="fixture completed Luna Max research",
            risk_warning="fixture risk",
            model_used="gpt-5.6-luna",
            dashboard={"battle_plan": {"sniper_points": {
                "ideal_buy": 95,
                "secondary_buy": 100,
                "stop_loss": 80,
                "take_profit": 130,
            }}},
        )
        return AnalysisCompletion(
            result=result,
            context_snapshot={"source": "fixture:DSAAnalysisCompletionRunner"},
            source_report_id=42,
            recovered=False,
            completed_at=current_time,
        )


class _FailingRunner:
    def complete(self, **_kwargs):
        raise TimeoutError("fixture Luna research timeout")


class _Publisher:
    def __init__(self):
        self.proposals = []

    def publish(self, proposal):
        from src.investment.proposal.transport import AthenaProposalAcknowledgement

        self.proposals.append(proposal)
        return AthenaProposalAcknowledgement(
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.content_hash,
            acknowledgement_id=f"ack:{proposal.content_hash[:24]}",
            acknowledgement_state="ACCEPTED",
            lifecycle_state="ACCEPTED",
            deduplicated=False,
        )


def _run_cycle(
    mode: str,
    context: dict[str, object],
    *,
    runner=None,
    run_at: datetime = NOW,
):
    from src.investment.m2.screening_candidates import DatabaseScreeningCandidateSource
    from src.investment.proposal.orchestration import ProposalHandoffLoopService

    config = SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_m2_interval_minutes=60,
        single_brain_m2_cycle_guard_seconds=0,
        generation_backend_timeout_seconds=1,
        single_brain_m2_snapshot_timeout_seconds=1,
        single_brain_proposal_timeout_seconds=1,
        single_brain_m2_max_symbols=1,
        single_brain_m2_holdings_limit=0,
        single_brain_m2_symbols=[],
        single_brain_m2_screening_max_candidates=3,
        single_brain_m2_screening_max_age_hours=72,
        single_brain_m2_screening_strategy="capital_heat",
        single_brain_m2_screening_market="cn",
        single_brain_m2_readiness_gate_enabled=False,
    )
    source = DatabaseScreeningCandidateSource(_ScreeningDB(mode="zero" if mode == "zero" else "unavailable" if mode == "holdings_only" else "valid"))
    publisher = _Publisher()
    service = ProposalHandoffLoopService(
        config=config,
        analysis_runner=runner or _Runner(),
        publisher=publisher,
        snapshot_source=SimpleNamespace(capture_snapshot=_snapshot),
        screening_candidate_source=source,
        trigger_coordinator=_Coordinator(mode=mode),
        clock=lambda: run_at,
    )
    result = service.run_cycle(
        scheduled_for=run_at,
        started_at=run_at,
        market_review_context=context,
        lock_acquired_at=run_at,
        require_market_review_context=True,
    )
    return result, publisher


def _context_fault_matrix() -> dict[str, dict[str, object]]:
    from src.market_review_contract import validate_market_context_for_slot

    cases = {
        "fresh_complete": _context(),
        "stale": _context(as_of=NOW - timedelta(hours=2)),
        "future_dated": _context(as_of=NOW + timedelta(hours=1)),
        "degraded_structural": _context(quality="degraded"),
        "missing_structural": {
            **_context(),
            "source_completeness": {
                "requested": ["indices", "breadth", "sectors", "concepts"],
                "available": ["indices", "breadth", "concepts"],
                "missing": ["sectors"],
                "failed": [],
                "status": "degraded",
            },
        },
        "invalid_pit": {
            **_context(),
            "component_timing_status": "PIT_PARTIAL",
        },
        "persistence_failed": {
            **_context(),
            "persistence_status": "PERSISTENCE_FAILED",
        },
        "identity_conflict": {
            **_context(),
            "market_review_id": "fixture-review-other",
        },
    }
    matrix: dict[str, dict[str, object]] = {}
    for name, value in cases.items():
        valid, reason = validate_market_context_for_slot(
            value,
            trade_date=NOW.date(),
            as_of=NOW,
            max_age_seconds=3600,
        )
        matrix[name] = {"valid": valid, "reason": reason}
    return matrix


def _narrative_failure_probe() -> dict[str, object]:
    """Exercise the real structured-only MarketAnalyzer fallback locally."""

    from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview

    analyzer = MarketAnalyzer(
        search_service=None,
        analyzer=None,
        region="cn",
        config=SimpleNamespace(report_language="en", market_review_color_scheme="green_up"),
    )
    overview = MarketOverview(
        date=NOW.date().isoformat(),
        indices=[MarketIndex(code="sh000001", name="SSE Composite", current=3000.0, change_pct=0.5)],
        up_count=2000,
        down_count=1000,
        flat_count=500,
        limit_up_count=40,
        limit_down_count=10,
        total_amount=9000.0,
        top_sectors=[{"name": "Fixture Leaders"}],
        bottom_sectors=[{"name": "Fixture Laggards"}],
        top_concepts=[{"name": "Fixture Theme"}],
        bottom_concepts=[{"name": "Fixture Risk"}],
        indices_data_status="available",
        breadth_data_status="available",
        sector_data_status="available",
        concept_data_status="available",
    )
    analyzer.get_market_overview = lambda: overview
    analyzer.search_market_news = lambda: []
    result = analyzer.run_structured_market_review_with_snapshot(narrative_reason="LUNA_TIMEOUT")
    payload = result.structured_payload
    narrative = payload.get("narrative") or {}
    return {
        "status": narrative.get("status"),
        "machine_authority": narrative.get("machine_authority"),
        "structured_quality": (payload.get("data_quality") or {}).get("status"),
        "machine_context_usable": (
            narrative.get("status") == "FAILED_CLOSED_STRUCTURED_CONTEXT_USABLE"
            and narrative.get("machine_authority") == "STRUCTURED_MARKET_DATA"
            and (payload.get("data_quality") or {}).get("status") == "complete"
        ),
    }


def _screening_fault_matrix() -> dict[str, dict[str, object]]:
    from src.investment.m2.screening_candidates import DatabaseScreeningCandidateSource

    cases = {
        "missing": "missing",
        "stale": "stale",
        "failed": "failed",
        "quality_failed": "quality",
    }
    matrix: dict[str, dict[str, object]] = {}
    for name, mode in cases.items():
        result = DatabaseScreeningCandidateSource(_ScreeningDB(mode=mode)).latest_result(
            max_candidates=3,
            max_age=timedelta(hours=72),
            now=NOW,
            strategy="capital_heat",
            market="cn",
        )
        matrix[name] = {"status": result.status, "reason": result.reason}
    return matrix


def _research_failure_probe() -> dict[str, object]:
    run_at = NOW + timedelta(hours=1)
    result, publisher = _run_cycle(
        "valid",
        _context(as_of=run_at),
        runner=_FailingRunner(),
        run_at=run_at,
    )
    return {
        "status": result.status,
        "candidate_outcome_status": [item.get("status") for item in result.candidate_outcomes],
        "proposal_count": len(publisher.proposals),
        "retryable_by_later_natural_work": result.status == "FAILED_CLOSED" and not publisher.proposals,
    }


def _proposal_transport_fault_probe(proposal) -> dict[str, object]:
    from src.investment.proposal.transport import (
        CanonicalHttpInvestmentProposalPublisher,
        ProposalTransportUncertain,
    )

    class _UnavailableOpener:
        def __init__(self):
            self.methods: list[str] = []

        def __call__(self, request, **_kwargs):
            self.methods.append(request.get_method())
            raise OSError("fixture Athena endpoint unavailable")

    opener = _UnavailableOpener()
    publisher = CanonicalHttpInvestmentProposalPublisher(
        url="http://127.0.0.1:8088/api/investment-proposals",
        timeout_seconds=1,
        opener=opener,
    )
    try:
        publisher.publish(proposal)
    except ProposalTransportUncertain as exc:
        return {
            "status": "PENDING_RECONCILIATION",
            "reason": str(exc),
            "methods": opener.methods,
            "post_attempts": opener.methods.count("POST"),
            "blind_retry_forbidden": opener.methods.count("POST") == 1,
        }
    return {
        "status": "FAILED_OPEN",
        "reason": "fixture transport unexpectedly acknowledged",
        "methods": opener.methods,
        "post_attempts": opener.methods.count("POST"),
        "blind_retry_forbidden": False,
    }


def _calendar_fault_probe() -> dict[str, object]:
    from src.investment.m2.natural_admission import evaluate_natural_cycle_admission

    admission = evaluate_natural_cycle_admission(datetime(2026, 8, 25, 2, 0))
    return {"allowed": admission.allowed, "reason": admission.reason_code}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("success", "zero", "holdings_only"), default="success")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pallas-dsa-harness-") as directory:
        os.environ["DATABASE_PATH"] = str(Path(directory) / "dsa-fixture.db")
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        try:
            context = _context()
            if args.scenario == "holdings_only":
                context = _context()
            result, publisher = _run_cycle(args.scenario, context)
            valid, valid_reason = __import__("src.market_review_contract", fromlist=["validate_market_context_for_slot"]).validate_market_context_for_slot(
                context,
                trade_date=NOW.date(),
                as_of=NOW,
                max_age_seconds=3600,
            )
            payload = {
                "repo": "DSA",
                "scenario": args.scenario,
                "status": result.status,
                "cycle_id": result.cycle_id,
                "candidate_discovery_status": result.candidate_discovery_status,
                "candidate_discovery_reason": result.candidate_discovery_reason,
                "market_context_admission": result.market_context_admission,
                "context_contract": {"valid": valid, "reason": valid_reason},
                "context_fault_matrix": _context_fault_matrix(),
                "narrative_failure": _narrative_failure_probe(),
                "screening_fault_matrix": _screening_fault_matrix(),
                "research_failure": _research_failure_probe(),
                "proposal_transport_fault": (
                    _proposal_transport_fault_probe(publisher.proposals[0])
                    if publisher.proposals
                    else {"status": "NOT_ENTERED", "reason": "no proposal in scenario"}
                ),
                "calendar_fault": _calendar_fault_probe(),
                "research_trigger_ids": list(result.research_trigger_ids),
                "candidate_outcomes": list(result.candidate_outcomes),
                "proposal_ids": list(result.proposal_ids),
                "acknowledgement_ids": [item.acknowledgement_id for item in result.acknowledgements],
                "proposals": [json.loads(item.canonical_json()) for item in publisher.proposals],
                "no_action_outcome": result.no_action_outcome,
                "runtime_contract": {
                    "model": "gpt-5.6-luna",
                    "reasoning_effort": "max",
                    "fallback_used": False,
                    "invocation": "DETERMINISTIC_STUB_ONLY",
                },
                "safety": {"simulation_only": True, "LIVE_TRADING": False, "real_provider": False, "real_luna": False, "real_worker": False},
            }
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
            return 0
        finally:
            DatabaseManager.reset_instance()


if __name__ == "__main__":
    raise SystemExit(main())
