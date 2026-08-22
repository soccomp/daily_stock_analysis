from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import time
from unittest.mock import patch

from src.core.market_review import run_market_review
from src.market_review_contract import build_market_context, derive_market_strength, no_action_outcome
from src.services.decision_scorecard_service import DecisionScorecardService
from src.services.task_queue import AnalysisTaskQueue, TaskInfo, TaskStatus
from src.market_analyzer import MarketAnalyzer
from src.investment.proposal.orchestration import ProposalHandoffLoopService
from src.repositories.market_review_outcome_repo import MarketReviewOutcomeRepository
from src.storage import DatabaseManager, MarketReviewOutcomeRecord


def test_invalid_historical_scorecard_is_listed_without_rewrite():
    created = datetime(2026, 8, 22, tzinfo=timezone.utc)
    row = SimpleNamespace(
        decision_id="legacy-1",
        trace_id="trace-1",
        account_id="account-1",
        symbol="600519",
        action="HOLD",
        payload_hash="f" * 64,
        payload_json='{"schema_version":"legacy-scorecard-v0"}',
        created_at=created,
    )

    class Repository:
        def list_ordered(self, **_kwargs):
            return [row]

    result = DecisionScorecardService(repository=Repository()).list()

    assert result["total"] == 1
    assert result["items"][0]["integrity_status"] == "LEGACY_UNVERIFIABLE"
    assert row.payload_hash == "f" * 64


def test_task_stage_is_monotonic_and_stale_reconciliation_is_explicit():
    queue = object.__new__(AnalysisTaskQueue)
    queue._tasks = {}
    queue._futures = {}
    queue._analyzing_stocks = {}
    queue._data_lock = __import__("threading").RLock()
    queue._subscribers = []
    queue._subscribers_lock = __import__("threading").Lock()
    queue._main_loop = None
    queue._max_flow_events_per_task = 20
    queue._broadcast_event = lambda *_args, **_kwargs: None
    now = datetime.now()
    task = TaskInfo(
        task_id="task-1",
        stock_code="market_review",
        status=TaskStatus.PROCESSING,
        stage="PREPARING",
        updated_at=now - timedelta(minutes=10),
        heartbeat_at=now - timedelta(minutes=10),
    )
    queue._tasks[task.task_id] = task

    queue.update_task_stage(task.task_id, "COLLECTING_BREADTH", "breadth")
    assert queue.get_task(task.task_id).stage == "COLLECTING_BREADTH"
    task.heartbeat_at = now - timedelta(minutes=10)
    task.updated_at = task.heartbeat_at
    stale = queue.reconcile_stale_tasks(timeout_seconds=60, now=now)

    assert stale[0].status is TaskStatus.STALE
    assert stale[0].task_id == task.task_id
    assert "heartbeat" in stale[0].error


def test_restart_reconciles_persisted_processing_task_and_keeps_identity(tmp_path, monkeypatch):
    state_path = tmp_path / "task-queue.json"
    monkeypatch.setenv("DSA_TASK_QUEUE_STATE_PATH", str(state_path))
    original = AnalysisTaskQueue._instance
    try:
        AnalysisTaskQueue._instance = None
        first = AnalysisTaskQueue(max_workers=1)
        task = TaskInfo(
            task_id="restart-task-1",
            trace_id="restart-trace-1",
            stock_code="600519",
            status=TaskStatus.PROCESSING,
            stage="LLM_GENERATION",
            execution_id="execution-1",
            heartbeat_at=datetime.now() - timedelta(minutes=10),
            updated_at=datetime.now() - timedelta(minutes=10),
        )
        first._tasks[task.task_id] = task
        first._analyzing_stocks["600519"] = task.task_id
        with first._data_lock:
            first._persist_tasks_locked()

        AnalysisTaskQueue._instance = None
        restarted = AnalysisTaskQueue(max_workers=1)
        recovered = restarted.get_task(task.task_id)
        assert recovered is not None
        assert recovered.task_id == "restart-task-1"
        assert recovered.execution_id == "execution-1"
        stale = restarted.reconcile_stale_tasks(timeout_seconds=60)
        assert stale[0].task_id == "restart-task-1"
        assert stale[0].status is TaskStatus.STALE
        assert restarted.get_analyzing_task_id("600519") is None
    finally:
        AnalysisTaskQueue._instance = original


