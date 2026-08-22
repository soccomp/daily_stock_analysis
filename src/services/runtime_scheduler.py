# -*- coding: utf-8 -*-
"""Runtime scheduler service for long-lived API/Web/Desktop processes."""

from __future__ import annotations

import logging
import os
import threading
import _thread
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Set

from src.config import Config, get_config
from src.scheduler import Scheduler, normalize_schedule_times

logger = logging.getLogger(__name__)
CLI_SCHEDULER_OWNER_ENV = "DSA_CLI_SCHEDULER_OWNS_SCHEDULE"
RUNTIME_SCHEDULER_FORCE_ENABLED_ENV = "DSA_RUNTIME_SCHEDULER_FORCE_ENABLED"
RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV = "DSA_RUNTIME_SCHEDULER_RUN_IMMEDIATELY"
RUNTIME_SCHEDULER_SUPPRESS_START_ENV = "DSA_RUNTIME_SCHEDULER_SUPPRESS_START"
RUNTIME_SCHEDULER_M2_SHADOW_ONLY_ENV = "DSA_RUNTIME_SCHEDULER_M2_SHADOW_ONLY"
RUNTIME_SCHEDULER_ARGS_ENV = "DSA_RUNTIME_SCHEDULER_ARGS"
SCHEDULER_MODE_OFF = "OFF"
SCHEDULER_MODE_FULL = "FULL"
SCHEDULER_MODE_M2_SHADOW_ONLY = "M2_SHADOW_ONLY"
SCHEDULER_MODE_M3_SIMULATION_EXECUTION_ONLY = "M3_SIMULATION_EXECUTION_ONLY"
SCHEDULER_MODE_PROPOSAL_HANDOFF_ONLY = "PROPOSAL_HANDOFF_ONLY"
_RUNTIME_ANALYSIS_LOCK = threading.Lock()
SCHEDULE_ARGS_OVERRIDE_KEYS = {
    "no_notify",
    "no_market_review",
    "dry_run",
    "force_run",
    "single_notify",
    "no_context_snapshot",
    "workers",
    "portfolio",
}


def run_with_global_analysis_lock(
    task_runner: Callable[[Config, Any, Optional[List[str]]], Any],
    config: Config,
    args: Any,
    stock_codes: Optional[List[str]] = None,
    *,
    blocking: bool = True,
) -> bool:
    """Execute a task while holding the shared runtime analysis lock."""
    if not _RUNTIME_ANALYSIS_LOCK.acquire(blocking=blocking):
        return False
    try:
        task_runner(config, args, stock_codes)
    finally:
        _RUNTIME_ANALYSIS_LOCK.release()
    return True


def _agent_event_monitor_interval_seconds(config: Config) -> int:
    """Return the validated Event Monitor polling interval in seconds."""
    interval_minutes = getattr(config, "agent_event_monitor_interval_minutes", 5)
    try:
        interval_minutes = max(1, int(interval_minutes))
    except (TypeError, ValueError):  # pragma: no cover - defensive branch
        logger.warning(
            "Invalid AGENT_EVENT_MONITOR_INTERVAL_MINUTES=%r; use fallback 5",
            interval_minutes,
        )
        interval_minutes = 5
    return interval_minutes * 60


def build_agent_event_monitor_background_tasks(
    config: Config,
    *,
    config_provider: Callable[[], Config],
) -> List[Dict[str, Any]]:
    """Build scheduler background tasks used by the runtime scheduler."""
    if not getattr(config, "agent_event_monitor_enabled", False):
        return []

    from src.services.alert_worker import AlertWorker

    interval_seconds = _agent_event_monitor_interval_seconds(config)
    try:
        alert_worker = AlertWorker(config_provider=config_provider)
    except Exception as exc:  # pragma: no cover - defensive branch
        logger.warning("Failed to initialize AlertWorker for event monitor: %s", exc)
        return []

    def event_monitor_task() -> None:
        stats = alert_worker.run_once()
        triggered_count = stats.get("triggered", 0)
        if triggered_count:
            logger.info("[EventMonitor] triggered %d alert(s)", triggered_count)

    return [{
        "task": event_monitor_task,
        "interval_seconds": interval_seconds,
        "run_immediately": True,
        "name": "agent_event_monitor",
    }]


