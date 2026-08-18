"""Phase 2B-0: daily screening scheduler behaviour proofs."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

import src.investment.screening_scheduler as sched_mod
from src.investment.screening_scheduler import DailyScreeningScheduler

CN_TZ = ZoneInfo("Asia/Shanghai")
TRADING_DAY = datetime(2026, 8, 18, 15, 5, 0, tzinfo=CN_TZ)  # Tuesday


class _FakeDB:
    def __init__(self, runs=()):
        self._runs = list(runs)

    def list_screening_runs(self, *, limit=20, strategy=None, market=None):
        return self._runs


def _scheduler(tmp_path, *, run_screen, now, db=None):
    return DailyScreeningScheduler(
        state_path=tmp_path / "scheduler_state.json",
        run_screen=run_screen,
        now=lambda: now,
        sleep=lambda _s: None,  # no real sleeps in tests
        db_manager=db if db is not None else _FakeDB(),
    )


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

    def run_screen(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return {"run_id": "run-2", "candidate_count": 2}

    s = _scheduler(tmp_path, run_screen=run_screen, now=TRADING_DAY)
    result = s.tick()

    assert result["status"] == "COMPLETED"
    assert result["attempts"] == 2
    assert len(calls) == 2


def test_all_retries_exhausted_fails_soft(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []

    def run_screen(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("down")

    s = _scheduler(tmp_path, run_screen=run_screen, now=TRADING_DAY)
    result = s.tick()

    assert result["status"] == "FAILED"
    assert result["attempts"] == len(sched_mod.RETRY_DELAYS_SECONDS)
    assert len(calls) == len(sched_mod.RETRY_DELAYS_SECONDS)
    assert "down" in result["last_error"]


def test_failed_day_does_not_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "is_market_open", lambda m, d: True)
    calls = []

    def run_screen(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("down")

    s = _scheduler(tmp_path, run_screen=run_screen, now=TRADING_DAY)
    s.tick()
    second = s.tick()

    assert second["status"] == "SCREENING_FAILED_FOR_DAY"
    assert len(calls) == len(sched_mod.RETRY_DELAYS_SECONDS)  # no extra attempts


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
