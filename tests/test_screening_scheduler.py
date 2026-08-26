"""Phase 2B-0: daily screening scheduler behaviour proofs."""

from __future__ import annotations

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import pytest

import src.investment.screening_scheduler as sched_mod
from src.investment.screening_scheduler import DailyScreeningScheduler

CN_TZ = ZoneInfo("Asia/Shanghai")
TRADING_DAY = datetime(2026, 8, 18, 14, 50, 0, tzinfo=CN_TZ)  # Tuesday
RETRY_DAY = datetime(2026, 8, 18, 14, 45, 0, tzinfo=CN_TZ)


class _FakeDB:
    def __init__(self, runs=()):
        self._runs = list(runs)

    def list_screening_runs(self, *, limit=20, strategy=None, market=None):
        return self._runs


def _scheduler(tmp_path, *, run_screen, now, db=None):
    return DailyScreeningScheduler(
        state_path=tmp_path / "scheduler_state.json",
        run_screen=run_screen,
        now=now if callable(now) else lambda: now,
        db_manager=db if db is not None else _FakeDB(),
    )


def _run_all_natural_attempts(scheduler, clock):
    results = [scheduler.tick()]
    for delay in sched_mod.RETRY_DELAYS_SECONDS[1:]:
        clock["now"] += timedelta(seconds=delay)
        results.append(scheduler.tick())
    return results


