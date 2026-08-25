"""Daily autonomous screening scheduler (thin, upstream-friendly trigger).

This is the soccomp integration layer, not the upstream screening engine.  It
turns screening from "manual API only" into "automatic once per trading day".

It never rewrites the screening engine, never changes the ranking algorithm,
and never re-implements candidate enrichment.  It only decides *when* to run
and records the scheduling outcome.

Behaviour:
  * runs on trading days only (real exchange calendar, not just weekday<5);
  * fires once per day, idempotent per (date, strategy, market);
  * bounded retry: 0s -> 30s -> 2m -> 10m, then SCREENING_FAILED_FOR_DAY;
  * fail-soft: on failure it never fabricates candidates and never fakes success.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.core.trading_calendar import is_market_open

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
# The producer must become due while the canonical proposal loop is still in
# the legal XSHG session. The screening pipeline uses the latest completed
# prior-session bar when the current session is not closed.
SCHEDULE_TIME = time(14, 45)
DEFAULT_STRATEGY = "capital_heat"
DEFAULT_MARKET = "cn"
DEFAULT_MAX_RESULTS = 3
DEFAULT_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "screening" / "scheduler_state.json"
# delays applied *before* each attempt (attempt 1 fires immediately).
RETRY_DELAYS_SECONDS = (0, 30, 120, 600)


def _utcnow() -> datetime:
    return datetime.now(ZoneInfo("UTC"))


class DailyScreeningScheduler:
    """One-shot per-day trigger for the existing DSA screening service."""

    def __init__(
        self,
        *,
        state_path: Path,
        run_screen: Callable[..., dict[str, Any]],
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        strategy: str = DEFAULT_STRATEGY,
        market: str = DEFAULT_MARKET,
        max_results: int = DEFAULT_MAX_RESULTS,
        schedule_time: time = SCHEDULE_TIME,
        db_manager: Any | None = None,
    ) -> None:
        self._state_path = Path(state_path)
        self._run_screen = run_screen
        self._now = now or (lambda: datetime.now(CN_TZ))
        self._sleep = sleep or _sleep
        self._strategy = strategy
        self._market = market
        self._max_results = max_results
        self._schedule_time = schedule_time
        self._db_manager = db_manager

    def tick(self) -> dict[str, Any]:
        now = self._now().astimezone(CN_TZ)
        today = now.date()
        run_key = f"{today.isoformat()}:{self._strategy}:{self._market}"

        if not is_market_open(self._market, today):
            return {"status": "NON_TRADING_DAY", "run_key": run_key, "date": today.isoformat()}

        if now.time() < self._schedule_time:
            return {
                "status": "BEFORE_SCHEDULE_TIME",
                "run_key": run_key,
                "scheduled_for": self._schedule_time.isoformat(),
            }

        state = self._load_state()
        existing = state.get("runs", {}).get(run_key)
        if existing and existing.get("status") == "COMPLETED":
            return {"status": "ALREADY_COMPLETED", "run_key": run_key, "run_id": existing.get("run_id")}
        if existing and existing.get("status") == "FAILED":
            return {"status": "SCREENING_FAILED_FOR_DAY", "run_key": run_key, "attempts": existing.get("attempts")}

        # Crash-recovery: if a run was persisted by the screening service but the
        # scheduler state was lost, treat today as already completed.
        prior = self._find_todays_persisted_run(today)
        if prior is not None:
            state.setdefault("runs", {})[run_key] = {
                "status": "COMPLETED", "run_id": prior, "attempts": 0,
                "updated_at": _utcnow().isoformat(),
            }
            self._save_state(state)
            return {"status": "ALREADY_COMPLETED", "run_key": run_key, "run_id": prior, "recovered": True}

        result = self._run_with_retry(run_key)
        state.setdefault("runs", {})[run_key] = result
        self._save_state(state)
        return {**result, "run_key": run_key}

    def _run_with_retry(self, run_key: str) -> dict[str, Any]:
        last_error: str | None = None
        for attempt, delay in enumerate(RETRY_DELAYS_SECONDS, start=1):
            if delay:
                self._sleep(delay)
            try:
                result = self._run_screen(
                    strategy=self._strategy,
                    market=self._market,
                    max_results=self._max_results,
                )
                run_id = str(result.get("run_id") or "").strip()
                if not run_id:
                    raise ValueError("screening service returned an empty run_id")
                if result.get("persistence_status") == "PERSISTENCE_FAILED":
                    raise RuntimeError("screening producer persistence failed")
                return {
                    "status": "COMPLETED",
                    "run_id": run_id,
                    "attempts": attempt,
                    "candidate_count": int(result.get("candidate_count") or 0),
                    "updated_at": _utcnow().isoformat(),
                }
            except Exception as exc:  # noqa: BLE001 - bounded retry, then fail-soft
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("screening scheduler attempt %s failed: %s", attempt, last_error)
        return {
            "status": "FAILED",
            "attempts": len(RETRY_DELAYS_SECONDS),
            "last_error": last_error,
            "updated_at": _utcnow().isoformat(),
        }

    def _find_todays_persisted_run(self, today: date) -> str | None:
        """Best-effort crash-recovery: locate a screening run already persisted today."""
        try:
            runs = self._db.list_screening_runs(limit=20, strategy=self._strategy, market=self._market)
        except Exception:  # noqa: BLE001 - crash-recovery is best-effort
            return None
        for run in runs:
            created = run.get("created_at")
            if not created:
                continue
            try:
                dt = datetime.fromisoformat(created)
            except (TypeError, ValueError):
                continue
            if dt.tzinfo is None or dt.utcoffset() is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            local = dt.astimezone(CN_TZ)
            if local.date() == today:
                return str(run.get("run_id") or "")
        return None

    # --- state persistence -------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._state_path)

    @property
    def _db(self):
        if self._db_manager is not None:
            return self._db_manager
        # Lazy import to avoid pulling storage into module import time.
        from src.storage import DatabaseManager

        return DatabaseManager.get_instance()


def _sleep(seconds: float) -> None:
    import time as _time

    _time.sleep(seconds)


def build_scheduler(state_path: Path, *, now: Callable[[], datetime] | None = None) -> DailyScreeningScheduler:
    """Build the production scheduler wired to the real screening service."""
    from src.config import Config
    from src.services.screening_service import ScreeningService
    from src.storage import DatabaseManager

    config = Config.get_instance()
    db = DatabaseManager.get_instance()
    service = ScreeningService(config=config, db_manager=db)
    strategy = (os.getenv("DSA_SCREENING_SCHEDULER_STRATEGY") or DEFAULT_STRATEGY).strip() or DEFAULT_STRATEGY
    market = (os.getenv("DSA_SCREENING_SCHEDULER_MARKET") or DEFAULT_MARKET).strip() or DEFAULT_MARKET
    max_results = int(os.getenv("DSA_SCREENING_SCHEDULER_MAX_RESULTS") or DEFAULT_MAX_RESULTS)

    def run_screen(*, strategy: str, market: str, max_results: int) -> dict[str, Any]:
        return service.screen(strategy=strategy, market=market, max_results=max_results)

    return DailyScreeningScheduler(
        state_path=state_path,
        run_screen=run_screen,
        now=now,
        strategy=strategy,
        market=market,
        max_results=max_results,
    )


def run_due_screening(
    *,
    config: Any,
    db_manager: Any,
    now: datetime,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Run the existing daily screening producer as a scheduler-owned step.

    The returned object is observational.  This helper creates no thread and
    registers no independent task; ``RuntimeSchedulerService`` remains the
    only DSA process-level scheduler authority.
    """

    from src.services.screening_service import ScreeningService

    service = ScreeningService(config=config, db_manager=db_manager)
    strategy = (os.getenv("DSA_SCREENING_SCHEDULER_STRATEGY") or DEFAULT_STRATEGY).strip() or DEFAULT_STRATEGY
    market = (os.getenv("DSA_SCREENING_SCHEDULER_MARKET") or DEFAULT_MARKET).strip() or DEFAULT_MARKET
    max_results = int(os.getenv("DSA_SCREENING_SCHEDULER_MAX_RESULTS") or DEFAULT_MAX_RESULTS)
    scheduler = DailyScreeningScheduler(
        state_path=state_path or DEFAULT_STATE_PATH,
        run_screen=lambda **kwargs: service.screen(**kwargs),
        now=lambda: now,
        strategy=strategy,
        market=market,
        max_results=max_results,
        db_manager=db_manager,
    )
    return scheduler.tick()
