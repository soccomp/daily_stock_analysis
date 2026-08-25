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

DISCOVERY_VALID = "VALID"
DISCOVERY_NO_FRESH_CANDIDATES = "NO_FRESH_CANDIDATES"
DISCOVERY_MISSING = "DISCOVERY_MISSING"
DISCOVERY_STALE = "DISCOVERY_STALE"
DISCOVERY_FAILED = "DISCOVERY_FAILED"
DISCOVERY_QUALITY_FAILED = "DISCOVERY_QUALITY_FAILED"
DISCOVERY_UNAVAILABLE = "DISCOVERY_UNAVAILABLE"


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
    latest_completed_trade_date: str | None = None
    decision_cutoff: str | None = None
    completion_status: str | None = None
    completion_basis: str | None = None
    quantitative_input_reference: str | None = None
    intraday_prefilter_observed_at: str | None = None
    intraday_prefilter_reference: str | None = None
    evidence_hash: str | None = None
    strategy_evidence: dict[str, Any] | None = None

    def as_scope(self) -> dict[str, Any]:
        """Project to the M2 research-object shape with source lineage."""
        scope = {
            "symbol": self.symbol,
            "source": "SCREENING",
            "screening_run_id": self.screening_run_id,
            "strategy": self.strategy,
            "rank": self.rank,
            "screening_score": self.screen_score,
            "score": self.score,
            "selected_at": self.selected_at,
        }
        for key in (
            "latest_completed_trade_date", "decision_cutoff", "completion_status",
            "completion_basis", "quantitative_input_reference",
            "intraday_prefilter_observed_at", "intraday_prefilter_reference", "evidence_hash",
        ):
            value = getattr(self, key)
            if value is not None:
                scope[key] = value
        if self.strategy_evidence is not None:
            scope["strategy_evidence"] = dict(self.strategy_evidence)
        return scope


