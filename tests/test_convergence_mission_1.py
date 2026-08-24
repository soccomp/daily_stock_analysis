"""Focused deterministic evidence for PALLAS Convergence Mission 1."""

import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.investment.canonical_cycle import CanonicalCycleRepository
from src.investment.m2.identity import cycle_id as build_cycle_id
from src.investment.m2.identity import cycle_slot
from src.investment.proposal.orchestration import ProposalHandoffLoopService
from src.investment.proposal.transport import AthenaProposalAcknowledgement
from src.repositories.market_review_linkage_repo import MarketReviewLinkageRepository
from src.scheduler import Scheduler
from src.services.runtime_scheduler import build_single_brain_m2_background_tasks
from src.services.runtime_scheduler import _persist_proposal_handoff_terminal
from src.services.runtime_scheduler import _RUNTIME_ANALYSIS_LOCK, run_with_global_analysis_lock
from src.services.runtime_scheduler import RuntimeSchedulerService
from src.storage import AnalysisHistory, DatabaseManager


UTC = timezone.utc
NOW = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mission-1.db"))
    monkeypatch.setattr(Config, "_instance", None)
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _config():
    return SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_m2_interval_minutes=60,
        single_brain_m2_symbols=("000001",),
    )


class _EmptyCoordinator:
    def plan(self, **_kwargs):
        return []


class _SnapshotSource:
    def capture_snapshot(self):
        return object()


def _service(*, coordinator=None, runner=None, publisher=None, clock=lambda: NOW):
    return ProposalHandoffLoopService(
        config=_config(),
        analysis_runner=runner or SimpleNamespace(),
        publisher=publisher or SimpleNamespace(),
        snapshot_source=_SnapshotSource(),
        trigger_coordinator=coordinator or _EmptyCoordinator(),
        clock=clock,
    )


def _market_context(task_id: str, context_id: str, as_of: datetime) -> dict:
    return {
        "source_task_id": task_id,
        "market_review_id": task_id,
        "context_id": context_id,
        "trade_date": as_of.date().isoformat(),
        "as_of": as_of.isoformat(),
        "provenance": {"source_task_id": task_id},
    }


def _run_real_scheduler_handoff(*, isolated_db, monkeypatch, due: datetime, started: datetime):
    """Run the timestamp-aware proposal task through the real Scheduler layer."""

    config = SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_m2_interval_minutes=60,
        single_brain_m2_run_immediately=False,
        single_brain_execution_mode="PROPOSAL_HANDOFF",
    )
    captured = {}

    real_service = ProposalHandoffLoopService(
        config=config,
        analysis_runner=SimpleNamespace(),
        publisher=SimpleNamespace(),
        snapshot_source=SimpleNamespace(
            capture_snapshot=lambda: (_ for _ in ()).throw(
                AssertionError("missing MarketContext must block before snapshot work")
            )
        ),
        trigger_coordinator=_EmptyCoordinator(),
        clock=lambda: started,
    )
    original_run_cycle = real_service.run_cycle

    def _capture_run_cycle(**kwargs):
        captured.update(kwargs)
        result = original_run_cycle(**kwargs)
        captured["cycle_id"] = result.cycle_id
        return result

    real_service.run_cycle = _capture_run_cycle
    monkeypatch.setattr(
        ProposalHandoffLoopService,
        "from_config",
        staticmethod(lambda _config: real_service),
    )
    task = build_single_brain_m2_background_tasks(
        config,
        config_provider=lambda: config,
    )[0]

    fake_schedule = SimpleNamespace(get_jobs=lambda: [])
    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False

    def _make_thread(target=None, **_kwargs):
        fake_thread.start.side_effect = target
        return fake_thread

    registration_epoch = due.timestamp() - 3600
    scheduler_time_values = iter(
        [registration_epoch, started.timestamp(), started.timestamp()]
    )
    with patch.dict(sys.modules, {"schedule": fake_schedule}), patch(
        "src.scheduler.time.time",
        side_effect=lambda: next(scheduler_time_values),
    ), patch("src.scheduler.threading.Thread", side_effect=_make_thread):
        scheduler = Scheduler(schedule_time="18:00", register_signals=False)
        scheduler.add_background_task(
            task["task"],
            interval_seconds=3600,
            run_immediately=False,
            name=task["name"],
        )
        scheduler._run_background_tasks()

    assert captured["scheduled_for"] == due
    assert captured["started_at"] == started
    cycle = CanonicalCycleRepository(isolated_db).get_cycle(
        captured["cycle_id"]
    )
    return captured, cycle, scheduler._background_tasks[0]


