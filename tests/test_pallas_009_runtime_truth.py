from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import time

from src.market_review_contract import build_market_context, derive_market_strength, no_action_outcome
from src.services.decision_scorecard_service import DecisionScorecardService
from src.services.task_queue import AnalysisTaskQueue, TaskInfo, TaskStatus
from src.market_analyzer import MarketAnalyzer


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
    assert no_action_outcome(task_id="task-1", reason="threshold") ["outcome"] == "NO_ACTION"