def build_single_brain_m2_background_tasks(
    config: Config,
    *,
    config_provider: Callable[[], Config],
) -> List[Dict[str, Any]]:
    """Build the default-off M2 shadow task on the existing scheduler lock."""
    if not getattr(config, "single_brain_m2_enabled", False):
        return []
    execution_mode = str(
        getattr(config, "single_brain_execution_mode", "SHADOW")
    ).strip().upper()
    if execution_mode == "SHADOW":
        task_name = "single_brain_m2_shadow"
    elif execution_mode == "PROPOSAL_HANDOFF":
        task_name = "single_brain_proposal_handoff"
    else:
        logger.error("Single Brain scheduler blocked: invalid execution mode %r", execution_mode)
        return []
    try:
        interval_minutes = max(
            1,
            min(1440, int(getattr(config, "single_brain_m2_interval_minutes", 60))),
        )
    except (TypeError, ValueError):
        interval_minutes = 60

    def m2_shadow_task() -> None:
        current_config = config_provider()
        if not getattr(current_config, "single_brain_m2_enabled", False):
            return
        current_mode = str(
            getattr(current_config, "single_brain_execution_mode", "SHADOW")
        ).strip().upper()
        if current_mode != execution_mode:
            logger.error(
                "Single Brain scheduler blocked: registered mode %s changed to %s",
                execution_mode,
                current_mode,
            )
            return

        def run_once(
            loaded_config: Config,
            _args: Any,
            _stock_codes: Optional[List[str]],
        ) -> None:
            if execution_mode == "PROPOSAL_HANDOFF":
                from src.investment.proposal.orchestration import ProposalHandoffLoopService

                result = ProposalHandoffLoopService.from_config(loaded_config).run_cycle()
                persisted_count = len(result.proposal_ids)
            else:
                from src.investment.m2.orchestration import M2ShadowLoopService

                result = M2ShadowLoopService.from_config(loaded_config).run_cycle()
                persisted_count = len(result.persisted_decision_ids)
            logger.info(
                "Single Brain %s cycle finished: cycle=%s status=%s persisted=%d "
                "researched=%s blocked=%s",
                execution_mode,
                result.cycle_id,
                result.status,
                persisted_count,
                ",".join(getattr(result, "researched_symbols", ())) or "-",
                "|".join(getattr(result, "blocked_reasons", ())) or "-",
            )

        acquired = run_with_global_analysis_lock(
            run_once,
            current_config,
            None,
            blocking=False,
        )
        if not acquired:
            logger.warning("Single Brain cycle skipped: analysis_already_running")

    return [{
        "task": m2_shadow_task,
        "interval_seconds": interval_minutes * 60,
        "run_immediately": bool(
            getattr(config, "single_brain_m2_run_immediately", False)
        ),
        "name": task_name,
    }]


def _restricted_single_brain_scheduler_mode(
    background_tasks: List[Dict[str, Any]],
) -> str:
    names = [entry.get("name") for entry in background_tasks]
    if names == ["single_brain_m2_shadow"]:
        return SCHEDULER_MODE_M2_SHADOW_ONLY
    if names == ["single_brain_m3_simulation_execution"]:
        return SCHEDULER_MODE_M3_SIMULATION_EXECUTION_ONLY
    if names == ["single_brain_proposal_handoff"]:
        return SCHEDULER_MODE_PROPOSAL_HANDOFF_ONLY
    return SCHEDULER_MODE_OFF