@dataclass(frozen=True)
class ScreeningDiscoveryResult:
    """Read-only producer outcome, separate from candidate selection."""

    status: str
    candidates: tuple[ScreeningCandidate, ...] = ()
    reason: str = ""
    run_id: str | None = None
    latest_completed_trade_date: str | None = None
    decision_cutoff: str | None = None


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
            candidate = _project_candidate(
                run_id=run_id,
                item=item,
                selected_at=selected_at,
                strategy=strategy,
            )
            if candidate is None or candidate.symbol in seen:
                continue
            seen.add(candidate.symbol)
            projected.append(candidate)
            if len(projected) >= max_candidates:
                break
        return projected

    def latest_result(
        self,
        *,
        max_candidates: int,
        max_age: timedelta,
        now: datetime | None = None,
        strategy: str | None = None,
        market: str | None = None,
    ) -> ScreeningDiscoveryResult:
        """Resolve the authoritative completed screening artifact.

        Freshness follows the producer's completed-trade date and causal
        decision cutoff.  ``created_at`` remains lineage metadata only and is
        never the acceptance clock for a proposal cycle.
        """

        if max_candidates <= 0:
            return ScreeningDiscoveryResult(DISCOVERY_NO_FRESH_CANDIDATES)
        observed_at = now or datetime.now(timezone.utc)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return ScreeningDiscoveryResult(DISCOVERY_UNAVAILABLE, reason="discovery clock must be timezone-aware")
        try:
            runs = self._db.list_screening_runs(
                limit=20,
                strategy=strategy or None,
                market=market or None,
            )
        except Exception as exc:  # read-only adapter: classify, never rerun
            return ScreeningDiscoveryResult(
                DISCOVERY_UNAVAILABLE,
                reason=f"{type(exc).__name__}: {exc}",
            )
        if not runs:
            return ScreeningDiscoveryResult(DISCOVERY_MISSING, reason="no persisted screening run matched scope")

        latest = runs[0]
        run_id = str(latest.get("run_id") or "").strip()
        if not run_id:
            return ScreeningDiscoveryResult(DISCOVERY_QUALITY_FAILED, reason="persisted screening run has no run_id")
        try:
            detail = self._db.get_screening_run(run_id)
        except Exception as exc:
            return ScreeningDiscoveryResult(DISCOVERY_UNAVAILABLE, run_id=run_id, reason=f"{type(exc).__name__}: {exc}")
        if not detail:
            return ScreeningDiscoveryResult(DISCOVERY_MISSING, run_id=run_id, reason="screening detail is absent")

        result = detail.get("result") if isinstance(detail.get("result"), dict) else {}
        merged = {**detail, **result}
        actual_strategy = str(detail.get("strategy") or result.get("strategy") or "").strip()
        actual_market = str(detail.get("market") or result.get("market") or "").strip()
        if strategy and actual_strategy != str(strategy).strip():
            return ScreeningDiscoveryResult(DISCOVERY_QUALITY_FAILED, run_id=run_id, reason="screening strategy identity mismatch")
        if market and actual_market != str(market).strip():
            return ScreeningDiscoveryResult(DISCOVERY_QUALITY_FAILED, run_id=run_id, reason="screening market identity mismatch")

        completion_status = _as_text(merged.get("completion_status"))
        producer_status = _as_text(
            merged.get("status")
            or merged.get("run_status")
            or merged.get("producer_status")
        )
        if completion_status in {"FAILED", "ERROR", "SCREENING_FAILED_FOR_DAY"} or producer_status in {
            "FAILED",
            "ERROR",
            "SCREENING_FAILED_FOR_DAY",
        }:
            return ScreeningDiscoveryResult(
                DISCOVERY_FAILED,
                run_id=run_id,
                reason="screening producer recorded a failed terminal status",
            )

        latest_trade_date = _as_text(
            merged.get("latest_completed_trade_date")
            or merged.get("daily_latest_completed_trade_date")
        )
        decision_cutoff = _as_text(merged.get("decision_cutoff"))
        legacy_unverified = False
        if not latest_trade_date or not decision_cutoff or completion_status not in {"CLOSE_CONFIRMED", "COMPLETED"}:
            if latest_trade_date or decision_cutoff or completion_status:
                return ScreeningDiscoveryResult(
                    DISCOVERY_QUALITY_FAILED,
                    run_id=run_id,
                    reason="screening run lacks completed-trade-date/cutoff/completion contract",
                    latest_completed_trade_date=latest_trade_date,
                    decision_cutoff=decision_cutoff,
                )
            legacy_cutoff = _selected_at(detail)
            if legacy_cutoff is None:
                return ScreeningDiscoveryResult(
                    DISCOVERY_QUALITY_FAILED,
                    run_id=run_id,
                    reason="screening run lacks completed-trade-date/cutoff/completion contract",
                    latest_completed_trade_date=latest_trade_date,
                    decision_cutoff=decision_cutoff,
                )
            latest_trade_date = legacy_cutoff.date().isoformat()
            decision_cutoff = legacy_cutoff.isoformat()
            completion_status = "LEGACY_UNVERIFIED"
            legacy_unverified = True
        try:
            completed_date = datetime.fromisoformat(latest_trade_date).date() if "T" in latest_trade_date else datetime.strptime(latest_trade_date, "%Y-%m-%d").date()
            cutoff = _parse_timestamp(decision_cutoff)
        except (TypeError, ValueError):
            return ScreeningDiscoveryResult(DISCOVERY_QUALITY_FAILED, run_id=run_id, reason="screening causal metadata is invalid")
        observed_utc = observed_at.astimezone(timezone.utc)
        future_tolerance = timedelta(seconds=2)
        if cutoff is None or (
            not legacy_unverified
            and cutoff - observed_utc > future_tolerance
        ):
            return ScreeningDiscoveryResult(DISCOVERY_STALE, run_id=run_id, reason="screening decision cutoff is future-dated", latest_completed_trade_date=latest_trade_date, decision_cutoff=decision_cutoff)
        if not legacy_unverified and completed_date > observed_utc.date():
            return ScreeningDiscoveryResult(DISCOVERY_QUALITY_FAILED, run_id=run_id, reason="latest completed trade date is future-dated", latest_completed_trade_date=latest_trade_date, decision_cutoff=decision_cutoff)
        if observed_at.astimezone(timezone.utc) - cutoff > max_age:
            return ScreeningDiscoveryResult(DISCOVERY_STALE, run_id=run_id, reason="screening decision cutoff is outside the cycle freshness window", latest_completed_trade_date=latest_trade_date, decision_cutoff=decision_cutoff)
        quality_reason = _screening_quality_failure(merged)
        if quality_reason:
            return ScreeningDiscoveryResult(DISCOVERY_QUALITY_FAILED, run_id=run_id, reason=quality_reason, latest_completed_trade_date=latest_trade_date, decision_cutoff=decision_cutoff)

        candidates = result.get("candidates") or []
        if not isinstance(candidates, list):
            return ScreeningDiscoveryResult(DISCOVERY_QUALITY_FAILED, run_id=run_id, reason="screening candidates payload is not a list", latest_completed_trade_date=latest_trade_date, decision_cutoff=decision_cutoff)
        selected_at = _selected_at(detail) or cutoff
        projected: list[ScreeningCandidate] = []
        seen: set[str] = set()
        for item in candidates:
            candidate = _project_candidate(
                run_id=run_id,
                item=item,
                selected_at=selected_at,
                strategy=actual_strategy,
            )
            if candidate is None or candidate.symbol in seen:
                continue
            seen.add(candidate.symbol)
            projected.append(candidate)
            if len(projected) >= max_candidates:
                break
        declared_count = merged.get("candidate_count")
        if declared_count is None and legacy_unverified:
            declared_count = len(candidates)
        declared_count = int(declared_count or 0)
        if declared_count != len(candidates):
            return ScreeningDiscoveryResult(DISCOVERY_QUALITY_FAILED, run_id=run_id, reason="screening candidate count does not match persisted payload", latest_completed_trade_date=latest_trade_date, decision_cutoff=decision_cutoff)
        if not projected:
            return ScreeningDiscoveryResult(DISCOVERY_NO_FRESH_CANDIDATES, run_id=run_id, latest_completed_trade_date=latest_trade_date, decision_cutoff=decision_cutoff)
        return ScreeningDiscoveryResult(
            DISCOVERY_VALID,
            tuple(projected),
            reason="LEGACY_UNVERIFIED" if legacy_unverified else "",
            run_id=run_id,
            latest_completed_trade_date=latest_trade_date,
            decision_cutoff=decision_cutoff,
        )

    def by_run(self, *, screening_run_id: str, symbol: str) -> ScreeningCandidate | None:
        """Recover one candidate from the run named by a durable trigger."""

        run_id = str(screening_run_id or "").strip()
        target_symbol = _cn_symbol(symbol)
        if not run_id or not target_symbol:
            return None
        detail = self._db.get_screening_run(run_id)
        if not detail:
            return None
        selected_at = _selected_at(detail)
        if selected_at is None:
            return None
        strategy = str(detail.get("strategy") or "")
        result = detail.get("result") or {}
        candidates = result.get("candidates") or []
        if not isinstance(candidates, list):
            return None
        for item in candidates:
            candidate = _project_candidate(
                run_id=run_id,
                item=item,
                selected_at=selected_at,
                strategy=strategy,
            )
            if candidate is not None and candidate.symbol == target_symbol:
                return candidate
        return None


