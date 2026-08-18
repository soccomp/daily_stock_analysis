"""Screening candidate adapter: feed the latest DSA screening run into the M2 scope.

This is the soccomp Athena integration layer (NOT upstream DSA core).  It reads
candidates that the existing DSA screening engine already persisted in the
``screening_runs`` table and re-exposes them as a research-object source for
Single Brain M2.  It never re-runs screening and never mutates screening state.

Why a thin adapter:
  * Screening is a manual/on-demand engine (API-triggered), while Single Brain
    M2 is a recurring loop.  The gap was that screening candidates were never
    wired into the M2 research scope, so M2 fell back to a static allowlist.
  * This adapter closes that gap with a read-only query + projection, keeping
    the upstream screening engine untouched.

Lineage: each candidate carries ``screening_run_id``, ``strategy``,
``screening_score``, ``rank`` and ``selected_at`` so a research object can be
traced back to the exact screening run that produced it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from data_provider.base import canonical_stock_code, normalize_stock_code

from src.core.trading_calendar import get_market_for_stock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScreeningCandidate:
    """A single screening candidate projected for M2 research scope."""

    symbol: str
    name: str
    screening_run_id: str
    strategy: str
    rank: int | None
    screen_score: float | None
    score: float | None
    selected_at: str

    def as_scope(self) -> dict[str, Any]:
        """Project to the M2 research-object shape with source lineage."""
        return {
            "symbol": self.symbol,
            "source": "SCREENING",
            "screening_run_id": self.screening_run_id,
            "strategy": self.strategy,
            "rank": self.rank,
            "screening_score": self.screen_score,
            "score": self.score,
            "selected_at": self.selected_at,
        }


class ScreeningCandidateSource(Protocol):
    """Read-only projection of the latest screening candidates."""

    def latest(self, *, max_candidates: int, max_age: timedelta) -> list[ScreeningCandidate]:
        """Return up to ``max_candidates`` fresh screening candidates."""


class DatabaseScreeningCandidateSource:
    """Reads the latest completed screening run from the DSA database."""

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    def latest(self, *, max_candidates: int, max_age: timedelta) -> list[ScreeningCandidate]:
        if max_candidates <= 0:
            return []
        runs = self._db.list_screening_runs(limit=1)
        if not runs:
            return []
        latest = runs[0]
        run_id = str(latest.get("run_id") or "")
        if not run_id:
            return []
        detail = self._db.get_screening_run(run_id)
        if not detail:
            return []
        result = detail.get("result") or {}
        candidates = result.get("candidates") or []
        if not isinstance(candidates, list):
            return []

        selected_at = _selected_at(detail)
        if selected_at is None:
            return []
        now = datetime.now(timezone.utc)
        if (now - selected_at) > max_age:
            logger.info(
                "latest screening run %s is older than %s; skipping screening scope",
                run_id, max_age,
            )
            return []

        strategy = str(detail.get("strategy") or "")
        projected: list[ScreeningCandidate] = []
        seen: set[str] = set()
        for item in candidates:
            if not isinstance(item, dict):
                continue
            symbol = _cn_symbol(item.get("code"))
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            projected.append(
                ScreeningCandidate(
                    symbol=symbol,
                    name=str(item.get("name") or ""),
                    screening_run_id=run_id,
                    strategy=strategy,
                    rank=_as_int(item.get("rank")),
                    screen_score=_as_float(item.get("screen_score")),
                    score=_as_float(item.get("score")),
                    selected_at=selected_at.isoformat(),
                )
            )
            if len(projected) >= max_candidates:
                break
        return projected


def _cn_symbol(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        normalized = canonical_stock_code(normalize_stock_code(raw))
    except Exception:
        return None
    if str(get_market_for_stock(normalized) or "").upper() != "CN":
        return None
    return normalized


def _selected_at(detail: dict[str, Any]) -> datetime | None:
    raw = detail.get("created_at")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