def test_slow_market_review_stage_emits_liveness_without_fake_progress():
    events = []
    analyzer = object.__new__(MarketAnalyzer)
    analyzer.progress_callback = lambda progress, stage, message: events.append(
        (progress, stage, message)
    )
    analyzer.heartbeat_interval_seconds = 0.01

    assert analyzer._run_stage(
        75,
        "LLM_GENERATION",
        "Generating market review",
        lambda: (time.sleep(0.05), "report")[1],
    ) == "report"
    assert events[0] == (75, "LLM_GENERATION", "Generating market review")
    assert any("仍在进行" in message for _, _, message in events[1:])
    assert all(progress == 75 and stage == "LLM_GENERATION" for progress, stage, _ in events)


def test_market_context_strength_is_structured_and_no_action_is_durable():
    payload = {
        "kind": "market_review",
        "region": "cn",
        "date": "2026-08-22",
        "generated_at": "2026-08-22T08:00:00+00:00",
        "indices": [{"change_pct": 1.0}],
        "breadth": {"up_count": 60, "down_count": 30, "flat_count": 10, "limit_up_count": 6, "limit_down_count": 1},
        "concepts": {"top": [], "bottom": [], "data_status": "available_empty"},
        "data_quality": {"indices": "available", "breadth": "available", "sectors": "available", "concepts": "available_empty"},
    }
    context = build_market_context(payload, task_id="task-1")

    assert context["market_strength"]["method"] == "deterministic_structured_inputs_v1"
    assert context["provenance"]["source_task_id"] == "task-1"
    assert derive_market_strength(payload)["value"] > 0
    in_memory = no_action_outcome(task_id="task-1", reason="threshold")
    assert in_memory["outcome"] == "NO_ACTION"
    assert in_memory["durable"] is False


def test_no_action_is_persisted_with_stable_identity_and_integrity(tmp_path, monkeypatch):
    database_path = tmp_path / "market-review-outcomes.db"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    DatabaseManager.reset_instance()
    try:
        repository = MarketReviewOutcomeRepository(DatabaseManager.get_instance())
        first = repository.persist_no_action(
            source_task_id="cycle-no-action-1",
            trade_date=datetime(2026, 8, 22, tzinfo=timezone.utc).date(),
            reason="threshold",
            persisted_at=datetime(2026, 8, 22, 8, 1, tzinfo=timezone.utc),
        )
        second = repository.persist_no_action(
            source_task_id="cycle-no-action-1",
            trade_date=datetime(2026, 8, 22, tzinfo=timezone.utc).date(),
            reason="threshold",
            persisted_at=datetime(2026, 8, 22, 8, 2, tzinfo=timezone.utc),
        )
        assert first == second
        assert first["durable"] is True
        assert first["outcome_id"]
        assert first["content_hash"]
        assert repository.get_no_action(
            source_task_id="cycle-no-action-1",
            trade_date=datetime(2026, 8, 22).date(),
        )["outcome_id"] == first["outcome_id"]
        with DatabaseManager.get_instance().get_session() as session:
            assert session.query(MarketReviewOutcomeRecord).count() == 1
    finally:
        DatabaseManager.reset_instance()