def _project_candidate(
    *,
    run_id: str,
    item: Any,
    selected_at: datetime,
    strategy: str,
) -> ScreeningCandidate | None:
    if not isinstance(item, dict):
        return None
    symbol = _cn_symbol(item.get("code"))
    if not symbol:
        return None
    return ScreeningCandidate(
        symbol=symbol,
        name=str(item.get("name") or ""),
        screening_run_id=run_id,
        strategy=strategy,
        rank=_as_int(item.get("rank")),
        screen_score=_as_float(item.get("screen_score")),
        score=_as_float(item.get("score")),
        selected_at=selected_at.isoformat(),
        latest_completed_trade_date=_as_text(item.get("latest_completed_trade_date")),
        decision_cutoff=_as_text(item.get("decision_cutoff")),
        completion_status=_as_text(item.get("completion_status")),
        completion_basis=_as_text(item.get("completion_basis")),
        quantitative_input_reference=_as_text(item.get("quantitative_input_reference")),
        intraday_prefilter_observed_at=_as_text(item.get("intraday_prefilter_observed_at")),
        intraday_prefilter_reference=_as_text(item.get("intraday_prefilter_reference")),
        evidence_hash=_as_text(item.get("evidence_hash")),
        strategy_evidence=(
            dict(item["strategy_evidence"])
            if isinstance(item.get("strategy_evidence"), dict)
            else None
        ),
    )


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


def _as_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


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


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _screening_quality_failure(payload: dict[str, Any]) -> str | None:
    for key in ("source_errors", "warnings"):
        values = payload.get(key) or []
        if values:
            return f"screening {key} are present"
    for value in payload.get("degradation") or ():
        text = str(value).lower()
        if any(token in text for token in ("failed", "fallback", "error", "unknown", "stale")):
            return "screening quality is degraded: " + str(value)
    return None


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
