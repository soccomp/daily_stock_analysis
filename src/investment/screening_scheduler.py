"""Daily autonomous screening scheduler (thin, upstream-friendly trigger).

This is the soccomp integration layer, not the upstream screening engine.  It
turns screening from "manual API only" into "automatic once per trading day".

It never rewrites the screening engine, never changes the ranking algorithm,
and never re-implements candidate enrichment.  It only decides *when* to run
and records the scheduling outcome.

Behaviour:
  * runs on trading days only (real exchange calendar, not just weekday<5);
  * fires once per day, idempotent per (date, strategy, market);
  * a producer attempt fails closed but remains eligible for a bounded later
    natural retry on later scheduler ticks; a valid persisted run is still idempotent;
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
# The producer must run after the official XSHG close.  Running before 15:00
# stamps the current session's incomplete data into the artifact, which the
# proposal consumer correctly rejects as ``CURRENT_SESSION_NOT_CLOSED``.
SCHEDULE_TIME = time(15, 5)
SESSION_CUTOFF_TIME = time(15, 0)
DEFAULT_STRATEGY = "capital_heat"
DEFAULT_MARKET = "cn"
DEFAULT_MAX_RESULTS = 3
DEFAULT_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "screening" / "scheduler_state.json"
# delays applied *between* attempts (attempt 1 fires immediately).
RETRY_DELAYS_SECONDS = (0, 30, 120, 600)
MAX_NATURAL_ATTEMPTS = len(RETRY_DELAYS_SECONDS)


class _ScreeningContractFailure(RuntimeError):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status


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
        strategy: str = DEFAULT_STRATEGY,
        market: str = DEFAULT_MARKET,
        max_results: int = DEFAULT_MAX_RESULTS,
        schedule_time: time = SCHEDULE_TIME,
        session_cutoff_time: time = SESSION_CUTOFF_TIME,
        db_manager: Any | None = None,
    ) -> None:
        self._state_path = Path(state_path)
        self._run_screen = run_screen
        self._now = now or (lambda: datetime.now(CN_TZ))
        self._strategy = strategy
        self._market = market
        self._max_results = max_results
        self._schedule_time = schedule_time
        self._session_cutoff_time = session_cutoff_time
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

        # Keep the old fail-closed behaviour for a caller that explicitly
        # configures a pre-close schedule, while allowing the production
        # 15:05 post-close schedule to run normally.  This makes the temporal
        # contract explicit without introducing a second scheduler path.
        if (
            self._schedule_time <= self._session_cutoff_time
            and now.time() >= self._session_cutoff_time
        ):
            return {
                "status": "AFTER_SESSION_CUTOFF",
                "run_key": run_key,
                "date": today.isoformat(),
                "cutoff_time": self._session_cutoff_time.isoformat(),
                "zero_work": True,
            }

        state = self._load_state()
        existing = state.get("runs", {}).get(run_key)
        if existing and existing.get("status") == "COMPLETED":
            persisted = self._persisted_discovery(existing.get("run_id"), now=now)
            if persisted is None or self._discovery_is_usable(persisted):
                return {"status": "ALREADY_COMPLETED", "run_key": run_key, "run_id": existing.get("run_id")}
            existing = {
                **existing,
                "status": "RETRYABLE_FAILED",
                "retryable": True,
                "failure_kind": persisted.status,
                "last_error": persisted.reason or persisted.status,
                "updated_at": now.isoformat(),
            }
            state.setdefault("runs", {})[run_key] = existing
            self._save_state(state)
        if existing and existing.get("status") in {
            "FAILED", "RETRYABLE_FAILED", "SCREENING_FAILED_FOR_DAY",
        }:
            attempts = int(existing.get("attempts") or 0)
            if attempts >= MAX_NATURAL_ATTEMPTS:
                return {
                    "status": "SCREENING_FAILED_FOR_DAY",
                    "run_key": run_key,
                    "attempts": attempts,
                }

        if existing and existing.get("status") == "RETRYABLE_FAILED":
            attempts = int(existing.get("attempts") or 0)
            retry_at = self._retry_at(existing, attempts=attempts)
            if retry_at is None or now < retry_at:
                return {
                    "status": "RETRY_NOT_DUE",
                    "attempts": attempts,
                    "retryable": True,
                    "last_error": existing.get("last_error"),
                    "updated_at": existing.get("updated_at"),
                    "retry_at": retry_at.isoformat() if retry_at is not None else None,
                }

        # Crash-recovery: if a run was persisted by the screening service but the
        # scheduler state was lost, treat today as already completed.
        prior = self._find_todays_persisted_run(today, now=now)
        if prior is not None:
            state.setdefault("runs", {})[run_key] = {
                "status": "COMPLETED", "run_id": prior, "attempts": 0,
                "updated_at": _utcnow().isoformat(),
            }
            self._save_state(state)
            return {"status": "ALREADY_COMPLETED", "run_key": run_key, "run_id": prior, "recovered": True}

        prior_attempts = int(existing.get("attempts") or 0) if existing else 0
        result = self._run_with_retry(
            run_key,
            prior_attempts=prior_attempts,
            now=now,
        )
        state.setdefault("runs", {})[run_key] = result
        self._save_state(state)
        return {**result, "run_key": run_key}

    def _run_with_retry(
        self,
        run_key: str,
        *,
        prior_attempts: int,
        now: datetime,
    ) -> dict[str, Any]:
        attempt = prior_attempts + 1
        if attempt > MAX_NATURAL_ATTEMPTS:
            return {
                "status": "FAILED",
                "attempts": prior_attempts,
                "retryable": False,
                "last_error": "bounded natural screening attempts exhausted",
                "updated_at": _utcnow().isoformat(),
            }
        last_error: str | None = None
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
            post_call_now = _utcnow()
            persisted = self._persisted_discovery(run_id, now=post_call_now)
            if persisted is not None:
                if not self._discovery_is_usable(persisted):
                    raise _ScreeningContractFailure(
                        persisted.status,
                        persisted.reason or "persisted screening artifact failed discovery contract",
                    )
            else:
                inline_failure = _inline_quality_failure(result)
                if inline_failure:
                    raise _ScreeningContractFailure("DISCOVERY_QUALITY_FAILED", inline_failure)
            return {
                "status": "COMPLETED",
                "run_id": run_id,
                "attempts": attempt,
                "candidate_count": int(result.get("candidate_count") or 0),
                "updated_at": self._now().astimezone(CN_TZ).isoformat(),
            }
        except Exception as exc:  # noqa: BLE001 - bounded natural retry, then fail-soft
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("screening scheduler attempt %s failed: %s", attempt, last_error)
            terminal = attempt >= MAX_NATURAL_ATTEMPTS
            failure_kind = getattr(exc, "status", "PRODUCER_FAILURE")
        return {
            "status": "FAILED" if terminal else "RETRYABLE_FAILED",
            "attempts": attempt,
            "retryable": not terminal,
            "failure_kind": failure_kind,
            "last_error": last_error,
            "updated_at": self._now().astimezone(CN_TZ).isoformat(),
        }

    @staticmethod
    def _retry_at(existing: dict[str, Any], *, attempts: int) -> datetime | None:
        if attempts <= 0 or attempts >= MAX_NATURAL_ATTEMPTS:
            return None
        updated_at = existing.get("updated_at")
        try:
            parsed = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(CN_TZ) + timedelta(seconds=RETRY_DELAYS_SECONDS[attempts])

    def _find_todays_persisted_run(self, today: date, *, now: datetime) -> str | None:
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
                run_id = str(run.get("run_id") or "").strip()
                if not run_id:
                    continue
                persisted = self._persisted_discovery(run_id, now=now)
                if persisted is None or self._discovery_is_usable(persisted):
                    return run_id
        return None

    def _persisted_discovery(self, run_id: Any, *, now: datetime):
        normalized = str(run_id or "").strip()
        if not normalized or not callable(getattr(self._db, "get_screening_run", None)):
            return None
        try:
            from src.investment.m2.screening_candidates import DatabaseScreeningCandidateSource

            return DatabaseScreeningCandidateSource(self._db).latest_result(
                max_candidates=max(1, self._max_results),
                # Canonical rows are accepted by the authoritative completed
                # CN session/PIT contract.  The adapter retains the bounded
                # compatibility rule only for legacy rows without that
                # producer metadata.
                max_age=None,
                now=now,
                strategy=self._strategy,
                market=self._market,
                run_id=normalized,
            )
        except Exception as exc:  # classification is fail-closed for producer state
            logger.warning("screening artifact validation failed: %s", exc)
            from src.investment.m2.screening_candidates import ScreeningDiscoveryResult

            return ScreeningDiscoveryResult(
                "DISCOVERY_UNAVAILABLE",
                reason=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _discovery_is_usable(result: Any) -> bool:
        return getattr(result, "status", None) in {"VALID", "NO_FRESH_CANDIDATES"}

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


def _inline_quality_failure(payload: Any) -> str | None:
    """Validate the producer fields available before a DB read is possible."""

    if not isinstance(payload, dict):
        return "screening producer response is not an object"
    # Keep the producer and consumer on the same quality contract.  A failed
    # LLM ranker is explicitly allowed when the deterministic ``screen_score``
    # fallback produced the candidates; data-source errors remain fatal.
    from src.investment.m2.screening_candidates import screening_quality_failure

    quality_failure = screening_quality_failure(payload)
    if quality_failure:
        return quality_failure
    metadata = any(
        payload.get(key) is not None
        for key in ("latest_completed_trade_date", "decision_cutoff", "completion_status")
    )
    if metadata:
        if payload.get("completion_status") != "CLOSE_CONFIRMED":
            return "screening completion status is not CLOSE_CONFIRMED"
        if not payload.get("latest_completed_trade_date") or not payload.get("decision_cutoff"):
            return "screening causal metadata is incomplete"
    candidates = payload.get("candidates")
    if candidates is not None and not isinstance(candidates, list):
        return "screening candidates payload is not a list"
    if candidates is not None and payload.get("candidate_count") is not None:
        if int(payload.get("candidate_count") or 0) != len(candidates):
            return "screening candidate count does not match persisted payload"
    return None


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