def build_cli_schedule_background_tasks(
    config: Config,
    *,
    config_provider: Callable[[], Config],
) -> List[Dict[str, Any]]:
    """Build the existing CLI scheduler's bounded background task set."""

    return [
        *build_agent_event_monitor_background_tasks(
            config,
            config_provider=config_provider,
        ),
        *build_single_brain_m2_background_tasks(
            config,
            config_provider=config_provider,
        ),
    ]


class RuntimeSchedulerService:
    """Manage scheduled analysis inside the current API/Web/Desktop process."""

    def __init__(
        self,
        *,
        config_provider: Callable[[], Config] = get_config,
        task_runner: Optional[Callable[[Config, Any, Optional[List[str]]], Any]] = None,
        owns_schedule: Optional[bool] = None,
        force_enabled: bool = False,
        run_immediately_in_background: bool = False,
        m2_shadow_only: bool = False,
        background_tasks_provider: Optional[Callable[[Config], List[Dict[str, Any]]]] = None,
        schedule_args_overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._config_provider = config_provider
        self._task_runner = task_runner
        if owns_schedule is None:
            owns_schedule = os.getenv(CLI_SCHEDULER_OWNER_ENV, "").strip().lower() not in {
                "1",
                "true",
                "yes",
                "on",
            }
        self._owns_schedule = owns_schedule
        self._force_enabled = force_enabled
        self._run_immediately_in_background = run_immediately_in_background
        self._m2_shadow_only = m2_shadow_only
        self._background_tasks_provider = background_tasks_provider
        self._schedule_args_overrides = {
            key: value
            for key, value in (schedule_args_overrides or {}).items()
            if key in SCHEDULE_ARGS_OVERRIDE_KEYS
        }
        self._background_task_cache: Dict[str, Dict[str, Any]] = {}
        self._background_task_registered_names: Set[str] = set()
        self._lock = threading.RLock()
        self._run_lock = _RUNTIME_ANALYSIS_LOCK
        self._scheduler: Optional[Scheduler] = None
        self._thread: Optional[threading.Thread] = None
        self._enabled = False
        self._mode = SCHEDULER_MODE_OFF
        self._registration_fingerprint: Optional[tuple[Any, ...]] = None
        self._last_run_at: Optional[str] = None
        self._last_success_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_skipped_at: Optional[str] = None
        self._last_skip_reason: Optional[str] = None

    def _make_schedule_args(self) -> SimpleNamespace:
        defaults = {
            "schedule": True,
            "no_run_immediately": True,
            "no_notify": False,
            "no_market_review": False,
            "dry_run": False,
            "force_run": False,
            "single_notify": False,
            "no_context_snapshot": False,
            "market_review": False,
            "serve": False,
            "serve_only": True,
            "stocks": None,
            "portfolio": None,
            "workers": None,
        }
        defaults.update(self._schedule_args_overrides)
        return SimpleNamespace(**defaults)

    def _reload_config(self) -> Config:
        from main import _reload_runtime_config

        return _reload_runtime_config()

    def _record_analysis_busy_skip(self) -> None:
        self._last_skipped_at = datetime.now().isoformat()
        self._last_skip_reason = "analysis_already_running"
        logger.warning("Runtime scheduler skipped run: analysis already running")

    def _run_analysis_locked(self, stock_codes: Optional[List[str]]) -> None:
        try:
            config = self._reload_config()
            runner = self._task_runner
            if runner is None:
                from main import run_scheduled_analysis

                runner = run_scheduled_analysis
            self._last_run_at = datetime.now().isoformat()
            result = runner(config, self._make_schedule_args(), stock_codes)
            if result is False:
                raise RuntimeError("runtime scheduled analysis reported failure")
            self._last_success_at = datetime.now().isoformat()
            self._last_error = None
        except Exception as exc:  # noqa: BLE001 - scheduled runs must not kill API process.
            self._last_error = str(exc)
            logger.exception("Runtime scheduled analysis failed: %s", exc)

    def _run_analysis_once(self, stock_codes: Optional[List[str]] = None) -> bool:
        if not self._run_lock.acquire(blocking=False):
            self._record_analysis_busy_skip()
            return False
        try:
            self._run_analysis_locked(stock_codes)
        finally:
            self._run_lock.release()
        return True

    def _current_times(self) -> List[str]:
        config = self._config_provider()
        return normalize_schedule_times(
            getattr(config, "schedule_times", None),
            fallback_time=getattr(config, "schedule_time", "18:00"),
        )

    def _is_schedule_enabled(self, config: Config) -> bool:
        return self._force_enabled or bool(getattr(config, "schedule_enabled", False))

    def _current_background_tasks(self, config: Config) -> List[Dict[str, Any]]:
        if self._m2_shadow_only:
            return build_single_brain_m2_background_tasks(
                config,
                config_provider=self._reload_config,
            )
        if self._background_tasks_provider is not None:
            return self._background_tasks_provider(config)
        return [
            *self._current_agent_event_monitor_background_tasks(config),
            *build_single_brain_m2_background_tasks(
                config,
                config_provider=self._reload_config,
            ),
        ]

    def _current_agent_event_monitor_background_tasks(self, config: Config) -> List[Dict[str, Any]]:
        name = "agent_event_monitor"
        if not getattr(config, "agent_event_monitor_enabled", False):
            self._background_task_cache.pop(name, None)
            self._background_task_registered_names.discard(name)
            return []

        cached = self._background_task_cache.get(name)
        if cached is None:
            entries = build_agent_event_monitor_background_tasks(
                config,
                config_provider=self._reload_config,
            )
            if not entries:
                self._background_task_cache.pop(name, None)
                self._background_task_registered_names.discard(name)
                return []
            cached = dict(entries[0])
            cached["name"] = name
            self._background_task_cache[name] = cached
            interval_seconds = int(cached["interval_seconds"])
        else:
            interval_seconds = _agent_event_monitor_interval_seconds(config)

        run_immediately = (
            bool(cached.get("run_immediately", False))
            and name not in self._background_task_registered_names
        )
        self._background_task_registered_names.add(name)
        return [{
            "task": cached["task"],
            "interval_seconds": interval_seconds,
            "run_immediately": run_immediately,
            "name": name,
        }]

    @staticmethod
    def _run_in_background_thread(target: Callable[[], None]) -> None:
        """Run a callback in a background thread without blocking startup."""
        try:
            _thread.start_new_thread(target, ())
            return
        except Exception:
            # Best-effort fallback for environments where the low-level thread API
            # is unavailable or restricted.
            thread = threading.Thread(target=target, daemon=True)
            thread.start()

    def start(self, *, run_immediately: bool = False) -> None:
        with self._lock:
            if not self._owns_schedule:
                self.stop()
                return
            config = self._config_provider()
            if self._m2_shadow_only:
                background_tasks = self._current_background_tasks(config)
                if not background_tasks:
                    self.stop()
                    return
                restricted_mode = _restricted_single_brain_scheduler_mode(
                    background_tasks
                )
                if restricted_mode == SCHEDULER_MODE_OFF:
                    self.stop()
                    return
                fingerprint = tuple(
                    (
                        entry.get("name"),
                        int(entry["interval_seconds"]),
                        bool(entry.get("run_immediately", False)),
                    )
                    for entry in background_tasks
                )
                if (
                    self._enabled
                    and self._mode == restricted_mode
                    and self._registration_fingerprint == fingerprint
                ):
                    return
            elif not self._is_schedule_enabled(config):
                self.stop()
                return
            else:
                background_tasks = self._current_background_tasks(config)
                fingerprint = None
            self.stop()
            times = normalize_schedule_times(
                getattr(config, "schedule_times", None),
                fallback_time=getattr(config, "schedule_time", "18:00"),
            )
            scheduler = Scheduler(
                schedule_time=getattr(config, "schedule_time", "18:00"),
                schedule_times=times,
                schedule_times_provider=self._current_times,
                register_signals=False,
            )
            if not self._m2_shadow_only:
                if run_immediately and self._run_immediately_in_background:
                    scheduler.set_daily_task(self._run_analysis_once, run_immediately=False)
                else:
                    scheduler.set_daily_task(self._run_analysis_once, run_immediately=run_immediately)
            for entry in background_tasks:
                scheduler.add_background_task(
                    entry["task"],
                    interval_seconds=entry["interval_seconds"],
                    run_immediately=entry.get("run_immediately", False),
                    name=entry.get("name"),
                )
            if (
                not self._m2_shadow_only
                and run_immediately
                and self._run_immediately_in_background
            ):
                self._run_in_background_thread(self._run_analysis_once)
            thread = threading.Thread(
                target=scheduler.run,
                daemon=True,
                name="runtime-scheduler",
            )
            self._scheduler = scheduler
            self._thread = thread
            self._enabled = True
            self._mode = (
                restricted_mode
                if self._m2_shadow_only
                else SCHEDULER_MODE_FULL
            )
            self._registration_fingerprint = fingerprint
            thread.start()

    def stop(self) -> None:
        scheduler = self._scheduler
        if scheduler is not None:
            scheduler.stop()
        self._scheduler = None
        self._thread = None
        self._enabled = False
        self._mode = SCHEDULER_MODE_OFF
        self._registration_fingerprint = None

    def reconcile_from_config(
        self,
        *,
        run_immediately: bool = False,
        clear_enabled_override: bool = False,
    ) -> None:
        if clear_enabled_override:
            self._force_enabled = False
        if not self._owns_schedule:
            self.stop()
            return
        config = self._config_provider()
        if self._m2_shadow_only:
            if getattr(config, "single_brain_m2_enabled", False):
                self.start(run_immediately=False)
            else:
                self.stop()
        elif self._is_schedule_enabled(config):
            self.start(run_immediately=run_immediately)
        else:
            self.stop()

    def run_now(self) -> Dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            self._record_analysis_busy_skip()
            return {
                "accepted": False,
                "running": True,
                "reason": "analysis_already_running",
            }

        def run_and_release() -> None:
            try:
                self._run_analysis_locked(None)
            finally:
                self._run_lock.release()

        worker = threading.Thread(
            target=run_and_release,
            daemon=True,
            name="runtime-scheduler-run-now",
        )
        try:
            worker.start()
        except Exception:
            self._run_lock.release()
            raise
        return {"accepted": True, "running": True}

    def status(self) -> Dict[str, Any]:
        scheduler = self._scheduler
        jobs = scheduler.schedule.get_jobs() if scheduler is not None else []
        next_run = None
        if jobs:
            next_run = min(job.next_run for job in jobs).isoformat()
        if scheduler is not None:
            schedule_times = list(getattr(scheduler, "schedule_times", []))
        else:
            try:
                schedule_times = self._current_times()
            except Exception:  # pragma: no cover - defensive status fallback
                schedule_times = []
        running = self._run_lock.locked()
        background_tasks = []
        for entry in getattr(scheduler, "_background_tasks", []) if scheduler else []:
            last_run = float(entry.get("last_run") or 0)
            interval_seconds = int(entry.get("interval_seconds") or 0)
            next_run_at = None
            if last_run > 0 and interval_seconds > 0:
                next_run_at = datetime.fromtimestamp(last_run + interval_seconds).isoformat()
            background_tasks.append({
                "name": entry.get("name"),
                "interval_seconds": interval_seconds,
                "running": bool(entry.get("running", False)),
                "next_run_at": next_run_at,
            })
        return {
            "enabled": self._enabled,
            "mode": self._mode,
            "running": running,
            "schedule_times": schedule_times,
            "next_run_at": next_run,
            "last_run_at": self._last_run_at,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "last_skipped_at": self._last_skipped_at,
            "last_skip_reason": self._last_skip_reason,
            "background_tasks": background_tasks,
        }
