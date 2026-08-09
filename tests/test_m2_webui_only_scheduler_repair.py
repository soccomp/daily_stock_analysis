"""Serve-only startup permits exactly one M2 shadow scheduler authority."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.services.runtime_scheduler import (
    RuntimeSchedulerService,
    SCHEDULER_MODE_M2_SHADOW_ONLY,
    SCHEDULER_MODE_OFF,
)


class _NoopThread:
    def __init__(self, target=None, **_kwargs):
        self.target = target

    def start(self):
        return None


class _BackgroundOnlyScheduler:
    instances = []

    def __init__(self, **_kwargs):
        self.daily_task_calls = []
        self._background_tasks = []
        self.schedule_times = []
        self._stopped = False
        self.__class__.instances.append(self)

    def set_daily_task(self, task, run_immediately=True):
        self.daily_task_calls.append((task, run_immediately))

    def add_background_task(
        self,
        task,
        interval_seconds,
        run_immediately=False,
        name=None,
    ):
        self._background_tasks.append({
            "task": task,
            "interval_seconds": interval_seconds,
            "last_run": 1000.0,
            "name": name,
            "running": False,
            "run_immediately": run_immediately,
        })

    def run(self):
        return None

    def stop(self):
        self._stopped = True

    @property
    def schedule(self):
        return SimpleNamespace(get_jobs=lambda: [])


def _config(*, m2_enabled: bool):
    return SimpleNamespace(
        schedule_enabled=True,
        schedule_time="18:00",
        schedule_times=["18:00"],
        agent_event_monitor_enabled=True,
        single_brain_m2_enabled=m2_enabled,
        single_brain_m2_interval_minutes=60,
        single_brain_m2_run_immediately=False,
    )


def test_m2_disabled_registers_no_serve_only_recurring_authority():
    config = _config(m2_enabled=False)
    service = RuntimeSchedulerService(
        config_provider=lambda: config,
        m2_shadow_only=True,
    )

    service.reconcile_from_config()

    status = service.status()
    assert status["enabled"] is False
    assert status["mode"] == SCHEDULER_MODE_OFF
    assert status["background_tasks"] == []


def test_m2_enabled_registers_one_background_only_authority_at_existing_cadence():
    _BackgroundOnlyScheduler.instances = []
    config = _config(m2_enabled=True)
    ordinary_runner = MagicMock()
    service = RuntimeSchedulerService(
        config_provider=lambda: config,
        task_runner=ordinary_runner,
        m2_shadow_only=True,
    )
    service._reload_config = lambda: config

    with patch(
        "src.services.runtime_scheduler.Scheduler",
        _BackgroundOnlyScheduler,
    ), patch(
        "src.services.runtime_scheduler.threading.Thread",
        _NoopThread,
    ):
        service.reconcile_from_config()
        first_scheduler = service._scheduler
        service.reconcile_from_config()

    assert len(_BackgroundOnlyScheduler.instances) == 1
    assert service._scheduler is first_scheduler
    assert first_scheduler.daily_task_calls == []
    assert [
        task["name"] for task in first_scheduler._background_tasks
    ] == ["single_brain_m2_shadow"]
    assert first_scheduler._background_tasks[0]["interval_seconds"] == 60 * 60
    assert ordinary_runner.call_count == 0
    status = service.status()
    assert status["enabled"] is True
    assert status["mode"] == SCHEDULER_MODE_M2_SHADOW_ONLY
    assert len(status["background_tasks"]) == 1
    assert status["background_tasks"][0]["interval_seconds"] == 60 * 60


def test_m2_shadow_only_never_registers_event_monitor_or_daily_analysis():
    _BackgroundOnlyScheduler.instances = []
    config = _config(m2_enabled=True)
    service = RuntimeSchedulerService(
        config_provider=lambda: config,
        m2_shadow_only=True,
    )
    service._reload_config = lambda: config

    with patch(
        "src.services.runtime_scheduler.Scheduler",
        _BackgroundOnlyScheduler,
    ), patch(
        "src.services.runtime_scheduler.threading.Thread",
        _NoopThread,
    ), patch(
        "src.services.runtime_scheduler.build_agent_event_monitor_background_tasks"
    ) as event_monitor_builder:
        service.start(run_immediately=True)

    scheduler = _BackgroundOnlyScheduler.instances[0]
    event_monitor_builder.assert_not_called()
    assert scheduler.daily_task_calls == []
    assert scheduler._background_tasks[0]["run_immediately"] is False
