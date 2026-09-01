from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.analyzer import AnalysisResult
from src.config import Config
from src.investment.canonical_cycle import CanonicalCycleRepository
from src.investment.proposal import orchestration as orchestration_module
from src.investment.proposal.orchestration import ProposalHandoffLoopService
from src.market_review_contract import (
    build_market_context,
    validate_market_context_for_slot,
)
from src.repositories.market_review_linkage_repo import MarketReviewLinkageRepository
from src.storage import DatabaseManager


UTC = timezone.utc
NOW = datetime(2026, 8, 25, 2, 0, tzinfo=UTC)


def _canonical_context(
    *,
    source_task_id: str,
    as_of: datetime,
    component_observed_at: dict[str, datetime] | None = None,
) -> dict[str, object]:
    iso = as_of.astimezone(UTC).isoformat()
    component_provenance = {
        component: {
            "observed_at": (
                (component_observed_at or {}).get(component, as_of)
                .astimezone(UTC)
                .isoformat()
            ),
            "reference": f"fixture:{component}",
        }
        for component in ("indices", "breadth", "sectors", "concepts")
    }
    payload = {
        "kind": "market_review",
        "region": "cn",
        "date": as_of.astimezone(UTC).date().isoformat(),
        "generated_at": iso,
        "summary": "deterministic scheduler-owned market review",
        "indices": [{"change_pct": 0.5}],
        "breadth": {
            "up_count": 60,
            "down_count": 30,
            "flat_count": 10,
            "limit_up_count": 6,
            "limit_down_count": 1,
        },
        "sectors": {"top": [], "bottom": []},
        "concepts": {"top": [], "bottom": [], "data_status": "available_empty"},
        "data_quality": {
            "indices": "available",
            "breadth": "available",
            "sectors": "available",
            "concepts": "available_empty",
        },
        "component_provenance": component_provenance,
        "news": [],
    }
    return build_market_context(
        payload,
        task_id=source_task_id,
        market_review_id=source_task_id,
        as_of=as_of,
    )


def _persist_market_review(db, *, query_id: str, context: dict[str, object]) -> None:
    payload = {
        "kind": "market_review",
        "region": "cn",
        "date": context["trade_date"],
        "generated_at": context["as_of"],
        "summary": "deterministic scheduler-owned market review",
        "market_context": context,
    }
    db.save_analysis_history(
        result=AnalysisResult(
            code="MARKET",
            name="Fixture Market Review",
            sentiment_score=50,
            trend_prediction="fixture",
            operation_advice="fixture",
            analysis_summary="deterministic scheduler-owned market review",
        ),
        query_id=query_id,
        report_type="market_review",
        news_content="fixture",
        context_snapshot={
            "market_review_region": "cn",
            "market_review_payload": payload,
        },
        save_snapshot=True,
    )


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_execution_mode="PROPOSAL_HANDOFF",
        single_brain_simulation_execution_authorized=False,
        single_brain_proposal_url="http://fixture.invalid/athena",
        single_brain_m2_snapshot_url="http://fixture.invalid/snapshot",
        single_brain_m2_screening_enabled=False,
        single_brain_m2_interval_minutes=10,
        single_brain_m2_cycle_guard_seconds=120,
        generation_backend_timeout_seconds=300,
        single_brain_m2_snapshot_timeout_seconds=5,
        single_brain_proposal_timeout_seconds=5,
        single_brain_m2_readiness_gate_enabled=False,
        market_review_region="cn",
        report_language="zh",
    )