def test_canonical_cycle_repository_is_durable_and_projection_is_read_only(isolated_db):
    repository = CanonicalCycleRepository(isolated_db)
    cycle_id = "m2-cycle-mission-1-durable"
    repository.start_cycle(
        cycle_id=cycle_id,
        scheduler_task_name="single_brain_proposal_handoff",
        scheduled_for=NOW,
        source_runtime_identity="DSA:test",
        now=NOW,
    )
    repository.set_stage(
        cycle_id=cycle_id,
        stage="SCHEDULER",
        state="SUCCEEDED",
        object_id=cycle_id,
        reason_code="CYCLE_STARTED",
        at=NOW,
    )
    repository.set_stage(
        cycle_id=cycle_id,
        stage="LOCK",
        state="SUCCEEDED",
        reason_code="GLOBAL_ANALYSIS_LOCK_ACQUIRED",
        at=NOW,
    )
    repository.update_identity_and_counts(
        cycle_id=cycle_id,
        candidate_count=1,
        candidate_outcomes=({"symbol": "000001", "status": "SUCCEEDED"},),
    )
    repository.finish_cycle(
        cycle_id=cycle_id,
        status="SUCCEEDED",
        terminal_reason_code="PROPOSAL_HANDOFF_COMPLETE",
        ended_at=NOW,
    )

    before = repository.get_cycle(cycle_id)
    projection = repository.scheduler_projection(
        scheduler_task_name="single_brain_proposal_handoff"
    )
    after = repository.get_cycle(cycle_id)

    assert before == after
    assert projection["current_cycle_id"] is None
    assert projection["last_terminal_cycle_id"] == cycle_id
    assert projection["last_terminal_status"] == "SUCCEEDED"
    assert repository.stage_events(cycle_id)[0]["object_id"] == cycle_id


def test_natural_no_action_cycle_has_terminal_ledger_and_all_zero_stages(isolated_db):
    result = _service().run_cycle(
        scheduled_for=NOW,
        lock_acquired_at=NOW,
    )

    assert result.status == "NO_ACTION"
    assert result.canonical_cycle["status"] == "NO_ACTION"
    assert result.canonical_cycle["candidate_count"] == 0
    stages = {
        item["stage"]: item["state"]
        for item in CanonicalCycleRepository(isolated_db).stage_events(result.cycle_id)
    }
    assert stages["SCHEDULER"] == "SUCCEEDED"
    assert stages["LOCK"] == "SUCCEEDED"
    assert stages["CANDIDATE_EVALUATION"] == "NO_ACTION"
    assert stages["RESEARCH_BUNDLE"] == "NO_ACTION"
    assert stages["INVESTMENT_PROPOSAL"] == "NO_ACTION"
    assert stages["ATHENA_HANDOFF_ACK"] == "NO_ACTION"


def test_natural_cycle_without_market_context_fails_closed_before_work(isolated_db):
    class MustNotRunSnapshot:
        def capture_snapshot(self):
            raise AssertionError("missing MarketContext must block before snapshot work")

    service = ProposalHandoffLoopService(
        config=_config(),
        analysis_runner=SimpleNamespace(),
        publisher=SimpleNamespace(),
        snapshot_source=MustNotRunSnapshot(),
        trigger_coordinator=_EmptyCoordinator(),
        clock=lambda: NOW,
    )
    result = service.run_cycle(
        scheduled_for=NOW,
        lock_acquired_at=NOW,
        require_market_review_context=True,
    )

    assert result.status == "FAILED_CLOSED"
    assert result.canonical_cycle["status"] == "BLOCKED"
    assert result.canonical_cycle["terminal_reason_code"] == "REQUIRED_DEPENDENCY_BLOCKED"
    assert result.canonical_cycle["current_stage"] == "LOCK"


def test_lock_unavailable_is_durable_skipped_without_entering_investment_work(isolated_db):
    config = _config()
    _persist_proposal_handoff_terminal(
        config,
        observed_at=NOW,
        status="SKIPPED",
        reason_code="GLOBAL_ANALYSIS_LOCK_UNAVAILABLE",
        reason_detail="another natural run owns the lock",
    )

    projection = CanonicalCycleRepository(isolated_db).scheduler_projection(
        scheduler_task_name="single_brain_proposal_handoff"
    )
    assert projection["last_terminal_status"] == "SKIPPED"
    assert projection["last_terminal_reason"]["code"] == "GLOBAL_ANALYSIS_LOCK_UNAVAILABLE"
    stages = CanonicalCycleRepository(isolated_db).stage_events(
        projection["last_terminal_cycle_id"]
    )
    assert next(item for item in stages if item["stage"] == "LOCK")["state"] == "BLOCKED"


