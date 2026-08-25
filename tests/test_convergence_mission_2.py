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
from src.services.dependency_health import evaluate_dsa_research_admission
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


def test_dsa_readiness_uses_only_owned_facts_and_never_heals_absence(tmp_path, monkeypatch):
    store = DependencyHealthStore(tmp_path / "health.json")
    store.record_result("news", category="NEWS_SEARCH", success=False, reachable=False)
    store.record_result(
        "market-context", category="MARKET_CONTEXT", success=True, reachable=True,
        usable=True, records=1, data_timestamp=NOW.isoformat(), max_age_seconds=1,
    )
    monkeypatch.setattr(
        "src.services.dependency_health._now", lambda: NOW + timedelta(seconds=2)
    )
    snapshot = store.snapshot()
    assert snapshot["readiness"]["DSA_RESEARCH_READINESS"] == "BLOCKED"
    assert "AUTONOMOUS_SIMULATION_READINESS" not in snapshot["readiness"]
    assert set(snapshot["readiness"]["blocked_categories"]) == {
        "LLM_RESEARCH", "RESEARCH_MARKET_DATA", "MARKET_CONTEXT"
    }
    assert "ATHENA_AUTHORITY" not in snapshot["readiness"]["blocked_categories"]
    assert snapshot["categories"]["MARKET_CONTEXT"]["status"] == "STALE"
    assert snapshot["categories"]["MARKET_CONTEXT"]["source_event_at"] == NOW.isoformat()
    assert snapshot["categories"]["MARKET_CONTEXT"]["fresh_until"] is not None
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


def test_unknown_calendar_persists_durable_blocked_before_lock(isolated_db, monkeypatch):
    config = SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_m2_interval_minutes=60,
        single_brain_m2_run_immediately=False,
        single_brain_execution_mode="PROPOSAL_HANDOFF",
        single_brain_m2_natural_session_gate_enabled=True,
    )
    monkeypatch.setattr(
        "src.investment.m2.natural_admission.evaluate_natural_cycle_admission",
        lambda *_args: SimpleNamespace(
            allowed=False,
            reason_code="TRADING_CALENDAR_UNAVAILABLE",
            market_phase="UNKNOWN",
        ),
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
    assert projection["last_terminal_status"] == "BLOCKED"
    assert projection["last_terminal_reason"]["code"] == "TRADING_CALENDAR_UNAVAILABLE"
    stages = repository.stage_events(projection["last_terminal_cycle_id"])
    assert ("LOCK", "NOT_ENTERED") in {
        (item["stage"], item["state"]) for item in stages
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


def test_target_budget_contract_is_admissible_and_unsafe_config_fails_closed(isolated_db):
    target = SimpleNamespace(
        single_brain_m2_interval_minutes=10,
        single_brain_m2_cycle_guard_seconds=120,
        generation_backend_timeout_seconds=300,
        single_brain_m2_snapshot_timeout_seconds=5,
        single_brain_proposal_timeout_seconds=5,
    )
    budget = build_cycle_budget(started_at=NOW, config=target)
    assert budget.interval_seconds == 600
    assert budget.guard_seconds == 120
    assert budget.usable_cycle_budget_seconds == 480
    assert budget.candidate_reserve_seconds == 310
    assert budget.configuration_admissible

    unsafe = SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_m2_interval_minutes=10,
        single_brain_m2_cycle_guard_seconds=300,
        generation_backend_timeout_seconds=300,
        single_brain_m2_snapshot_timeout_seconds=5,
        single_brain_proposal_timeout_seconds=5,
        single_brain_m2_readiness_gate_enabled=False,
    )
    unsafe_budget = build_cycle_budget(started_at=NOW, config=unsafe)
    assert unsafe_budget.usable_cycle_budget_seconds == 300
    assert not unsafe_budget.configuration_admissible

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
    ).run_cycle(scheduled_for=NOW, lock_acquired_at=NOW)
    assert result.status == "FAILED_CLOSED"
    assert "configuration is inadmissible" in result.blocked_reasons[0]
    assert result.canonical_cycle["status"] == "BLOCKED"
    assert result.canonical_cycle["terminal_reason_code"] == "REQUIRED_DEPENDENCY_BLOCKED"
    assert calls == {"snapshot": 0, "research": 0}


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


