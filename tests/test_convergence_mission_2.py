"""Deterministic evidence for canonical readiness and bounded natural work."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.config import Config
from src.investment.canonical_cycle import CanonicalCycleRepository
from src.investment.m2.natural_admission import (
    build_cycle_budget,
    evaluate_natural_cycle_admission,
)
from src.investment.proposal.orchestration import ProposalHandoffLoopService
from src.investment.proposal.transport import AthenaProposalAcknowledgement
from src.services.dependency_health import DependencyHealthStore
from src.services.runtime_scheduler import build_single_brain_m2_background_tasks
from src.storage import DatabaseManager


UTC = timezone.utc
NOW = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mission-2.db"))
    monkeypatch.setattr(Config, "_instance", None)
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def test_dsa_readiness_uses_only_owned_facts_and_never_heals_absence(tmp_path):
    store = DependencyHealthStore(tmp_path / "health.json")
    store.record_result("news", category="NEWS_SEARCH", success=False, reachable=False)
    snapshot = store.snapshot()
    assert snapshot["readiness"]["DSA_RESEARCH_READINESS"] == "BLOCKED"
    assert set(snapshot["readiness"]["blocked_categories"]) == {
        "LLM_RESEARCH", "RESEARCH_MARKET_DATA", "MARKET_CONTEXT"
    }
    assert "ATHENA_AUTHORITY" not in snapshot["readiness"]["blocked_categories"]
    for fact in snapshot["categories"].values():
        assert fact["owner_component"] == "DSA"
        assert {"purpose", "reason_code", "observed_at", "source_event_at", "fresh_until", "source"} <= set(fact)


def test_news_is_advisory_after_all_required_research_facts_are_healthy(tmp_path):
    store = DependencyHealthStore(tmp_path / "health.json")
    for dependency_id, category in (
        ("codex-luna", "LLM_RESEARCH"),
        ("research-market", "RESEARCH_MARKET_DATA"),
        ("market-context", "MARKET_CONTEXT"),
    ):
        if dependency_id == "codex-luna":
            store.record_result(dependency_id, category=category, success=True, reachable=True, usable=True, records=1, observation_kind="identity")
            store.record_result(dependency_id, category=category, success=True, reachable=True, usable=True, records=1, observation_kind="generation")
        else:
            store.record_result(dependency_id, category=category, success=True, reachable=True, usable=True, records=1)
    store.record_result("news", category="NEWS_SEARCH", success=False, reachable=False)
    readiness = store.snapshot()["readiness"]
    assert readiness["DSA_RESEARCH_READINESS"] == "DEGRADED"
    assert readiness["blocked_categories"] == []
    assert readiness["advisories"] == ["NEWS_SEARCH:FAILED"]


@pytest.mark.parametrize(
    ("phase", "allowed", "reason"),
    [
        ("INTRADAY", True, "LEGAL_TRADING_SESSION"),
        ("LUNCH_BREAK", False, "OUTSIDE_TRADING_SESSION"),
        ("NON_TRADING", False, "NON_TRADING_DAY"),
        ("UNKNOWN", False, "TRADING_CALENDAR_UNAVAILABLE"),
    ],
)
def test_natural_admission_is_authoritative_and_fail_closed(monkeypatch, phase, allowed, reason):
    from src.core.trading_calendar import MarketPhase

    monkeypatch.setattr(
        "src.investment.m2.natural_admission.infer_market_phase",
        lambda *_args, **_kwargs: MarketPhase(phase.lower()),
    )
    admission = evaluate_natural_cycle_admission(NOW)
    assert admission.allowed is allowed
    assert admission.reason_code == reason


def test_outside_session_scheduler_creates_zero_work_and_never_takes_lock(
    isolated_db, monkeypatch
):
    config = SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_m2_interval_minutes=60,
        single_brain_m2_run_immediately=False,
        single_brain_execution_mode="PROPOSAL_HANDOFF",
        single_brain_m2_natural_session_gate_enabled=True,
    )
    monkeypatch.setattr(
        "src.services.runtime_scheduler.evaluate_natural_cycle_admission",
        lambda *_args: SimpleNamespace(allowed=False, reason_code="OUTSIDE_TRADING_SESSION", market_phase="LUNCH_BREAK"),
        raising=False,
    )
    # Patch the imported module function used by the local import.
    monkeypatch.setattr(
        "src.investment.m2.natural_admission.evaluate_natural_cycle_admission",
        lambda *_args: SimpleNamespace(allowed=False, reason_code="OUTSIDE_TRADING_SESSION", market_phase="LUNCH_BREAK"),
    )
    monkeypatch.setattr(
        "src.services.runtime_scheduler.run_with_global_analysis_lock",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("lock must not be entered")),
    )
    task = build_single_brain_m2_background_tasks(config, config_provider=lambda: config)[0]["task"]
    task(scheduled_for=NOW, started_at=NOW)
    repository = CanonicalCycleRepository(isolated_db)
    projection = repository.scheduler_projection(
        scheduler_task_name="single_brain_proposal_handoff"
    )
    assert projection["last_terminal_status"] == "SKIPPED"
    assert projection["last_terminal_reason"]["code"] == "OUTSIDE_TRADING_SESSION"
    stages = repository.stage_events(projection["last_terminal_cycle_id"])
    assert {(item["stage"], item["state"]) for item in stages} == {
        ("SCHEDULER", "SUCCEEDED"), ("LOCK", "NOT_ENTERED")
    }


def test_budget_reserves_configured_timeouts_and_next_interval_guard():
    config = SimpleNamespace(
        single_brain_m2_interval_minutes=60,
        single_brain_m2_cycle_guard_seconds=300,
        generation_backend_timeout_seconds=300,
        single_brain_m2_snapshot_timeout_seconds=5,
        single_brain_proposal_timeout_seconds=5,
    )
    budget = build_cycle_budget(started_at=NOW, config=config)
    assert budget.deadline == NOW + timedelta(seconds=3300)
    assert budget.candidate_reserve_seconds == 310
    assert budget.admits_candidate(budget.deadline - timedelta(seconds=310))
    assert not budget.admits_candidate(budget.deadline - timedelta(seconds=309))
    delayed = build_cycle_budget(
        started_at=NOW + timedelta(minutes=58), scheduled_for=NOW, config=config
    )
    assert delayed.deadline == NOW + timedelta(seconds=3300)
    assert not delayed.admits_candidate(NOW + timedelta(minutes=58))


def test_partial_workload_defers_remaining_candidate_and_persists_deadline(isolated_db, monkeypatch):
    scopes = [
        {"symbol": "000001", "source": "HOLDING"},
        {"symbol": "600519", "source": "HOLDING"},
    ]
    coordinator = SimpleNamespace(plan=lambda **_kwargs: scopes)
    runner = SimpleNamespace(complete=lambda **kwargs: SimpleNamespace(
        completed_at=NOW, result=object(), context_snapshot={}, source_report_id=101
    ))
    monkeypatch.setattr(
        "src.investment.proposal.orchestration.InvestmentProposalBuilder.build",
        lambda _self, **kwargs: SimpleNamespace(
            proposal=SimpleNamespace(proposal_id=f"proposal-{kwargs['cycle_id']}-{len(kwargs['cycle_id'])}", content_hash="a" * 64),
            research_bundle=SimpleNamespace(research_id="research-1"),
        ),
    )
    publisher = SimpleNamespace(publish=lambda proposal: AthenaProposalAcknowledgement(
        proposal_id=proposal.proposal_id, proposal_hash=proposal.content_hash,
        acknowledgement_id="ack-1", acknowledgement_state="ACCEPTED",
        lifecycle_state="NO_ACTION", deduplicated=False,
    ))
    times = iter((NOW, NOW, NOW + timedelta(seconds=3301)))
    config = SimpleNamespace(
        single_brain_m2_enabled=True, single_brain_m2_interval_minutes=60,
        single_brain_m2_cycle_guard_seconds=300, generation_backend_timeout_seconds=300,
        single_brain_m2_snapshot_timeout_seconds=5, single_brain_proposal_timeout_seconds=5,
        single_brain_m2_readiness_gate_enabled=False,
    )
    result = ProposalHandoffLoopService(
        config=config, analysis_runner=runner, publisher=publisher,
        snapshot_source=SimpleNamespace(capture_snapshot=lambda: object()),
        trigger_coordinator=coordinator, clock=lambda: next(times),
    ).run_cycle(scheduled_for=NOW, lock_acquired_at=NOW)
    assert result.status == "PARTIAL"
    assert result.deferred_count == 1
    assert [item["status"] for item in result.candidate_outcomes] == ["SUCCEEDED", "DEFERRED_BUDGET"]
    assert result.canonical_cycle["terminal_reason_code"] == "CYCLE_BUDGET_EXHAUSTED"
    assert result.canonical_cycle["cycle_deadline"] == "2026-08-24T02:55:00Z"
    assert result.canonical_cycle["deferred_count"] == 1


def test_readiness_block_stops_before_snapshot_and_generation(isolated_db, monkeypatch):
    class FakeStore:
        def record_result(self, *_args, **_kwargs):
            return None

        def snapshot(self):
            return {"readiness": {"DSA_RESEARCH_READINESS": "BLOCKED", "reasons": ["LLM_RESEARCH:STALE"]}}

    monkeypatch.setattr("src.services.dependency_health.get_dependency_health_store", lambda: FakeStore())
    config = SimpleNamespace(
        single_brain_m2_enabled=True, single_brain_m2_interval_minutes=60,
        single_brain_m2_readiness_gate_enabled=True,
    )
    service = ProposalHandoffLoopService(
        config=config,
        analysis_runner=SimpleNamespace(complete=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("generation must not run"))),
        publisher=SimpleNamespace(),
        snapshot_source=SimpleNamespace(capture_snapshot=lambda: (_ for _ in ()).throw(AssertionError("snapshot must not run"))),
        trigger_coordinator=SimpleNamespace(plan=lambda **_kwargs: []),
        clock=lambda: NOW,
    )
    context = {
        "source_task_id": "review", "market_review_id": "review", "context_id": "context",
        "trade_date": NOW.date().isoformat(), "as_of": NOW.isoformat(), "provenance": {"source_task_id": "review"},
    }
    result = service.run_cycle(
        scheduled_for=NOW, lock_acquired_at=NOW,
        market_review_context=context, require_market_review_context=True,
    )
    assert result.status == "FAILED_CLOSED"
    assert result.canonical_cycle["status"] == "BLOCKED"
    assert "LLM_RESEARCH:STALE" in result.blocked_reasons[0]
