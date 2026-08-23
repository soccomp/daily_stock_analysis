# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Decision-time metadata helpers for DSA screening and research inputs."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd


EXCHANGE_TIMEZONE = ZoneInfo("Asia/Shanghai")
SESSION_CLOSE = time(15, 0)
CLOSE_CONFIRMED = "CLOSE_CONFIRMED"
PARTIAL_OR_UNCONFIRMED = "PARTIAL_OR_UNCONFIRMED"
UNKNOWN = "UNKNOWN"


def require_decision_cutoff(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("decision_as_of must be an ISO timestamp") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision_as_of must include a timezone")
    return value


def canonical_utc(value: datetime | str) -> str:
    return require_decision_cutoff(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_trade_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text[:8]):
        try:
            if len(candidate) == 8 and candidate.isdigit():
                return datetime.strptime(candidate, "%Y%m%d").date()
            return date.fromisoformat(candidate[:10])
        except ValueError:
            continue
    return None


def _calendar_contains(calendar: Iterable[Any] | None, day: date) -> bool | None:
    if calendar is None:
        return None
    if callable(calendar):
        try:
            return bool(calendar(day))
        except Exception:
            return False
    try:
        return day in {parsed for value in calendar if (parsed := parse_trade_date(value)) is not None}
    except TypeError:
        return False


def daily_completion(
    trade_date: Any,
    decision_as_of: datetime | str,
    *,
    trading_calendar: Iterable[Any] | None = None,
) -> tuple[str, str]:
    cutoff = require_decision_cutoff(decision_as_of)
    day = parse_trade_date(trade_date)
    if day is None:
        return UNKNOWN, "TRADE_DATE_MISSING_OR_INVALID"
    local = cutoff.astimezone(EXCHANGE_TIMEZONE)
    calendar_status = _calendar_contains(trading_calendar, day)
    if calendar_status is False:
        return UNKNOWN, "NOT_A_CALENDAR_TRADING_DAY"
    if calendar_status is None and day.weekday() >= 5:
        return UNKNOWN, "WEEKEND_CALENDAR_UNKNOWN"
    if day < local.date():
        return CLOSE_CONFIRMED, "PRIOR_PROVIDER_RETURNED_SESSION"
    if day > local.date():
        return UNKNOWN, "FUTURE_TRADE_DATE"
    if local.time() < SESSION_CLOSE:
        return PARTIAL_OR_UNCONFIRMED, "CURRENT_SESSION_NOT_CLOSED"
    return CLOSE_CONFIRMED, "SESSION_CLOSED_AND_ROW_RETURNED"


def annotate_completed_daily_bars(
    frame: pd.DataFrame,
    decision_as_of: datetime | str,
    *,
    trading_calendar: Iterable[Any] | None = None,
) -> pd.DataFrame:
    """Preserve source metadata and remove current partial bars from features."""

    cutoff = require_decision_cutoff(decision_as_of)
    result = frame.copy()
    date_column = next(
        (name for name in ("trade_date", "date", "datetime", "timestamp") if name in result.columns),
        None,
    )
    if date_column is None:
        result["bar_completion_status"] = UNKNOWN
        result["bar_completion_basis"] = "TRADE_DATE_MISSING"
        result["bar_trade_date"] = pd.NaT
        result.attrs.update({
            "decision_cutoff": canonical_utc(cutoff),
            "daily_completion_status": UNKNOWN,
            "latest_completed_trade_date": None,
            "source_time_status": UNKNOWN,
        })
        return result.iloc[0:0].copy()

    statuses = [
        daily_completion(value, cutoff, trading_calendar=trading_calendar)
        for value in result[date_column].tolist()
    ]
    result["bar_trade_date"] = [parse_trade_date(value) for value in result[date_column].tolist()]
    result["bar_completion_status"] = [status for status, _basis in statuses]
    result["bar_completion_basis"] = [basis for _status, basis in statuses]
    result["bar_source_event_time"] = result.get("source_event_time", pd.Series(index=result.index, dtype="object"))
    result["bar_observed_at"] = result.get(
        "observed_at",
        result.get("retrieved_at", pd.Series(index=result.index, dtype="object")),
    )
    if "source_reference" not in result.columns:
        reference = result.attrs.get("source_reference") or result.attrs.get("snapshot_source")
        result["source_reference"] = str(reference or "")

    eligible = result[result["bar_completion_status"] == CLOSE_CONFIRMED].copy()
    completed_dates = [value for value in result["bar_trade_date"].tolist() if value is not None]
    latest = max(
        (value for value, status in zip(result["bar_trade_date"], result["bar_completion_status"])
         if value is not None and status == CLOSE_CONFIRMED),
        default=None,
    )
    excluded = sorted({
        value.isoformat() for value, status in zip(result["bar_trade_date"], result["bar_completion_status"])
        if value is not None and status != CLOSE_CONFIRMED
    })
    source_time_status = "KNOWN" if result["bar_source_event_time"].notna().any() else "TRADE_DATE_ONLY"
    eligible.attrs = dict(result.attrs)
    eligible.attrs.update({
        "decision_cutoff": canonical_utc(cutoff),
        "daily_completion_status": CLOSE_CONFIRMED if latest is not None else UNKNOWN,
        "daily_completion_basis": ";".join(sorted(set(
            basis for status, basis in statuses if status == CLOSE_CONFIRMED
        ))),
        "latest_completed_trade_date": latest.isoformat() if latest is not None else None,
        "excluded_partial_trade_dates": excluded,
        "source_time_status": source_time_status,
        "source_observed_at": result.attrs.get("source_observed_at"),
    })
    return eligible


def actionable_news_for_cutoff(
    items: Iterable[Mapping[str, Any]],
    decision_as_of: datetime | str,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    """Separate news with causal publication time from audit-only records."""

    cutoff = require_decision_cutoff(decision_as_of)
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in items:
        item = dict(raw)
        published = item.get("published_at") or item.get("published_date") or item.get("publication_time")
        try:
            published_at = require_decision_cutoff(published) if published else None
        except ValueError:
            published_at = None
        if published_at is None or published_at > cutoff:
            item["point_in_time_status"] = "EXCLUDED_UNKNOWN_OR_LATER_THAN_CUTOFF"
            excluded.append(item)
            continue
        item["point_in_time_status"] = "ELIGIBLE"
        item["publication_time"] = published_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        included.append(item)
    return tuple(included), tuple(excluded)