def _patch_scheduler_owned_runtime(
    monkeypatch,
    *,
    db,
    mode,
    generated,
    live_context_factory=None,
):
    def fake_run_market_review(**kwargs):
        if mode == "generation":
            raise RuntimeError("fixture market review generation failure")

        source_task_id = str(kwargs["query_id"])
        if live_context_factory is not None and kwargs.get("context_as_of") is None:
            context = live_context_factory(source_task_id, kwargs)
        else:
            as_of = kwargs.get("context_as_of") or NOW
            if mode == "pit":
                as_of = as_of + timedelta(hours=1)
            context = _canonical_context(source_task_id=source_task_id, as_of=as_of)
        generated.append(context)
        if mode == "persistence":
            return SimpleNamespace(
                market_review_payload={"market_context": context},
                report="fixture",
                persistence_status="PERSISTENCE_FAILED",
            )
        _persist_market_review(db, query_id=source_task_id, context=context)
        return SimpleNamespace(
            market_review_payload={
                "kind": "market_review",
                "region": "cn",
                "date": context["trade_date"],
                "generated_at": context["as_of"],
                "summary": "deterministic scheduler-owned market review",
                "market_context": context,
            },
            report="fixture",
            persistence_status="PERSISTED",
        )

    class EmptyCoordinator:
        def __init__(self, *_args, **_kwargs):
            pass

        def plan(self, **_kwargs):
            return []

    monkeypatch.setattr(
        "src.core.market_review_runtime.build_market_review_runtime",
        lambda _config: (SimpleNamespace(), None, None),
    )
    monkeypatch.setattr(
        "src.services.daily_market_context.run_market_review",
        fake_run_market_review,
    )
    monkeypatch.setattr(
        "src.services.daily_market_context.try_acquire_market_review_lock",
        lambda _config: object(),
    )
    monkeypatch.setattr(
        "src.services.daily_market_context.release_market_review_lock",
        lambda _token: None,
    )
    monkeypatch.setattr(
        orchestration_module,
        "DSAAnalysisCompletionRunner",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        orchestration_module,
        "CanonicalHttpInvestmentProposalPublisher",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        orchestration_module,
        "CanonicalHttpPortfolioSnapshotSource",
        lambda **_kwargs: SimpleNamespace(capture_snapshot=lambda: object()),
    )
    monkeypatch.setattr(orchestration_module, "ResearchTriggerCoordinator", EmptyCoordinator)


@pytest.mark.parametrize("evidence_case", ["post_call", "late"])
def test_scheduler_owned_live_market_context_uses_post_call_admission_cutoff_and_preserves_fixed_pit(
    isolated_db,
    monkeypatch,
    evidence_case,
):
    cycle_start = datetime(2026, 8, 25, 5, 0, 0, tzinfo=UTC)  # 13:00:00 BJT
    clock = {"now": cycle_start}
    timing: list[dict[str, datetime]] = []
    generated: list[dict[str, object]] = []

    def live_context_factory(source_task_id, kwargs):
        assert kwargs.get("context_as_of") is None
        callback_start = clock["now"]
        finalization = callback_start + timedelta(seconds=5)
        offsets = (2, 3, 4, 5) if evidence_case == "post_call" else (2, 3, 4, 7)
        observations = {
            component: callback_start + timedelta(seconds=offset)
            for component, offset in zip(
                ("indices", "breadth", "sectors", "concepts"),
                offsets,
            )
        }
        clock["now"] = callback_start + timedelta(seconds=6)
        timing.append({
            "callback_start": callback_start,
            "finalization": finalization,
            "admission": clock["now"],
            "last_provider_observation": max(observations.values()),
        })
        return _canonical_context(
            source_task_id=source_task_id,
            as_of=finalization,
            component_observed_at=observations,
        )

    _patch_scheduler_owned_runtime(
        monkeypatch,
        db=isolated_db,
        mode="success",
        generated=generated,
        live_context_factory=live_context_factory,
    )

    service = ProposalHandoffLoopService.from_config(_config())
    service._clock = lambda: clock["now"]
    result = service.run_cycle(
        scheduled_for=cycle_start,
        started_at=cycle_start,
        lock_acquired_at=cycle_start,
        require_market_review_context=True,
    )

    assert timing[0]["callback_start"] == cycle_start
    assert timing[0]["callback_start"].astimezone(
        timezone(timedelta(hours=8))
    ).strftime("%H:%M:%S") == "13:00:00"
    assert timing[0]["finalization"] < timing[0]["admission"]
    assert timing[0]["last_provider_observation"] == (
        timing[0]["finalization"]
        if evidence_case == "post_call"
        else timing[0]["admission"] + timedelta(seconds=1)
    )
    assert generated[0]["decision_as_of"] == timing[0]["finalization"].isoformat().replace(
        "+00:00",
        "Z",
    )

    fixed_cutoff_context = _canonical_context(
        source_task_id="historical-fixed-cutoff",
        as_of=cycle_start,
        component_observed_at={
            component: cycle_start + timedelta(seconds=2)
            for component in ("indices", "breadth", "sectors", "concepts")
        },
    )
    valid, reason = validate_market_context_for_slot(
        fixed_cutoff_context,
        trade_date=cycle_start.date(),
        as_of=cycle_start,
        max_age_seconds=600,
    )
    assert valid is False
    assert reason in {"INVALID_PIT", "DEGRADED_STRUCTURAL"}

    if evidence_case == "post_call":
        assert result.status == "NO_ACTION"
        assert result.market_context_admission == "VALID"
        assert generated[0]["component_timing_status"] == "PIT_VALIDATED"
        assert result.no_action_outcome is not None
        assert result.no_action_outcome["durable"] is True
        stages = {
            (item["stage"], item["state"])
            for item in CanonicalCycleRepository(isolated_db).stage_events(result.cycle_id)
        }
        assert ("MARKET_REVIEW", "SUCCEEDED") in stages
        assert ("MARKET_CONTEXT", "SUCCEEDED") in stages
        assert ("RESEARCH_TRIGGER", "NO_ACTION") in stages
    else:
        assert result.status == "FAILED_CLOSED"
        assert result.market_context_admission == "DEGRADED_STRUCTURAL"
        assert generated[0]["component_timing_status"] == "PIT_PARTIAL"
        assert result.canonical_cycle["status"] == "BLOCKED"
        assert not result.proposal_ids
        assert all(
            item["state"] == "NOT_ENTERED"
            for item in CanonicalCycleRepository(isolated_db).stage_events(result.cycle_id)
            if item["stage"] == "RESEARCH_TRIGGER"
        )


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "market-context-wiring.db"))
    monkeypatch.setenv(
        "DSA_DEPENDENCY_HEALTH_PATH",
        str(tmp_path / "market-context-wiring-dependency-health.json"),
    )
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()


