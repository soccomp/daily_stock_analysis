"""PALLAS-004 trigger ledger, fair holdings coverage, and real handoff evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.config import Config
from src.investment.contracts.research_trigger import ResearchTrigger
from src.investment.contracts.data_evidence import (
    DataEvidence,
    analysis_context_evidence,
    portfolio_snapshot_evidence,
)
from src.investment.m2.orchestration import AnalysisCompletion
from src.investment.m2.orchestration import M2ShadowLoopService
from src.investment.m2.repository import M2OperationalRepository
from src.investment.m2.research_trigger import (
    ResearchTriggerConflictError,
    ResearchTriggerCoordinator,
)
from src.investment.m2.telemetry import build_research_runtime_signals
from src.investment.m2.screening_candidates import (
    DatabaseScreeningCandidateSource,
    ScreeningCandidate,
)
from src.investment.proposal.orchestration import ProposalHandoffLoopService
from src.storage import DatabaseManager, ResearchTriggerLedgerRecord
from src.services.decision_scorecard_service import DecisionScorecardService
from tests.test_investment_proposal_issue_9 import _ack, _result
from tests.test_investment_shadow_wiring_p1a import _analysis_result, _policy, _snapshot
from tests.test_m2_screening_candidates import _snapshot_many
from tests.test_single_brain_m2_shadow_loop import _PolicySource, _SnapshotSource


NOW = datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc)


@pytest.fixture
def trigger_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'pallas-004.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _config(*, symbols=(), max_symbols=5, holdings_limit=10):
    return Config(
        single_brain_m2_enabled=True,
        single_brain_m2_symbols=list(symbols),
        single_brain_m2_max_symbols=max_symbols,
        single_brain_m2_holdings_limit=holdings_limit,
        single_brain_m2_interval_minutes=60,
        single_brain_m2_screening_enabled=True,
        single_brain_m2_screening_max_candidates=5,
        single_brain_m2_screening_max_age_hours=72,
    )


def test_trigger_is_immutable_and_content_addressed():
    trigger = ResearchTrigger.build(
        research_trigger_id="research-trigger-contract",
        trigger_type="SCHEDULED_SCREENING",
        trigger_source="screening-scheduler",
        symbol="300274",
        market="CN",
        priority=5,
        created_at=NOW,
        effective_at=NOW,
        scheduled_for=NOW,
        dedup_key="screening:run-1:300274",
        policy_version="pallas-004-test-v1",
        evidence_refs=("screening-run:run-1",),
        screening_scheduler_run_id="scheduler-run-1",
        screening_run_id="run-1",
    )
    assert trigger.content_hash == (
        ResearchTrigger.model_validate(trigger.model_dump()).content_hash
    )
    with pytest.raises((ValidationError, TypeError)):
        trigger.trigger_type = "MANUAL_OWNER_REVIEW"


def test_data_evidence_is_content_addressed_and_unknown_quality_is_explicit():
    evidence = analysis_context_evidence(
        context_snapshot={}, source_report_id=104, now=NOW,
    )
    assert evidence.availability_status == "UNKNOWN"
    assert evidence.freshness_status == "UNKNOWN"
    assert evidence.content_hash == DataEvidence.model_validate(
        evidence.model_dump()
    ).content_hash
    tampered = evidence.model_dump()
    tampered["availability_status"] = "AVAILABLE"
    with pytest.raises(ValidationError, match="content_hash"):
        DataEvidence.model_validate(tampered)


def test_trigger_ledger_persists_deduplication_and_blocked_outcome(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    first = coordinator.enqueue_material_event(
        symbol="600519",
        event_id="material-1",
        effective_at=NOW,
        evidence_refs=("news:material-1",),
    )
    duplicate = coordinator.enqueue_material_event(
        symbol="600519",
        event_id="material-1",
        effective_at=NOW,
        evidence_refs=("news:material-1",),
    )
    assert (first.status, first.created) == ("FIRED", True)
    assert (duplicate.status, duplicate.created) == ("DEDUPLICATED", False)
    assert len(coordinator.ledger.pending(now=NOW)) == 1
    coordinator.ledger.mark_blocked(first.trigger.research_trigger_id)
    assert coordinator.ledger.pending(now=NOW) == ()


def test_priority_places_defensive_then_material_then_holding(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    coordinator.enqueue_material_event(
        symbol="600519", event_id="material-2", effective_at=NOW,
        evidence_refs=("news:material-2",),
    )
    coordinator.enqueue_defensive_risk(
        symbol="600519", risk_event_id="risk-2", effective_at=NOW,
        evidence_refs=("risk:risk-2",),
    )
    scopes = coordinator.plan(
        config=_config(max_symbols=3),
        snapshot=_snapshot_many("600519"),
        screening_candidates=[{
            "symbol": "300274",
            "source": "SCREENING",
            "screening_run_id": "run-priority",
            "strategy": "capital_heat",
            "rank": 1,
            "screening_score": 80.0,
            "score": 81.0,
            "selected_at": NOW.isoformat(),
        }],
        cycle_id="cycle-priority",
        now=NOW,
    )
    assert [item["research_trigger"]["trigger_type"] for item in scopes] == [
        "DEFENSIVE_RISK_REVIEW", "MATERIAL_EVENT_REVIEW", "SCHEDULED_HOLDING_REVIEW",
    ]


def test_holdings_review_rotates_never_reviewed_then_oldest(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    config = _config(max_symbols=1)
    snapshot = _snapshot_many("600519", "600036")

    first = coordinator.plan(
        config=config, snapshot=snapshot, screening_candidates=[],
        cycle_id="cycle-rotation-1", now=NOW,
    )
    coordinator.mark_success(
        trigger=first[0]["research_trigger"], research_id="research-1",
        proposal_id="proposal-1", reviewed_at=NOW, interval_minutes=60,
    )
    second_time = NOW + timedelta(minutes=61)
    second = coordinator.plan(
        config=config, snapshot=snapshot, screening_candidates=[],
        cycle_id="cycle-rotation-2", now=second_time,
    )
    coordinator.mark_success(
        trigger=second[0]["research_trigger"], research_id="research-2",
        proposal_id="proposal-2", reviewed_at=second_time, interval_minutes=60,
    )
    third = coordinator.plan(
        config=config, snapshot=snapshot, screening_candidates=[],
        cycle_id="cycle-rotation-3", now=NOW + timedelta(minutes=122),
    )
    assert [item["symbol"] for item in first + second + third] == [
        "600036", "600519", "600036",
    ]
    projection = {item["symbol"]: item for item in coordinator.coverage.projection()}
    assert projection["600519"]["last_successful_review_id"] == "research-2"
    assert projection["600036"]["last_successful_review_id"] == "research-1"


def test_capacity_deferral_is_explicit_and_durable(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    scopes = coordinator.plan(
        config=_config(max_symbols=1), snapshot=_snapshot_many("600519", "600036"),
        screening_candidates=[], cycle_id="cycle-capacity", now=NOW,
    )
    assert len(scopes) == 1
    projection = {item["symbol"]: item for item in coordinator.coverage.projection()}
    assert projection["600036"]["review_status"] == "IN_PROGRESS"
    assert projection["600519"]["review_status"] == "DEFERRED_CAPACITY"
    assert projection["600519"]["deferred_count"] == 1


def test_aged_screening_trigger_breaks_holding_capacity_starvation(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    config = _config(max_symbols=3, holdings_limit=3)
    snapshot = _snapshot_many("600519", "600036", "000001")
    screening_candidate = {
        "symbol": "300274",
        "source": "SCREENING",
        "screening_run_id": "run-starvation",
        "strategy": "capital_heat",
        "rank": 1,
        "screening_score": 80.0,
        "score": 81.0,
        "selected_at": NOW.isoformat(),
    }

    initial = coordinator.plan(
        config=_config(max_symbols=4, holdings_limit=3),
        snapshot=snapshot,
        screening_candidates=[screening_candidate],
        cycle_id="cycle-starvation-initial",
        now=NOW,
    )
    assert {item["research_trigger"]["trigger_type"] for item in initial} == {
        "SCHEDULED_HOLDING_REVIEW",
        "SCHEDULED_SCREENING",
    }

    retry = coordinator.plan(
        config=config,
        snapshot=snapshot,
        screening_candidates=[screening_candidate],
        cycle_id="cycle-starvation-retry",
        now=NOW + timedelta(minutes=61),
    )
    assert retry[0]["research_trigger"]["trigger_type"] == "SCHEDULED_SCREENING"
    assert retry[0]["research_trigger"]["screening_run_id"] == "run-starvation"
    retry_types = [item["research_trigger"]["trigger_type"] for item in retry]
    assert retry_types.count("SCHEDULED_SCREENING") == 1
    assert retry_types.count("SCHEDULED_HOLDING_REVIEW") == 2


def test_multiple_overdue_screenings_reserve_holdings_and_progress_across_cycles(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    snapshot = _snapshot_many("600519", "600036", "000001")
    candidates = [
        {
            "symbol": symbol,
            "source": "SCREENING",
            "screening_run_id": f"run-fairness-{index}",
            "strategy": "capital_heat",
            "rank": index + 1,
            "screening_score": 80.0 - index,
            "score": 81.0 - index,
            "selected_at": NOW.isoformat(),
        }
        for index, symbol in enumerate(
            (
                "300274", "600362", "600111", "002241", "000426",
                "600988", "600570", "600588", "601138", "603986",
            )
        )
    ]

    initial = coordinator.plan(
        config=_config(max_symbols=13, holdings_limit=3),
        snapshot=snapshot,
        screening_candidates=candidates,
        cycle_id="cycle-fairness-initial",
        now=NOW,
    )
    assert len(initial) == 13

    retry = coordinator.plan(
        config=_config(max_symbols=3, holdings_limit=3),
        snapshot=snapshot,
        screening_candidates=candidates,
        cycle_id="cycle-fairness-retry",
        now=NOW + timedelta(minutes=61),
    )
    retry_types = [item["research_trigger"]["trigger_type"] for item in retry]
    assert retry_types.count("SCHEDULED_SCREENING") == 1
    assert retry_types.count("SCHEDULED_HOLDING_REVIEW") == 2
    first_screen = next(
        item for item in retry
        if item["research_trigger"]["trigger_type"] == "SCHEDULED_SCREENING"
    )
    coordinator.mark_success(
        trigger=first_screen["research_trigger"],
        research_id="research-screen-1",
        proposal_id="proposal-screen-1",
        reviewed_at=NOW + timedelta(minutes=61),
        interval_minutes=60,
    )

    next_retry = coordinator.plan(
        config=_config(max_symbols=3, holdings_limit=3),
        snapshot=snapshot,
        screening_candidates=[
            candidate for candidate in candidates
            if candidate["symbol"] != first_screen["symbol"]
        ],
        cycle_id="cycle-fairness-next",
        now=NOW + timedelta(minutes=122),
    )
    next_screen = next(
        item for item in next_retry
        if item["research_trigger"]["trigger_type"] == "SCHEDULED_SCREENING"
    )
    assert next_screen["symbol"] != first_screen["symbol"]
    assert [item["research_trigger"]["trigger_type"] for item in next_retry].count(
        "SCHEDULED_HOLDING_REVIEW"
    ) == 2


def test_runtime_signals_report_pending_screening_age(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    coordinator.plan(
        config=_config(max_symbols=2, holdings_limit=1),
        snapshot=_snapshot_many("600519"),
        screening_candidates=[{
            "symbol": "300274",
            "source": "SCREENING",
            "screening_run_id": "run-telemetry",
            "strategy": "capital_heat",
            "rank": 1,
            "screening_score": 80.0,
            "score": 81.0,
            "selected_at": NOW.isoformat(),
        }],
        cycle_id="cycle-telemetry",
        now=NOW,
    )
    signals = build_research_runtime_signals(
        coordinator=coordinator,
        now=NOW + timedelta(minutes=61),
    )
    assert signals["pending_screening_triggers"] == 1
    assert signals["oldest_pending_screening_age_seconds"] == 3660


def test_pending_screening_recovers_provenance_from_original_persisted_run(trigger_db):
    first_run_at = NOW - timedelta(minutes=1)
    second_run_at = NOW + timedelta(minutes=1)
    assert trigger_db.save_screening_run({
        "run_id": "run-persisted-original",
        "strategy": "capital_heat",
        "market": "cn",
        "candidate_count": 1,
        "created_at": first_run_at.isoformat(),
        "candidates": [{
            "code": "300274", "name": "阳光电源", "rank": 1,
            "screen_score": 88.5, "score": 92.1,
        }],
    }) == 1
    assert trigger_db.save_screening_run({
        "run_id": "run-persisted-newer",
        "strategy": "capital_heat",
        "market": "cn",
        "candidate_count": 1,
        "created_at": second_run_at.isoformat(),
        "candidates": [{
            "code": "600362", "name": "江西铜业", "rank": 1,
            "screen_score": 77.5, "score": 79.1,
        }],
    }) == 1
    original = {
        "symbol": "300274", "source": "SCREENING",
        "screening_run_id": "run-persisted-original",
        "strategy": "capital_heat", "rank": 1,
        "screening_score": 88.5, "score": 92.1,
        "selected_at": first_run_at.isoformat(),
    }
    newer = {
        "symbol": "600362", "source": "SCREENING",
        "screening_run_id": "run-persisted-newer",
        "strategy": "capital_heat", "rank": 1,
        "screening_score": 77.5, "score": 79.1,
        "selected_at": second_run_at.isoformat(),
    }
    source = DatabaseScreeningCandidateSource(trigger_db)
    coordinator = ResearchTriggerCoordinator(
        trigger_db,
        screening_candidate_source=source,
    )
    coordinator.plan(
        config=_config(max_symbols=1, holdings_limit=0),
        snapshot=_snapshot_many(),
        screening_candidates=[original],
        cycle_id="cycle-persisted-original",
        now=NOW,
    )
    recovered = coordinator.plan(
        config=_config(max_symbols=1, holdings_limit=0),
        snapshot=_snapshot_many(),
        screening_candidates=[newer],
        cycle_id="cycle-persisted-newer",
        now=NOW + timedelta(minutes=61),
    )[0]
    assert recovered["symbol"] == "300274"
    assert recovered["screening_run_id"] == "run-persisted-original"
    assert recovered["strategy"] == "capital_heat"
    assert recovered["rank"] == 1
    assert recovered["screening_score"] == 88.5
    assert recovered["score"] == 92.1


def test_pending_screening_without_persisted_source_is_blocked(trigger_db):
    missing = {
        "symbol": "300274", "source": "SCREENING",
        "screening_run_id": "run-not-persisted",
        "strategy": "capital_heat", "rank": 1,
        "screening_score": 80.0, "score": 81.0,
        "selected_at": NOW.isoformat(),
    }
    replacement = {
        **missing,
        "symbol": "600362",
        "screening_run_id": "run-replacement",
    }
    source = DatabaseScreeningCandidateSource(trigger_db)
    coordinator = ResearchTriggerCoordinator(
        trigger_db,
        screening_candidate_source=source,
    )
    first = coordinator.plan(
        config=_config(max_symbols=1, holdings_limit=0),
        snapshot=_snapshot_many(),
        screening_candidates=[missing],
        cycle_id="cycle-missing-source",
        now=NOW,
    )
    second = coordinator.plan(
        config=_config(max_symbols=1, holdings_limit=0),
        snapshot=_snapshot_many(),
        screening_candidates=[replacement],
        cycle_id="cycle-missing-source-retry",
        now=NOW + timedelta(minutes=61),
    )
    assert first[0]["symbol"] == "300274"
    assert second[0]["symbol"] == "600362"
    with trigger_db.get_session() as session:
        row = session.get(
            ResearchTriggerLedgerRecord,
            first[0]["research_trigger"]["research_trigger_id"],
        )
    assert row is not None
    assert row.status == "BLOCKED"


def test_holdings_exceed_configured_limit_are_covered_across_repeated_cycles(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    config = _config(max_symbols=1, holdings_limit=2)
    snapshot = _snapshot_many("600519", "600036", "000001", "300274", "601318")
    reviewed = []
    for index in range(5):
        reviewed_at = NOW + timedelta(minutes=61 * index)
        scopes = coordinator.plan(
            config=config,
            snapshot=snapshot,
            screening_candidates=[],
            cycle_id=f"cycle-all-holdings-{index}",
            now=reviewed_at,
        )
        assert len(scopes) == 1
        reviewed.append(scopes[0]["symbol"])
        coordinator.mark_success(
            trigger=scopes[0]["research_trigger"],
            research_id=f"research-all-{index}",
            proposal_id=f"proposal-all-{index}",
            reviewed_at=reviewed_at,
            interval_minutes=60,
        )
    assert set(reviewed) == {"600519", "600036", "000001", "300274", "601318"}
    assert all(item["last_successful_review_id"] for item in coordinator.coverage.projection())


def test_interrupted_holding_episode_is_reused_without_duplicate(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    config = _config(max_symbols=1, holdings_limit=1)
    first = coordinator.plan(
        config=config, snapshot=_snapshot_many("600519"), screening_candidates=[],
        cycle_id="cycle-restart-holding", now=NOW,
    )
    second = coordinator.plan(
        config=config, snapshot=_snapshot_many("600519"), screening_candidates=[],
        cycle_id="cycle-restart-holding-retry", now=NOW,
    )
    assert second[0]["research_trigger"]["research_trigger_id"] == first[0]["research_trigger"]["research_trigger_id"]
    assert len(coordinator.ledger.pending(now=NOW)) == 1


def test_interrupted_screening_episode_preserves_source_without_duplicate(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    candidate = {
        "symbol": "300274", "source": "SCREENING", "screening_run_id": "run-restart",
        "strategy": "capital_heat", "rank": 1, "screening_score": 80.0,
        "score": 81.0, "selected_at": NOW.isoformat(),
    }
    first = coordinator.plan(
        config=_config(max_symbols=1), snapshot=_snapshot_many(),
        screening_candidates=[candidate], cycle_id="cycle-restart-screening", now=NOW,
    )
    second = coordinator.plan(
        config=_config(max_symbols=1), snapshot=_snapshot_many(),
        screening_candidates=[candidate], cycle_id="cycle-restart-screening-retry", now=NOW,
    )
    assert second[0]["source"] == "SCREENING"
    assert second[0]["research_trigger"]["trigger_type"] == "SCHEDULED_SCREENING"
    assert second[0]["research_trigger"]["research_trigger_id"] == first[0]["research_trigger"]["research_trigger_id"]


def test_processed_screening_episode_replays_by_dedup_identity_without_conflict(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    candidate = {
        "symbol": "300274", "source": "SCREENING", "screening_run_id": "run-replay",
        "strategy": "capital_heat", "rank": 1, "screening_score": 80.0,
        "score": 81.0, "selected_at": NOW.isoformat(),
    }
    first = coordinator.plan(
        config=_config(max_symbols=1), snapshot=_snapshot_many(),
        screening_candidates=[candidate], cycle_id="cycle-replay-first", now=NOW,
    )
    trigger = first[0]["research_trigger"]
    coordinator.mark_success(
        trigger=trigger,
        research_id="research-replay",
        proposal_id="proposal-replay",
        reviewed_at=NOW,
        interval_minutes=60,
    )

    replay = coordinator.plan(
        config=_config(max_symbols=1), snapshot=_snapshot_many(),
        screening_candidates=[candidate],
        cycle_id="cycle-replay-later",
        now=NOW + timedelta(minutes=61),
    )

    assert replay == []
    persisted = coordinator.ledger.get_by_dedup_key("screening:run-replay:300274")
    assert persisted is not None
    assert persisted.research_trigger_id == trigger["research_trigger_id"]
    assert persisted.content_hash == trigger["content_hash"]


def test_unprocessed_screening_content_conflict_remains_fail_closed(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    candidate = {
        "symbol": "300274", "source": "SCREENING", "screening_run_id": "run-conflict",
        "strategy": "capital_heat", "rank": 1, "screening_score": 80.0,
        "score": 81.0, "selected_at": NOW.isoformat(),
    }
    first = coordinator.plan(
        config=_config(max_symbols=1), snapshot=_snapshot_many(),
        screening_candidates=[candidate], cycle_id="cycle-conflict-first", now=NOW,
    )
    original = coordinator.ledger.get_by_dedup_key("screening:run-conflict:300274")
    assert original is not None
    conflicting = ResearchTrigger.build(
        **{
            **original.model_dump(mode="python", exclude={"content_hash"}),
            "evidence_refs": ("screening-run:run-conflict", "cycle:changed", "immutable-change"),
        }
    )

    with pytest.raises(ResearchTriggerConflictError, match="dedup_key reused"):
        coordinator.ledger.enqueue(conflicting)


def test_empty_research_scope_is_a_normal_no_opportunity(trigger_db):
    class SnapshotSource:
        def capture_snapshot(self):
            return _snapshot_many()

    result = ProposalHandoffLoopService(
        config=_config(max_symbols=1),
        analysis_runner=None,
        publisher=None,
        snapshot_source=SnapshotSource(),
        trigger_coordinator=ResearchTriggerCoordinator(trigger_db),
        clock=lambda: NOW,
    ).run_cycle(scheduled_for=NOW)

    assert result.status == "NO_OPPORTUNITY"
    assert result.proposal_ids == ()
    assert result.blocked_reasons == ("no eligible research objects",)


def test_empty_scope_with_screening_source_failure_remains_failed_closed(trigger_db):
    class SnapshotSource:
        def capture_snapshot(self):
            return _snapshot_many()

    class BrokenScreeningSource:
        def latest(self, **kwargs):
            raise RuntimeError("screening database unavailable")

    result = ProposalHandoffLoopService(
        config=_config(max_symbols=1),
        analysis_runner=None,
        publisher=None,
        snapshot_source=SnapshotSource(),
        screening_candidate_source=BrokenScreeningSource(),
        trigger_coordinator=ResearchTriggerCoordinator(trigger_db),
        clock=lambda: NOW,
    ).run_cycle(scheduled_for=NOW)

    assert result.status == "FAILED_CLOSED"
    assert "screening candidate source failed" in result.blocked_reasons[0]
    assert "screening database unavailable" in result.blocked_reasons[0]


def test_interrupted_external_episode_preserves_trigger_type_without_duplicate(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    first = coordinator.enqueue_material_event(
        symbol="600519", event_id="restart-material", effective_at=NOW,
        evidence_refs=("news:restart-material",),
    )
    first_plan = coordinator.plan(
        config=_config(max_symbols=1), snapshot=_snapshot_many(),
        screening_candidates=[], cycle_id="cycle-restart-event", now=NOW,
    )
    second_plan = coordinator.plan(
        config=_config(max_symbols=1), snapshot=_snapshot_many(),
        screening_candidates=[], cycle_id="cycle-restart-event-retry", now=NOW,
    )
    assert first_plan[0]["source"] == "MATERIAL_EVENT"
    assert second_plan[0]["research_trigger"]["research_trigger_id"] == first.trigger.research_trigger_id
    assert len(coordinator.ledger.pending(now=NOW)) == 1


def test_later_material_event_supersedes_completed_morning_episode(trigger_db):
    class Runner:
        def complete(self, **kwargs):
            result = _result("hold")
            result.code = kwargs["symbol"]
            return AnalysisCompletion(result, {"data_quality": {"level": "good"}}, 106, False, kwargs.get("current_time", NOW))

    class Publisher:
        def __init__(self):
            self.proposals = []

        def publish(self, proposal):
            self.proposals.append(proposal)
            return _ack(proposal, "NO_ACTION")

    coordinator = ResearchTriggerCoordinator(trigger_db)
    publisher = Publisher()
    snapshot_source = type("SnapshotSource", (), {
        "capture_snapshot": lambda self: _snapshot_many("600519"),
    })()
    morning = ProposalHandoffLoopService(
        config=_config(max_symbols=1, holdings_limit=1), analysis_runner=Runner(),
        publisher=publisher, snapshot_source=snapshot_source,
        trigger_coordinator=coordinator, clock=lambda: NOW,
    )
    assert morning.run_cycle(scheduled_for=NOW).status == "COMPLETED"
    morning_rows = coordinator.coverage.projection()
    assert morning_rows[0]["last_successful_review_id"]
    prior_trigger = coordinator.ledger.latest_for_symbol(
        symbol="600519", effective_at=NOW,
    )
    assert prior_trigger is not None
    event_at = NOW + timedelta(minutes=61)
    event = coordinator.enqueue_material_event(
        symbol="600519", event_id="later-material", effective_at=event_at,
        evidence_refs=("news:later-material",), snapshot_id="snapshot-many",
    )
    assert event.trigger.supersedes_trigger_id == prior_trigger.research_trigger_id
    assert coordinator.ledger.get(prior_trigger.research_trigger_id) is not None
    with trigger_db.get_session() as session:
        prior_row = session.get(ResearchTriggerLedgerRecord, prior_trigger.research_trigger_id)
    assert prior_row.status == "SUPERSEDED"
    later = ProposalHandoffLoopService(
        config=_config(max_symbols=1, holdings_limit=1), analysis_runner=Runner(),
        publisher=publisher, snapshot_source=snapshot_source,
        trigger_coordinator=coordinator, clock=lambda: event_at,
    )
    assert later.run_cycle(scheduled_for=event_at).status == "COMPLETED"
    assert publisher.proposals[-1].research_trigger.supersedes_trigger_id == prior_trigger.research_trigger_id
    assert publisher.proposals[-1].supersedes_id == prior_trigger.research_trigger_id


def test_closed_holdings_remain_audit_rows_but_leave_open_metrics(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    coordinator.coverage.materialize(
        snapshot=_snapshot_many("600519", "600036"), now=NOW,
        interval_minutes=60, policy_version="test-v1",
    )
    coordinator.coverage.materialize(
        snapshot=_snapshot_many("600519"), now=NOW + timedelta(minutes=1),
        interval_minutes=60, policy_version="test-v1",
    )
    projection = {item["symbol"]: item for item in coordinator.coverage.projection()}
    assert projection["600036"]["review_status"] == "CLOSED"
    signals = build_research_runtime_signals(coordinator=coordinator, now=NOW + timedelta(minutes=1))
    assert signals["never_reviewed_holdings"] == 1
    assert signals["open_holdings_due"] == 1
    assert "600036" not in signals["fairness_order"]


def test_data_freshness_uses_time_not_quality(trigger_db):
    fresh = portfolio_snapshot_evidence(
        snapshot=_snapshot(as_of=NOW - timedelta(minutes=1)), now=NOW,
    )
    stale = portfolio_snapshot_evidence(
        snapshot=_snapshot(as_of=NOW - timedelta(minutes=6)), now=NOW,
    )
    unknown_timing = analysis_context_evidence(
        context_snapshot={"data_quality": {"level": "good"}},
        source_report_id=107, now=NOW,
    )
    assert fresh.freshness_status == "FRESH"
    assert stale.freshness_status == "STALE"
    assert fresh.quality_flags[-1] == "HIGH"
    assert stale.quality_flags[-1] == "HIGH"
    assert unknown_timing.freshness_status == "UNKNOWN"


def test_material_event_reaches_real_handoff_with_external_lineage(trigger_db):
    class Runner:
        def complete(self, **kwargs):
            result = _result("hold")
            result.code = kwargs["symbol"]
            return AnalysisCompletion(result, {"data_quality": {"level": "good"}}, 105, False, NOW)

    class Publisher:
        def __init__(self):
            self.proposals = []

        def publish(self, proposal):
            self.proposals.append(proposal)
            return _ack(proposal, "NO_ACTION")

    coordinator = ResearchTriggerCoordinator(trigger_db)
    coordinator.enqueue_material_event(
        symbol="600519", event_id="material-integrated-1", effective_at=NOW,
        evidence_refs=("news:material-integrated-1",), snapshot_id="snapshot-1",
    )
    publisher = Publisher()
    service = ProposalHandoffLoopService(
        config=_config(max_symbols=1, holdings_limit=1),
        analysis_runner=Runner(), publisher=publisher,
        snapshot_source=type("SnapshotSource", (), {
            "capture_snapshot": lambda self: _snapshot_many("600519"),
        })(),
        trigger_coordinator=coordinator, clock=lambda: NOW,
    )
    result = service.run_cycle(scheduled_for=NOW)
    assert result.status == "COMPLETED", result.blocked_reasons
    assert publisher.proposals[0].candidate_provenance.candidate_source == "EXTERNAL_EVENT"
    assert publisher.proposals[0].research_trigger.trigger_type == "MATERIAL_EVENT_REVIEW"


def test_screening_and_manual_triggers_keep_candidate_provenance_separate(trigger_db):
    class ScreeningSource:
        def latest(self, *, max_candidates, max_age):
            return [ScreeningCandidate(
                symbol="300274", name="candidate", screening_run_id="run-004",
                strategy="capital_heat", rank=1, screen_score=80.0, score=81.0,
                selected_at=NOW.isoformat(),
            )]

    class Runner:
        def complete(self, **kwargs):
            result = _result("hold")
            result.code = kwargs["symbol"]
            return AnalysisCompletion(result, {}, 104, False, NOW)

    class SnapshotSource:
        def capture_snapshot(self):
            return _snapshot(as_of=NOW - timedelta(minutes=1))

    class Publisher:
        def __init__(self):
            self.proposals = []

        def publish(self, proposal):
            self.proposals.append(proposal)
            return _ack(proposal, "NO_ACTION")

    publisher = Publisher()
    service = ProposalHandoffLoopService(
        config=_config(symbols=("000001",), max_symbols=3, holdings_limit=1),
        analysis_runner=Runner(), publisher=publisher,
        snapshot_source=SnapshotSource(), screening_candidate_source=ScreeningSource(),
        trigger_coordinator=ResearchTriggerCoordinator(trigger_db), clock=lambda: NOW,
    )
    result = service.run_cycle(scheduled_for=NOW)
    assert result.status == "COMPLETED", result.blocked_reasons
    assert len(publisher.proposals) == 3
    by_source = {
        item.candidate_provenance.candidate_source: item
        for item in publisher.proposals if item.candidate_provenance is not None
    }
    screening = by_source["SCREENING"]
    assert screening.candidate_provenance.screening_run_id == "run-004"
    assert screening.research_trigger.trigger_type == "SCHEDULED_SCREENING"
    assert screening.research_trigger.screening_run_id == "run-004"
    assert screening.research_trigger.research_trigger_id == (
        screening.research_trigger.research_trigger_id
    )
    assert all(item.research_trigger is not None for item in publisher.proposals)
    assert all(
        item.research_trigger.research_trigger_id
        == item.research_trigger.research_trigger_id
        for item in publisher.proposals
    )
    assert all(item.data_evidence for item in publisher.proposals)
    assert all(
        item.data_evidence[0].source_reference.startswith("portfolio-snapshot:")
        for item in publisher.proposals
    )
    assert all(item.data_evidence[0].freshness_status == "FRESH" for item in publisher.proposals)
    assert all(item.data_evidence[1].freshness_status == "UNKNOWN" for item in publisher.proposals)
    coverage = ResearchTriggerCoordinator(trigger_db).coverage.projection()
    assert coverage[0]["last_successful_review_id"].startswith("research-")


def test_real_m2_shadow_wiring_persists_trigger_lineage(trigger_db):
    class Runner:
        def complete(self, **kwargs):
            result = _analysis_result()
            result.code = kwargs["symbol"]
            return AnalysisCompletion(result, {"data_quality": {"level": "good"}}, 204, False, NOW)

    config = _config(symbols=(), max_symbols=1, holdings_limit=1)
    config.single_brain_m2_account_id = "simulation-account-1"
    service = M2ShadowLoopService(
        config=config,
        snapshot_source=_SnapshotSource(_snapshot(as_of=NOW - timedelta(minutes=1))),
        policy_source=_PolicySource(_policy(
            effective_from=NOW - timedelta(days=1),
            effective_until=NOW + timedelta(days=1),
        )),
        analysis_runner=Runner(),
        lineage_store=DecisionScorecardService(db_manager=trigger_db),
        repository=M2OperationalRepository(trigger_db),
        trigger_coordinator=ResearchTriggerCoordinator(trigger_db),
        clock=lambda: NOW,
    )
    result = service.run_cycle(scheduled_for=NOW)
    assert result.status == "COMPLETED", result.blocked_reasons
    item = DecisionScorecardService(db_manager=trigger_db).get(result.persisted_decision_ids[0])["item"]
    trigger = item["research_bundle"]["research_trigger"]
    assert trigger["trigger_type"] == "SCHEDULED_HOLDING_REVIEW"
    assert trigger["portfolio_snapshot_id"] == _snapshot(as_of=NOW - timedelta(minutes=1)).snapshot_id
    assert item["research_bundle"]["data_evidence"]
    assert item["execution_mandate"] is None


def test_research_runtime_signals_include_fairness_capacity_and_data_status(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    scopes = coordinator.plan(
        config=_config(max_symbols=1), snapshot=_snapshot_many("600519", "600036"),
        screening_candidates=[], cycle_id="cycle-signals", now=NOW,
    )
    signals = build_research_runtime_signals(
        coordinator=coordinator,
        now=NOW,
        data_evidence=(analysis_context_evidence(
            context_snapshot={}, source_report_id=104, now=NOW,
        ),),
    )
    assert len(scopes) == 1
    assert signals["open_holdings_due"] == 1
    assert signals["capacity_deferrals"] == 1
    assert signals["never_reviewed_holdings"] == 2
    assert signals["data_availability"] == {"UNKNOWN": 1}