def test_trading_day_after_schedule_runs_screening(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []

    def run_screen(**kwargs):
        calls.append(kwargs)
        return {"run_id": "run-1", "candidate_count": 3}

    s = _scheduler(tmp_path, run_screen=run_screen, now=TRADING_DAY)
    result = s.tick()

    assert result["status"] == "COMPLETED"
    assert result["run_id"] == "run-1"
    assert len(calls) == 1
    assert calls[0]["strategy"] == "capital_heat"


def test_non_trading_day_does_not_trigger(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: False)
    calls = []

    def run_screen(**kwargs):
        calls.append(kwargs)
        return {"run_id": "run-1"}

    s = _scheduler(tmp_path, run_screen=run_screen, now=TRADING_DAY)
    result = s.tick()

    assert result["status"] == "NON_TRADING_DAY"
    assert calls == []


def test_same_day_rerun_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []

    def run_screen(**kwargs):
        calls.append(kwargs)
        return {"run_id": "run-1", "candidate_count": 3}

    s = _scheduler(tmp_path, run_screen=run_screen, now=TRADING_DAY)
    first = s.tick()
    second = s.tick()

    assert first["status"] == "COMPLETED"
    assert second["status"] == "ALREADY_COMPLETED"
    assert second["run_id"] == "run-1"
    assert len(calls) == 1  # screening ran exactly once


def test_retry_after_first_failure_then_success(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []
    clock = {"now": RETRY_DAY}

    def run_screen(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return {"run_id": "run-2", "candidate_count": 2}

    s = _scheduler(tmp_path, run_screen=run_screen, now=lambda: clock["now"])
    first = s.tick()
    clock["now"] += timedelta(seconds=30)
    result = s.tick()

    assert result["status"] == "COMPLETED"
    assert result["attempts"] == 2
    assert first["status"] == "RETRYABLE_FAILED"
    assert first["attempts"] == 1
    assert len(calls) == 2
    assert calls[0]["decision_as_of"] == RETRY_DAY
    assert calls[1]["decision_as_of"] == RETRY_DAY + timedelta(seconds=30)


def test_retry_tick_waits_for_persisted_delay_without_sleep(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []
    clock = {"now": RETRY_DAY}

    def run_screen(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return {"run_id": "run-natural", "candidate_count": 1}

    scheduler = _scheduler(tmp_path, run_screen=run_screen, now=lambda: clock["now"])
    first = scheduler.tick()
    clock["now"] += timedelta(seconds=29)
    not_due = scheduler.tick()
    clock["now"] += timedelta(seconds=1)
    recovered = scheduler.tick()

    assert first["status"] == "RETRYABLE_FAILED"
    assert not_due["status"] == "RETRY_NOT_DUE"
    assert not_due["attempts"] == 1
    assert recovered["status"] == "COMPLETED"
    assert [item["decision_as_of"] for item in calls] == [
        RETRY_DAY,
        RETRY_DAY + timedelta(seconds=30),
    ]


def test_empty_run_id_is_not_reported_as_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []
    clock = {"now": RETRY_DAY}

    def run_screen(**kwargs):
        calls.append(kwargs)
        return {"run_id": "   ", "candidate_count": 3}

    s = _scheduler(tmp_path, run_screen=run_screen, now=lambda: clock["now"])
    results = _run_all_natural_attempts(s, clock)
    result = results[-1]
    locked = s.tick()

    assert result["status"] == "FAILED"
    assert result["attempts"] == len(sched_mod.RETRY_DELAYS_SECONDS)
    assert len(calls) == len(sched_mod.RETRY_DELAYS_SECONDS)
    assert "empty run_id" in result["last_error"]
    assert [item["status"] for item in results[:-1]] == ["RETRYABLE_FAILED"] * (len(results) - 1)
    assert locked["status"] == "SCREENING_FAILED_FOR_DAY"


def test_all_retries_exhausted_fails_soft(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []
    clock = {"now": RETRY_DAY}

    def run_screen(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("down")

    s = _scheduler(tmp_path, run_screen=run_screen, now=lambda: clock["now"])
    results = _run_all_natural_attempts(s, clock)
    result = results[-1]
    locked = s.tick()

    assert result["status"] == "FAILED"
    assert result["attempts"] == len(sched_mod.RETRY_DELAYS_SECONDS)
    assert len(calls) == len(sched_mod.RETRY_DELAYS_SECONDS)
    assert "down" in result["last_error"]
    assert [item["status"] for item in results[:-1]] == ["RETRYABLE_FAILED"] * (len(results) - 1)
    assert locked["status"] == "SCREENING_FAILED_FOR_DAY"


def test_failed_day_self_locks_only_after_bounded_natural_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []
    clock = {"now": RETRY_DAY}

    def run_screen(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("down")

    s = _scheduler(tmp_path, run_screen=run_screen, now=lambda: clock["now"])
    results = _run_all_natural_attempts(s, clock)
    locked = s.tick()

    assert results[-1]["status"] == "FAILED"
    assert locked["status"] == "SCREENING_FAILED_FOR_DAY"
    assert len(calls) == len(sched_mod.RETRY_DELAYS_SECONDS)


def test_retryable_state_survives_scheduler_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []
    clock = {"now": RETRY_DAY}

    def first_run(**kwargs):
        calls.append("first")
        raise RuntimeError("temporary producer outage")

    first_scheduler = _scheduler(tmp_path, run_screen=first_run, now=lambda: clock["now"])
    first = first_scheduler.tick()
    assert first["status"] == "RETRYABLE_FAILED"
    assert first["attempts"] == 1

    def recovered_run(**kwargs):
        calls.append("recovered")
        return {"run_id": "run-after-restart", "candidate_count": 0}

    clock["now"] += timedelta(seconds=30)
    restarted = _scheduler(tmp_path, run_screen=recovered_run, now=lambda: clock["now"])
    recovered = restarted.tick()

    assert recovered["status"] == "COMPLETED"
    assert recovered["run_id"] == "run-after-restart"
    assert recovered["attempts"] == 2
    assert calls == ["first", "recovered"]


def test_crash_recovery_uses_persisted_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []
    db = _FakeDB(runs=[{
        "run_id": "persisted-run",
        "strategy": "capital_heat",
        "market": "cn",
        "created_at": "2026-08-18T07:05:00",  # UTC = 15:05 Beijing
    }])

    def run_screen(**kwargs):
        calls.append(kwargs)
        return {"run_id": "should-not-run"}

    s = _scheduler(tmp_path, run_screen=run_screen, now=TRADING_DAY, db=db)
    result = s.tick()

    assert result["status"] == "ALREADY_COMPLETED"
    assert result["run_id"] == "persisted-run"
    assert result["recovered"] is True
    assert calls == []  # screening not re-run


def test_before_schedule_time_does_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []
    early = TRADING_DAY.replace(hour=14, minute=0)

    def run_screen(**kwargs):
        calls.append(kwargs)
        return {"run_id": "x"}

    s = _scheduler(tmp_path, run_screen=run_screen, now=early)
    result = s.tick()

    assert result["status"] == "BEFORE_SCHEDULE_TIME"
    assert calls == []


def test_after_session_cutoff_does_not_catch_up_screening(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []

    def run_screen(**kwargs):
        calls.append(kwargs)
        return {"run_id": "late"}

    late = TRADING_DAY.replace(hour=15, minute=1)
    s = _scheduler(tmp_path, run_screen=run_screen, now=late)
    result = s.tick()

    assert result["status"] == "AFTER_SESSION_CUTOFF"
    assert result["zero_work"] is True
    assert calls == []