@pytest.mark.parametrize("initial_state", ["MISSING", "STALE"])
def test_scheduler_owned_market_context_refreshes_in_cycle_and_reaches_durable_no_action(
    isolated_db,
    monkeypatch,
    initial_state,
):
    if initial_state == "STALE":
        stale_context = _canonical_context(
            source_task_id="stale-market-review",
            as_of=NOW - timedelta(hours=2),
        )
        _persist_market_review(
            isolated_db,
            query_id="stale-market-review",
            context=stale_context,
        )

    generated: list[dict[str, object]] = []
    _patch_scheduler_owned_runtime(
        monkeypatch,
        db=isolated_db,
        mode="success",
        generated=generated,
    )
    resolve_calls = []
    original_resolve = MarketReviewLinkageRepository.resolve_market_context

    def observe_resolve(self, **kwargs):
        resolve_calls.append(kwargs)
        return original_resolve(self, **kwargs)

    monkeypatch.setattr(
        MarketReviewLinkageRepository,
        "resolve_market_context",
        observe_resolve,
    )

    service = ProposalHandoffLoopService.from_config(_config())
    service._clock = lambda: NOW
    result = service.run_cycle(
        scheduled_for=NOW,
        lock_acquired_at=NOW,
        require_market_review_context=True,
    )

    assert result.status == "NO_ACTION"
    assert result.no_action_outcome is not None
    assert result.no_action_outcome["durable"] is True
    assert len(generated) == 1
    assert len(resolve_calls) == 1
    assert result.market_review_linkage["market_context_id"] == generated[0]["context_id"]
    assert result.canonical_cycle["market_context_id"] == generated[0]["context_id"]

    stages = {
        (item["stage"], item["state"])
        for item in CanonicalCycleRepository(isolated_db).stage_events(result.cycle_id)
    }
    assert ("MARKET_REVIEW", "SUCCEEDED") in stages
    assert ("MARKET_CONTEXT", "SUCCEEDED") in stages
    assert ("RESEARCH_TRIGGER", "NO_ACTION") in stages
    assert ("INVESTMENT_PROPOSAL", "NO_ACTION") in stages
    assert ("ATHENA_HANDOFF_ACK", "NO_ACTION") in stages