def test_scheduler_status_reads_last_terminal_cycle_from_canonical_ledger(isolated_db):
    repository = CanonicalCycleRepository(isolated_db)
    cycle_id = "m2-cycle-mission-1-status"
    repository.start_cycle(
        cycle_id=cycle_id,
        scheduler_task_name="single_brain_proposal_handoff",
        scheduled_for=NOW,
        source_runtime_identity="DSA:ProposalHandoffLoopService",
        now=NOW,
    )
    repository.finish_cycle(
        cycle_id=cycle_id,
        status="NO_ACTION",
        terminal_reason_code="NO_CANDIDATE_OR_NO_ACTION_OUTCOME",
        ended_at=NOW,
    )

    config = SimpleNamespace(single_brain_execution_mode="PROPOSAL_HANDOFF")
    service = RuntimeSchedulerService(config_provider=lambda: config)
    service._enabled = True
    service._mode = "PROPOSAL_HANDOFF_ONLY"
    service._scheduler = SimpleNamespace(
        schedule=SimpleNamespace(get_jobs=lambda: []),
        _background_tasks=[
            {
                "name": "single_brain_proposal_handoff",
                "interval_seconds": 3600,
                "last_run": 0,
                "running": False,
            }
        ],
    )

    status = service.status()
    assert status["last_terminal_cycle_id"] == cycle_id
    assert status["last_terminal_status"] == "NO_ACTION"
    assert status["last_success_at"] == "2026-08-24T02:00:00Z"
    task = status["background_tasks"][0]
    assert task["last_terminal_cycle_id"] == cycle_id


def test_same_day_market_reviews_select_one_explicit_context_at_cycle_cutoff(isolated_db):
    early = _market_context("review-early", "context-early", NOW)
    late = _market_context("review-late", "context-late", NOW.replace(minute=30))
    with isolated_db.session_scope() as session:
        for index, (context, created_at) in enumerate(
            ((early, NOW), (late, NOW.replace(minute=30)))
        ):
            session.add(
                AnalysisHistory(
                    query_id=f"review-{index}",
                    code="market_review",
                    report_type="market_review",
                    context_snapshot=json.dumps(
                        {"market_review_payload": {"market_context": context}}
                    ),
                    created_at=created_at.replace(tzinfo=None),
                )
            )

    resolved = MarketReviewLinkageRepository(isolated_db).latest_market_context(
        trade_date=NOW.date(),
        as_of=NOW.replace(minute=45),
    )
    assert resolved["market_review_id"] == "review-late"
    assert resolved["context_id"] == "context-late"


def test_one_success_one_timeout_is_persisted_as_partial_with_candidate_outcomes(
    isolated_db, monkeypatch
):
    scopes = [
        {"symbol": "000001", "source": "HOLDING"},
        {"symbol": "600519", "source": "HOLDING"},
    ]

    class Coordinator:
        def plan(self, **_kwargs):
            return scopes

    class Runner:
        def complete(self, *, symbol, **_kwargs):
            if symbol == "600519":
                raise TimeoutError("deterministic timeout")
            return SimpleNamespace(
                completed_at=NOW,
                result=object(),
                context_snapshot={},
                source_report_id=101,
            )

    def build(_self, **_kwargs):
        proposal = SimpleNamespace(proposal_id="proposal-000001", content_hash="a" * 64)
        return SimpleNamespace(
            proposal=proposal,
            research_bundle=SimpleNamespace(research_id="research-000001"),
        )

    def publish(proposal):
        return AthenaProposalAcknowledgement(
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.content_hash,
            acknowledgement_id="ack-000001",
            acknowledgement_state="ACCEPTED",
            lifecycle_state="NO_ACTION",
            deduplicated=False,
        )

    monkeypatch.setattr(
        "src.investment.proposal.orchestration.InvestmentProposalBuilder.build",
        build,
    )
    result = ProposalHandoffLoopService(
        config=_config(),
        analysis_runner=Runner(),
        publisher=SimpleNamespace(publish=publish),
        snapshot_source=_SnapshotSource(),
        trigger_coordinator=Coordinator(),
        clock=lambda: NOW,
    ).run_cycle(scheduled_for=NOW, lock_acquired_at=NOW)

    assert result.status == "PARTIAL"
    assert result.canonical_cycle["status"] == "PARTIAL"
    assert result.canonical_cycle["candidate_count"] == 2
    assert {item["status"] for item in result.candidate_outcomes} == {"SUCCEEDED", "FAILED"}
    assert result.canonical_cycle["proposal_ids"] == ["proposal-000001"]