def _admission_snapshot(*, llm_status="STALE", market_status="STALE", model="gpt-5.6-luna"):
    return {
        "dependencies": {
            "codex-luna": {
                "dependency_id": "codex-luna",
                "category": "LLM_RESEARCH",
                "configured": True,
                "enabled": True,
                "status": llm_status,
                "identity_status": "HEALTHY",
                "generation_status": llm_status,
                "metadata": {"model": model, "provider": "codex_chatgpt_oauth"},
            },
            "sina": {
                "dependency_id": "sina",
                "category": "RESEARCH_MARKET_DATA",
                "configured": True,
                "enabled": True,
                "status": market_status,
            },
        },
        "categories": {
            "LLM_RESEARCH": {"status": llm_status},
            "RESEARCH_MARKET_DATA": {"status": market_status},
            "MARKET_CONTEXT": {"status": "HEALTHY"},
        },
        "readiness": {"DSA_RESEARCH_READINESS": "BLOCKED"},
    }


def test_expired_health_allows_one_natural_research_attempt(isolated_db, monkeypatch):
    class FakeStore:
        def record_result(self, *_args, **_kwargs):
            return None

        def snapshot(self):
            return _admission_snapshot()

    monkeypatch.setattr("src.services.dependency_health.get_dependency_health_store", lambda: FakeStore())
    calls = {"snapshot": 0, "generation": 0}
    runner = SimpleNamespace(
        complete=lambda **_kwargs: (
            calls.__setitem__("generation", calls["generation"] + 1)
            or SimpleNamespace(
                completed_at=NOW,
                result=object(),
                context_snapshot={},
                source_report_id=101,
            )
        )
    )
    monkeypatch.setattr(
        "src.investment.proposal.orchestration.InvestmentProposalBuilder.build",
        lambda _self, **kwargs: SimpleNamespace(
            proposal=SimpleNamespace(
                proposal_id="proposal-expired-health",
                content_hash="a" * 64,
            ),
            research_bundle=SimpleNamespace(research_id="research-expired-health"),
        ),
    )
    config = SimpleNamespace(
        single_brain_m2_enabled=True, single_brain_m2_interval_minutes=60,
        single_brain_m2_cycle_guard_seconds=300, generation_backend_timeout_seconds=300,
        single_brain_m2_snapshot_timeout_seconds=5, single_brain_proposal_timeout_seconds=5,
        single_brain_m2_readiness_gate_enabled=True,
    )
    service = ProposalHandoffLoopService(
        config=config,
        analysis_runner=runner,
        publisher=SimpleNamespace(publish=lambda proposal: AthenaProposalAcknowledgement(
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.content_hash,
            acknowledgement_id="ack-expired-health",
            acknowledgement_state="ACCEPTED",
            lifecycle_state="NO_ACTION",
            deduplicated=False,
        )),
        snapshot_source=SimpleNamespace(
            capture_snapshot=lambda: calls.__setitem__("snapshot", calls["snapshot"] + 1) or object()
        ),
        trigger_coordinator=SimpleNamespace(
            plan=lambda **_kwargs: [{
                "symbol": "000001",
                "source": "HOLDING",
                "research_trigger": {"research_trigger_id": "trigger-expired-health"},
            }],
            mark_success=lambda **_kwargs: None,
        ),
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
    assert result.status == "COMPLETED"
    assert calls == {"snapshot": 1, "generation": 1}


@pytest.mark.parametrize("status", ["STALE", "FAILED", "UNKNOWN"])
def test_transient_research_health_is_admitted_for_next_natural_cycle(status):
    admission = evaluate_dsa_research_admission(
        _admission_snapshot(llm_status=status, market_status=status)
    )
    assert admission["can_attempt"] is True
    assert admission["status"] == "ADMITTED"


def test_model_provider_identity_mismatch_still_blocks_natural_admission():
    snapshot = _admission_snapshot(model="wrong-model")
    admission = evaluate_dsa_research_admission(snapshot)
    assert admission["can_attempt"] is False
    assert "LLM_RESEARCH_MODEL_MISMATCH" in admission["blocked_reasons"]


def test_stale_research_market_data_does_not_create_refresh_deadlock():
    snapshot = _admission_snapshot(llm_status="HEALTHY", market_status="STALE")
    admission = evaluate_dsa_research_admission(snapshot)
    assert admission["can_attempt"] is True
    assert "RESEARCH_MARKET_DATA_OBSERVED:STALE" in admission["advisories"]


def test_missing_research_market_provider_remains_blocked():
    snapshot = _admission_snapshot(llm_status="HEALTHY", market_status="UNKNOWN")
    snapshot["dependencies"].pop("sina")
    snapshot["dependencies"]["tushare"] = {
        "category": "RESEARCH_MARKET_DATA",
        "configured": False,
        "enabled": False,
        "status": "DISABLED",
    }
    admission = evaluate_dsa_research_admission(snapshot)
    assert admission["can_attempt"] is False
    assert "RESEARCH_MARKET_DATA_PROVIDER_NOT_CONFIGURED" in admission["blocked_reasons"]