def test_rules_proposal_path_does_not_block_on_missing_market_context(
    isolated_db,
):
    """Rules-first simulation can produce a durable outcome without a slow review."""

    provider_calls: list[object] = []

    class RuleRunner:
        decision_mode = "rules"

        def complete(self, **_kwargs):  # pragma: no cover - no candidates are selected
            raise AssertionError("the empty candidate path must not analyze a symbol")

    class EmptyCoordinator:
        def plan(self, **_kwargs):
            return []

    def unexpected_provider(**_kwargs):
        provider_calls.append(object())
        raise AssertionError("rules mode must not generate market review")

    service = ProposalHandoffLoopService(
        config=_config(),
        analysis_runner=RuleRunner(),
        publisher=SimpleNamespace(),
        snapshot_source=SimpleNamespace(capture_snapshot=lambda: object()),
        trigger_coordinator=EmptyCoordinator(),
        market_context_provider=unexpected_provider,
        clock=lambda: NOW,
    )

    result = service.run_cycle(
        scheduled_for=NOW,
        lock_acquired_at=NOW,
        require_market_review_context=True,
    )

    assert result.status == "NO_ACTION"
    assert result.market_context_admission == "OPTIONAL_RULES_MODE"
    assert provider_calls == []
    assert result.no_action_outcome is not None
    stages = {
        (item["stage"], item["state"], item["reason_code"])
        for item in CanonicalCycleRepository(isolated_db).stage_events(result.cycle_id)
    }
    assert ("MARKET_CONTEXT", "NOT_ENTERED", "MARKET_CONTEXT_OPTIONAL_RULES_MODE") in stages
    assert ("ATHENA_HANDOFF_ACK", "NO_ACTION", "NO_CANDIDATES") in stages


def test_rules_proposal_path_does_not_use_llm_readiness_gate(
    isolated_db,
    monkeypatch,
):
    """A valid optional context must not reintroduce the AI dependency gate."""

    monkeypatch.setattr(
        "src.services.dependency_health.evaluate_dsa_research_admission",
        lambda _snapshot: {
            "can_attempt": False,
            "blocked_reasons": ["LLM_RESEARCH:STALE"],
        },
    )

    class RuleRunner:
        decision_mode = "rules"

        def complete(self, **_kwargs):  # pragma: no cover - no candidates are selected
            raise AssertionError("the empty candidate path must not analyze a symbol")

    class EmptyCoordinator:
        def plan(self, **_kwargs):
            return []

    def unexpected_provider(**_kwargs):
        raise AssertionError("rules mode must not generate market review")

    context = {
        "source_task_id": "review",
        "market_review_id": "review",
        "context_id": "context",
        "trade_date": NOW.date().isoformat(),
        "as_of": NOW.isoformat(),
        "provenance": {"source_task_id": "review"},
    }
    service = ProposalHandoffLoopService(
        config=_config(),
        analysis_runner=RuleRunner(),
        publisher=SimpleNamespace(),
        snapshot_source=SimpleNamespace(capture_snapshot=lambda: object()),
        trigger_coordinator=EmptyCoordinator(),
        market_context_provider=unexpected_provider,
        clock=lambda: NOW,
    )

    result = service.run_cycle(
        scheduled_for=NOW,
        market_review_context=context,
        lock_acquired_at=NOW,
        require_market_review_context=True,
    )

    assert result.status == "NO_ACTION"
    assert result.market_context_admission == "LEGACY_UNVERIFIED"
    assert result.no_action_outcome is not None


@pytest.mark.parametrize("failure_mode", ["generation", "persistence", "pit"])
def test_scheduler_owned_market_context_faults_block_before_research(
    isolated_db,
    monkeypatch,
    failure_mode,
):
    generated: list[dict[str, object]] = []
    _patch_scheduler_owned_runtime(
        monkeypatch,
        db=isolated_db,
        mode=failure_mode,
        generated=generated,
    )

    service = ProposalHandoffLoopService.from_config(_config())
    service._clock = lambda: NOW
    result = service.run_cycle(
        scheduled_for=NOW,
        lock_acquired_at=NOW,
        require_market_review_context=True,
    )

    assert result.status == "FAILED_CLOSED"
    assert result.canonical_cycle["status"] == "BLOCKED"
    assert result.canonical_cycle["terminal_reason_code"] == "REQUIRED_DEPENDENCY_BLOCKED"
    assert result.no_action_outcome is None
    assert not result.proposal_ids
    assert result.canonical_cycle["market_context_id"] is None
    assert all(
        item["state"] == "NOT_ENTERED"
        for item in CanonicalCycleRepository(isolated_db).stage_events(result.cycle_id)
        if item["stage"] in {
            "RESEARCH_TRIGGER",
            "CANDIDATE_EVALUATION",
            "RESEARCH_BUNDLE",
            "INVESTMENT_PROPOSAL",
            "ATHENA_HANDOFF_ACK",
        }
    )