def test_live_projection_exposes_current_candidate_while_analysis_is_blocked(
    isolated_db, monkeypatch
):
    started = threading.Event()
    release = threading.Event()
    result_holder = {}

    class Coordinator:
        def plan(self, **_kwargs):
            return [{"symbol": "000001", "source": "HOLDING"}]

    class Runner:
        def complete(self, **_kwargs):
            started.set()
            assert release.wait(3)
            return SimpleNamespace(
                completed_at=NOW,
                result=object(),
                context_snapshot={},
                source_report_id=101,
            )

    def build(_self, **_kwargs):
        proposal = SimpleNamespace(proposal_id="proposal-live", content_hash="b" * 64)
        return SimpleNamespace(
            proposal=proposal,
            research_bundle=SimpleNamespace(research_id="research-live"),
        )

    def publish(proposal):
        return AthenaProposalAcknowledgement(
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.content_hash,
            acknowledgement_id="ack-live",
            acknowledgement_state="ACCEPTED",
            lifecycle_state="NO_ACTION",
            deduplicated=False,
        )

    monkeypatch.setattr(
        "src.investment.proposal.orchestration.InvestmentProposalBuilder.build",
        build,
    )
    service = ProposalHandoffLoopService(
        config=_config(),
        analysis_runner=Runner(),
        publisher=SimpleNamespace(publish=publish),
        snapshot_source=_SnapshotSource(),
        trigger_coordinator=Coordinator(),
        clock=lambda: NOW,
    )

    def run():
        result_holder["result"] = service.run_cycle(
            scheduled_for=NOW,
            market_review_context=_market_context("review-live", "context-live", NOW),
            lock_acquired_at=NOW,
        )

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(2)
    projection = CanonicalCycleRepository(isolated_db).scheduler_projection(
        scheduler_task_name="single_brain_proposal_handoff"
    )
    assert projection["current_stage"] == "CANDIDATE_EVALUATION"
    assert projection["current_symbol_or_scope"] == "000001:HOLDING"
    assert projection["current_work_state"] == "RUNNING"

    release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert result_holder["result"].status in {"COMPLETED", "PARTIAL"}
    terminal = CanonicalCycleRepository(isolated_db).get_cycle(
        result_holder["result"].cycle_id
    )
    assert terminal["current_stage"] == "ATHENA_HANDOFF_ACK"
    assert terminal["current_symbol_or_scope"] is None


def test_actual_scheduled_time_is_separate_from_cycle_slot(isolated_db):
    due = datetime(2026, 8, 24, 2, 12, 28, tzinfo=UTC)
    result = _service(clock=lambda: due).run_cycle(
        scheduled_for=due,
        lock_acquired_at=due,
    )
    assert result.canonical_cycle["scheduled_for"] == "2026-08-24T02:12:28Z"
    assert result.canonical_cycle["cycle_slot"] == "2026-08-24T02:00:00Z"
    assert result.cycle_id == build_cycle_id(
        account_id="dsa-proposal-authority",
        scheduled_for=cycle_slot(due, interval_minutes=60),
    )
    assert cycle_slot(due, interval_minutes=60).isoformat() == "2026-08-24T02:00:00+00:00"


def test_real_background_scheduler_preserves_delayed_due_time(isolated_db, monkeypatch):
    due = datetime(2026, 8, 24, 14, 12, 28, tzinfo=UTC)
    started = datetime(2026, 8, 24, 14, 12, 40, tzinfo=UTC)

    captured, cycle, entry = _run_real_scheduler_handoff(
        isolated_db=isolated_db,
        monkeypatch=monkeypatch,
        due=due,
        started=started,
    )

    assert entry["scheduled_for_epoch"] == due.timestamp()
    assert entry["started_at_epoch"] == started.timestamp()
    assert entry["last_run"] == started.timestamp()
    assert cycle["scheduled_for"] == "2026-08-24T14:12:28Z"
    assert cycle["started_at"] == "2026-08-24T14:12:40Z"
    assert cycle["cycle_slot"] == "2026-08-24T14:00:00Z"
    assert captured["cycle_id"] == build_cycle_id(
        account_id="dsa-proposal-authority",
        scheduled_for=cycle_slot(due, interval_minutes=60),
    )