def test_proposal_handoff_no_action_branch_persists_canonical_record(tmp_path, monkeypatch):
    database_path = tmp_path / "handoff-no-action.db"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    DatabaseManager.reset_instance()

    class EmptyCoordinator:
        def plan(self, **_kwargs):
            return []

    class SnapshotSource:
        def capture_snapshot(self):
            return object()

    class UnusedRunner:
        def complete(self, **_kwargs):  # pragma: no cover - no scopes must be selected
            raise AssertionError("NO_ACTION must not analyze a symbol")

    try:
        result = ProposalHandoffLoopService(
            config=SimpleNamespace(
                single_brain_m2_enabled=True,
                single_brain_m2_interval_minutes=60,
            ),
            analysis_runner=UnusedRunner(),
            publisher=object(),
            snapshot_source=SnapshotSource(),
            trigger_coordinator=EmptyCoordinator(),
            clock=lambda: datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc),
        ).run_cycle(scheduled_for=datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc))
        assert result.status == "NO_ACTION"
        assert result.no_action_outcome["durable"] is True
        assert result.no_action_outcome["source_task_id"] == result.cycle_id
        assert MarketReviewOutcomeRepository().get_no_action(
            source_task_id=result.cycle_id,
            trade_date=datetime(2026, 8, 22).date(),
        )["outcome_id"] == result.no_action_outcome["outcome_id"]
    finally:
        DatabaseManager.reset_instance()


def test_api_market_review_callback_is_monotonic_for_llm_and_multi_market(tmp_path):
    queue = object.__new__(AnalysisTaskQueue)
    queue._tasks = {}
    queue._futures = {}
    queue._analyzing_stocks = {}
    queue._data_lock = __import__("threading").RLock()
    queue._subscribers = []
    queue._subscribers_lock = __import__("threading").Lock()
    queue._main_loop = None
    queue._max_flow_events_per_task = 20
    queue._max_history = 100
    queue._state_path = tmp_path / "queue-state.json"
    queue._broadcast_event = lambda *_args, **_kwargs: None
    task = TaskInfo(
        task_id="market-review-api-task",
        stock_code="market_review",
        status=TaskStatus.PROCESSING,
        stage="PREPARING",
    )
    queue._tasks[task.task_id] = task

    class LlmReturningAnalyzer:
        def __init__(self, *, progress_callback=None, region=None, **_kwargs):
            self.progress_callback = progress_callback
            self.region = region

        def run_daily_review_with_snapshot(self):
            for progress, stage, message in (
                (10, "COLLECTING_INDICES", "indices"),
                (30, "COLLECTING_BREADTH", "breadth"),
                (45, "COLLECTING_SECTORS_CONCEPTS", "sectors"),
                (60, "COLLECTING_NEWS", "news"),
                (68, "ASSEMBLING_CONTEXT", "context"),
                (75, "LLM_GENERATION", "llm"),
                (84, "PARSING_VALIDATING", "parsed"),
            ):
                self.progress_callback(progress, stage, message)
            return SimpleNamespace(
                report=f"{self.region} report",
                market_light_snapshot={"region": self.region, "trade_date": "2026-08-22"},
            )

    notifier = SimpleNamespace(
        save_report_to_file=lambda *_args: "/tmp/market-review.md",
        is_available=lambda: False,
    )
    events = []

    def update(progress, stage, message):
        events.append((progress, stage, message))
        queue.update_task_stage(task.task_id, stage, message, progress=progress)

    def run_task():
        with patch("src.core.market_review.MarketAnalyzer", LlmReturningAnalyzer):
            result = run_market_review(
                notifier,
                config=SimpleNamespace(report_language="zh", market_review_region="cn,us"),
                send_notification=False,
                save_report_file=False,
                persist_history=False,
                return_structured=True,
                query_id=task.task_id,
                progress_callback=update,
            )
        return {"market_review": result.report}

    result = queue._execute_background_task(task.task_id, run_task)

    assert result is not None
    assert task.status is TaskStatus.COMPLETED
    assert task.stage == "COMPLETED"
    assert task.progress == 100
    assert any("market=us substage=COLLECTING_INDICES" in message for _, _, message in events)
