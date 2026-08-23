from datetime import date, datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from src.core.backtest_engine import BacktestEngine, EvaluationConfig
from src.investment.contracts.data_evidence import actionable_news_evidence, price_plan_evidence
from src.services.screening.daily import compute_daily_features
from src.services.screening.temporal import (
    CLOSE_CONFIRMED,
    UNKNOWN,
    annotate_completed_daily_bars,
)


T = date(2026, 8, 21)
T1 = date(2026, 8, 24)


def _daily_frame():
    rows = []
    for index in range(62):
        day = pd.Timestamp(T) - pd.offsets.BDay(61 - index)
        rows.append({
            "date": day.date().isoformat(),
            "open": 100 + index,
            "high": 101 + index,
            "low": 99 + index,
            "close": 100 + index,
            "volume": 1000,
        })
    rows[-1]["date"] = T.isoformat()
    return pd.DataFrame(rows)


def test_dsa_daily_completion_matrix_and_partial_bar_exclusion():
    cutoffs = {
        datetime(2026, 8, 21, 2, 30, tzinfo=timezone.utc): "2026-08-20",
        datetime(2026, 8, 21, 6, 50, tzinfo=timezone.utc): "2026-08-20",
        datetime(2026, 8, 21, 7, 5, tzinfo=timezone.utc): "2026-08-21",
        datetime(2026, 8, 24, 2, 30, tzinfo=timezone.utc): "2026-08-21",
    }
    for cutoff, expected in cutoffs.items():
        result = annotate_completed_daily_bars(_daily_frame(), cutoff)
        assert result.attrs["latest_completed_trade_date"] == expected
        assert result.attrs["daily_completion_status"] == CLOSE_CONFIRMED
        assert str(result.iloc[-1]["bar_trade_date"])[:10] == expected


def test_weekend_unknown_and_fresh_cache_created_at_does_not_upgrade_source_time():
    weekend = annotate_completed_daily_bars(
        pd.DataFrame([{"date": "2026-08-22", "close": 1}]),
        datetime(2026, 8, 22, 7, 5, tzinfo=timezone.utc),
    )
    assert weekend.empty
    assert weekend.attrs["daily_completion_status"] == UNKNOWN
    holiday = annotate_completed_daily_bars(
        pd.DataFrame([{"date": "2026-08-24", "close": 1}]),
        datetime(2026, 8, 24, 7, 5, tzinfo=timezone.utc),
        trading_calendar={"2026-08-21"},
    )
    assert holiday.empty
    assert holiday.attrs["daily_completion_status"] == UNKNOWN

    cached = annotate_completed_daily_bars(_daily_frame(), datetime(2026, 8, 24, 2, 30, tzinfo=timezone.utc))
    cached.attrs["daily_cache_causal_status"] = UNKNOWN
    with pytest.raises(RuntimeError, match="unknown provider observation time"):
        compute_daily_features(cached)


def test_news_cutoff_excludes_later_and_unknown_publication_time():
    eligible, excluded = actionable_news_evidence(
        items=[
            {"title": "before", "published_at": "2026-08-21T05:00:00+00:00", "retrieved_at": "2026-08-21T06:00:00+00:00"},
            {"title": "after", "published_at": "2026-08-21T07:00:01+00:00"},
            {"title": "unknown", "retrieved_at": "2026-08-21T06:00:00+00:00"},
        ],
        decision_as_of=datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc),
    )
    assert [item["title"] for item in eligible] == ["before"]
    assert {item["title"] for item in excluded} == {"after", "unknown"}


def test_price_plan_evidence_without_provider_event_time_is_explicitly_unknown():
    evidence = price_plan_evidence(context_snapshot={}, source_report_id=31, now=datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc))
    assert evidence.data_class == "PRICE_PLAN"
    assert evidence.source_event_time is None
    assert evidence.freshness_status == "UNKNOWN"
    assert evidence.availability_status == "UNKNOWN"


def test_generic_backtest_enters_on_next_eligible_bar_not_analysis_close():
    bars = [
        SimpleNamespace(date=T1, open=110.0, high=112.0, low=109.0, close=111.0),
        SimpleNamespace(date=date(2026, 8, 25), open=112.0, high=113.0, low=111.0, close=112.0),
    ]
    result = BacktestEngine.evaluate_single_next_eligible_bar(
        operation_advice="买入",
        analysis_date=T,
        forward_bars=bars,
        stop_loss=95.0,
        take_profit=130.0,
        config=EvaluationConfig(eval_window_days=2),
    )
    assert result["eval_status"] == "completed"
    assert result["entry_date"] == T1
    assert result["entry_timing"] == "NEXT_ELIGIBLE_BAR_OPEN"
    assert result["start_price"] == 110.0
    assert result["start_price"] != 100.0