def test_real_background_scheduler_keeps_prior_identity_across_slot_boundary(
    isolated_db, monkeypatch
):
    due = datetime(2026, 8, 24, 14, 59, 59, tzinfo=UTC)
    started = datetime(2026, 8, 24, 15, 0, 10, tzinfo=UTC)

    captured, cycle, entry = _run_real_scheduler_handoff(
        isolated_db=isolated_db,
        monkeypatch=monkeypatch,
        due=due,
        started=started,
    )

    assert captured["scheduled_for"] == due
    assert captured["started_at"] == started
    assert captured["started_at"] > captured["scheduled_for"]
    assert entry["last_run"] == started.timestamp()
    assert cycle["scheduled_for"] == "2026-08-24T14:59:59Z"
    assert cycle["started_at"] == "2026-08-24T15:00:10Z"
    assert cycle["cycle_slot"] == "2026-08-24T14:00:00Z"
    assert cycle["cycle_id"] == build_cycle_id(
        account_id="dsa-proposal-authority",
        scheduled_for=cycle_slot(due, interval_minutes=60),
    )
    assert cycle["cycle_id"] != build_cycle_id(
        account_id="dsa-proposal-authority",
        scheduled_for=cycle_slot(started, interval_minutes=60),
    )


def test_lock_release_is_persisted_after_wrapper_unlocks_on_success(isolated_db):
    repository = CanonicalCycleRepository(isolated_db)
    cycle_id = "m2-cycle-lock-release-success"
    repository.start_cycle(
        cycle_id=cycle_id,
        scheduler_task_name="single_brain_proposal_handoff",
        scheduled_for=NOW,
        source_runtime_identity="DSA:test",
        now=NOW,
    )
    repository.record_lock(cycle_id=cycle_id, acquired_at=NOW)
    callback_state = {}

    def task(*_args):
        repository.finish_cycle(
            cycle_id=cycle_id,
            status="SUCCEEDED",
            terminal_reason_code="PROPOSAL_HANDOFF_COMPLETE",
            ended_at=NOW + timedelta(seconds=1),
        )

    def after_release(released_at):
        callback_state["lock_was_released"] = _RUNTIME_ANALYSIS_LOCK.acquire(
            blocking=False
        )
        if callback_state["lock_was_released"]:
            _RUNTIME_ANALYSIS_LOCK.release()
        repository.record_lock(cycle_id=cycle_id, released_at=released_at)

    assert run_with_global_analysis_lock(
        task,
        SimpleNamespace(),
        None,
        blocking=True,
        on_released=after_release,
    )
    cycle = repository.get_cycle(cycle_id)
    assert callback_state["lock_was_released"] is True
    assert cycle["lock_released_at"] is not None
    assert cycle["lock_released_at"] >= cycle["ended_at"]


def test_lock_release_is_persisted_after_wrapper_unlocks_on_exception(isolated_db):
    repository = CanonicalCycleRepository(isolated_db)
    cycle_id = "m2-cycle-lock-release-failure"
    repository.start_cycle(
        cycle_id=cycle_id,
        scheduler_task_name="single_brain_proposal_handoff",
        scheduled_for=NOW,
        source_runtime_identity="DSA:test",
        now=NOW,
    )
    repository.record_lock(cycle_id=cycle_id, acquired_at=NOW)

    def task(*_args):
        repository.finish_cycle(
            cycle_id=cycle_id,
            status="FAILED",
            terminal_reason_code="UNEXPECTED_EXCEPTION",
            ended_at=NOW + timedelta(seconds=1),
        )
        raise RuntimeError("deterministic failure")

    def after_release(released_at):
        repository.record_lock(cycle_id=cycle_id, released_at=released_at)

    with pytest.raises(RuntimeError, match="deterministic failure"):
        run_with_global_analysis_lock(
            task,
            SimpleNamespace(),
            None,
            blocking=True,
            on_released=after_release,
        )
    cycle = repository.get_cycle(cycle_id)
    assert cycle["status"] == "FAILED"
    assert cycle["lock_released_at"] >= cycle["ended_at"]


def test_lock_unavailable_does_not_invoke_release_callback():
    assert _RUNTIME_ANALYSIS_LOCK.acquire(blocking=False)
    callback_called = []
    try:
        assert not run_with_global_analysis_lock(
            lambda *_args: None,
            SimpleNamespace(),
            None,
            blocking=False,
            on_released=lambda _released_at: callback_called.append(True),
        )
    finally:
        _RUNTIME_ANALYSIS_LOCK.release()
    assert callback_called == []
