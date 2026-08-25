"""Fail-closed admission and budget rules for natural proposal cycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.core.trading_calendar import MarketPhase, infer_market_phase


@dataclass(frozen=True)
class NaturalCycleAdmission:
    allowed: bool
    reason_code: str
    market_phase: str


def evaluate_natural_cycle_admission(started_at: datetime) -> NaturalCycleAdmission:
    """Admit only an authoritative XSHG regular-session natural start."""

    if started_at.tzinfo is None or started_at.utcoffset() is None:
        return NaturalCycleAdmission(False, "TRADING_CALENDAR_UNAVAILABLE", "UNKNOWN")
    phase = infer_market_phase("cn", current_time=started_at)
    if phase == MarketPhase.NON_TRADING:
        return NaturalCycleAdmission(False, "NON_TRADING_DAY", phase.value)
    if phase not in {MarketPhase.INTRADAY, MarketPhase.CLOSING_AUCTION}:
        reason = "TRADING_CALENDAR_UNAVAILABLE" if phase == MarketPhase.UNKNOWN else "OUTSIDE_TRADING_SESSION"
        return NaturalCycleAdmission(False, reason, phase.value)
    return NaturalCycleAdmission(True, "LEGAL_TRADING_SESSION", phase.value)


@dataclass(frozen=True)
class CycleBudget:
    deadline: datetime
    candidate_reserve_seconds: float

    def remaining_seconds(self, observed_at: datetime) -> float:
        return max(0.0, (self.deadline - observed_at).total_seconds())

    def admits_candidate(self, observed_at: datetime) -> bool:
        return self.remaining_seconds(observed_at) >= self.candidate_reserve_seconds


def build_cycle_budget(
    *, started_at: datetime, config: object, scheduled_for: datetime | None = None
) -> CycleBudget:
    interval_seconds = max(60, int(getattr(config, "single_brain_m2_interval_minutes", 10)) * 60)
    guard_seconds = max(0, int(getattr(config, "single_brain_m2_cycle_guard_seconds", 300)))
    usable_seconds = max(0, interval_seconds - guard_seconds)
    reserve = (
        max(1, int(getattr(config, "generation_backend_timeout_seconds", 300)))
        + max(1.0, float(getattr(config, "single_brain_m2_snapshot_timeout_seconds", 5.0)))
        + max(1.0, float(getattr(config, "single_brain_proposal_timeout_seconds", 5.0)))
    )
    start_deadline = started_at + timedelta(seconds=usable_seconds)
    due_deadline = (scheduled_for or started_at) + timedelta(seconds=usable_seconds)
    return CycleBudget(
        deadline=min(start_deadline, due_deadline),
        candidate_reserve_seconds=reserve,
    )
