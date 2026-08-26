import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from src.core.backtest_engine import BacktestEngine, EvaluationConfig
from src.investment.contracts.data_evidence import actionable_news_evidence, price_plan_evidence
from src.market_review_contract import build_market_context
from src.services.daily_market_context import DailyMarketContextService
from src.services.screening import candidate_context as candidate_context_module
from src.services.screening import daily as daily_module
from src.services.screening import snapshot as snapshot_module
from src.services.screening.context import build_llm_context
from src.services.screening.daily import compute_daily_features
from src.services.screening.dsa_provider import apply_dsa_provider_context
from src.services.screening.models import Pick
from src.services.screening.temporal import (
    CLOSE_CONFIRMED,
    UNKNOWN,
    authoritative_cn_trading_calendar,
    annotate_completed_daily_bars,
    filter_actionable_context_row,
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


def test_authoritative_cn_calendar_excludes_known_holiday_and_keeps_session():
    days = authoritative_cn_trading_calendar(
        datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc),
    )
    assert date(2026, 10, 1) not in days
    assert date(2026, 10, 8) in days


def test_snapshot_observation_is_captured_after_provider_call_and_late_fetch_fails_closed(monkeypatch):
    cutoff = datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc)
    before = cutoff.replace(hour=6, minute=59)
    after = cutoff.replace(minute=1, hour=8)
    frame = pd.DataFrame([{"code": "000001", "name": "Ping An", "price": 10.0}])
    monkeypatch.setattr(snapshot_module, "fetch_cn_snapshot", lambda _source: frame.copy())

    observed = snapshot_module.fetch_snapshot_with_fallback(
        ["efinance"],
        required_columns=["price"],
        decision_as_of=cutoff,
        clock=lambda: before,
    )
    assert observed.attrs["source_observed_at"] == before.isoformat().replace("+00:00", "Z")
    assert observed.loc[0, "retrieved_at"] == before.isoformat().replace("+00:00", "Z")

    with pytest.raises(RuntimeError, match="after decision cutoff"):
        snapshot_module.fetch_snapshot_with_fallback(
            ["efinance"],
            required_columns=["price"],
            decision_as_of=cutoff,
            clock=lambda: after,
        )


def test_screening_service_pipeline_accepts_post_callback_observation_but_rejects_future_artifact(
    monkeypatch,
    tmp_path,
):
    from src.config import Config
    from src.investment.m2.screening_candidates import (
        DISCOVERY_STALE,
        DISCOVERY_VALID,
        DatabaseScreeningCandidateSource,
    )
    from src.services.screening import pipeline as pipeline_module
    from src.services.screening import temporal as temporal_module
    from src.services.screening.ranker import LLMRankingResult
    from src.services.screening_service import ScreeningService
    from src.storage import DatabaseManager

    callback_start = datetime(2026, 8, 21, 6, 45, tzinfo=timezone.utc)
    provider_observed_value = callback_start + timedelta(seconds=3)

    def _as_frozen_datetime(cls, value, tz):
        return cls(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            tzinfo=tz or value.tzinfo,
        )

    class PipelineClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return _as_frozen_datetime(cls, callback_start, tz)

    class ProviderClock(PipelineClock):
        @classmethod
        def now(cls, tz=None):
            return _as_frozen_datetime(cls, provider_observed_value, tz)

    provider_observed = _as_frozen_datetime(ProviderClock, provider_observed_value, timezone.utc)

    frame = pd.DataFrame([{
        "code": "000001",
        "name": "Ping An",
        "price": 10.0,
        "amount": 100_000_000.0,
        "total_mv": 10_000_000_000.0,
        "pe_ratio": 10.0,
        "pb_ratio": 1.0,
        "change_pct": 0.0,
        "volume_ratio": 1.5,
        "turnover_rate": 2.0,
    }])
    frame.attrs.update({
        "latest_completed_trade_date": "2026-08-20",
        "daily_completion_status": CLOSE_CONFIRMED,
        "daily_completion_basis": "PRIOR_PROVIDER_RETURNED_SESSION",
    })
    annotated_snapshots = []

    monkeypatch.setenv("SCREENING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SNAPSHOT_SOURCE_PRIORITY", "efinance")
    monkeypatch.setenv("SCREENING_SNAPSHOT_CACHE_TTL_SEC", "0")
    monkeypatch.setenv("DAILY_ENRICH_ENABLED", "false")
    monkeypatch.setenv("LITELLM_MODEL", "ollama/deterministic-regression")
    monkeypatch.setattr(
        "src.services.screening_service._get_screening_status_snapshot",
        lambda: ({}, True, None),
    )
    monkeypatch.setattr(
        snapshot_module,
        "fetch_cn_snapshot",
        lambda _source: frame.copy(),
    )
    monkeypatch.setattr(snapshot_module, "datetime", ProviderClock)
    monkeypatch.setattr(temporal_module, "datetime", PipelineClock)
    monkeypatch.setattr(
        snapshot_module,
        "_write_last_good_snapshot",
        lambda _path, annotated, **_kwargs: annotated_snapshots.append(annotated.copy()),
    )
    monkeypatch.setattr(snapshot_module, "_persist_dependency_observation", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline_module, "apply_dsa_provider_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        pipeline_module,
        "rank_candidates_with_metadata",
        lambda candidates, *args, **kwargs: LLMRankingResult(
            picks=candidates,
            ranked=True,
            coverage=1.0,
        ),
    )
    monkeypatch.setattr(
        "src.services.screening_service._enrich_candidates_with_dsa",
        lambda candidates: (
            candidates,
            {"enabled": False, "requested_count": 0, "enriched_count": 0, "warnings": []},
        ),
    )

    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    try:
        response = ScreeningService(
            Config(screening_enabled=True),
            db_manager=db,
        ).screen(strategy="dual_low", market="cn", max_results=1)

        assert response["persistence_status"] == "PERSISTED"
        assert response["decision_cutoff"] == "2026-08-21T06:45:00Z"
        assert annotated_snapshots[-1].attrs["decision_cutoff"] == "2026-08-21T06:45:00Z"
        assert annotated_snapshots[-1].attrs["source_observed_at"] == "2026-08-21T06:45:03Z"
        assert annotated_snapshots[-1].attrs["source_observed_at"] > annotated_snapshots[-1].attrs["decision_cutoff"]

        monkeypatch.setattr(temporal_module, "datetime", datetime)
        source = DatabaseScreeningCandidateSource(db)
        normal = source.latest_result(
            max_candidates=1,
            max_age=None,
            now=provider_observed,
            strategy="dual_low",
            market="cn",
            run_id=response["run_id"],
        )
        assert normal.status == DISCOVERY_VALID, normal.reason

        future_payload = {
            **response,
            "run_id": "future-screening-evidence",
            "decision_cutoff": (provider_observed + timedelta(seconds=5)).isoformat(),
        }
        assert db.save_screening_run(future_payload) == 1
        future = source.latest_result(
            max_candidates=1,
            max_age=None,
            now=provider_observed,
            strategy="dual_low",
            market="cn",
            run_id="future-screening-evidence",
        )
        assert future.status == DISCOVERY_STALE
        assert "future-dated" in future.reason
    finally:
        DatabaseManager.reset_instance()


def test_daily_observation_is_captured_after_provider_call_and_late_fetch_fails_closed(monkeypatch):
    cutoff = datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc)
    after = cutoff.replace(minute=1, hour=8)
    frame = pd.DataFrame([
        {"date": "2026-08-20", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
    ])
    monkeypatch.setattr(daily_module, "_call_daily_wrapper", lambda *args, **kwargs: frame.copy())

    with pytest.raises(RuntimeError, match="after decision cutoff"):
        daily_module.fetch_daily_history(
            "000001",
            source="tencent",
            retries=0,
            decision_as_of=cutoff,
            clock=lambda: after,
        )


def test_actual_candidate_context_and_market_context_drop_unknown_or_later_news():
    cutoff = datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc)
    row = filter_actionable_context_row(
        {
            "code": "000001",
            "news": [
                {"title": "before", "published_at": "2026-08-21T06:00:00+00:00"},
                {"title": "after", "published_at": "2026-08-21T08:00:00+00:00"},
                {"title": "unknown"},
            ],
            "quote": {"price": 10.0},
        },
        cutoff,
    )
    assert [item["title"] for item in row["news"]] == ["before"]
    assert {item["title"] for item in row["news_audit_excluded"]} == {"after", "unknown"}
    prompt = build_llm_context(
        candidate_context_rows=[row],
        candidate_df=pd.DataFrame([{"code": "000001", "name": "Ping An"}]),
        decision_as_of=cutoff,
    )
    assert "before" in prompt
    assert "after" not in prompt
    assert "unknown" not in prompt

    market_context = build_market_context(
        {
            "region": "cn",
            "generated_at": cutoff.isoformat(),
            "news": [
                {"title": "before", "published_at": "2026-08-21T06:00:00+00:00"},
                {"title": "after", "published_at": "2026-08-21T08:00:00+00:00"},
            ],
        },
        task_id="task-pit",
    )
    assert [item["title"] for item in market_context["news"]] == ["before"]
    assert market_context["news_actionability"] == "CUTOFF_FILTERED"
    assert market_context["news_audit_excluded"][0]["title"] == "after"


def test_market_context_components_require_causal_provenance_at_explicit_cutoff():
    cutoff = datetime(2026, 8, 21, 6, 30, tzinfo=timezone.utc)
    evidence = {
        component: {
            "observed_at": datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc).isoformat(),
            "reference": f"provider:{component}",
        }
        for component in ("indices", "breadth", "sectors", "concepts")
    }
    payload = {
        "kind": "market_review",
        "region": "cn",
        "generated_at": cutoff.isoformat(),
        "indices": [{"change_pct": 1.0}],
        "breadth": {
            "up_count": 60,
            "down_count": 30,
            "flat_count": 10,
            "limit_up_count": 6,
            "limit_down_count": 1,
        },
        "sectors": {"top": [{"name": "AI"}], "bottom": []},
        "concepts": {"top": [{"name": "Robotics"}], "bottom": []},
        "data_quality": {
            "indices": "available",
            "breadth": "available",
            "sectors": "available",
            "concepts": "available",
        },
        "component_provenance": evidence,
    }

    validated = build_market_context(payload, task_id="pit-components", as_of=cutoff)
    assert validated["component_timing_status"] == "PIT_VALIDATED"
    assert validated["indices"]
    assert validated["breadth"]
    assert validated["sector_strength"]["top"]
    assert validated["concepts"]["top"]

    late = dict(payload)
    late["component_provenance"] = {
        **evidence,
        "sectors": {
            "observed_at": "2026-08-21T07:05:00+00:00",
            "reference": "provider:sectors-late",
        },
    }
    filtered = build_market_context(late, task_id="pit-components-late", as_of=cutoff)
    assert filtered["sector_strength"] == {}
    assert filtered["component_provenance"]["sectors"]["status"] == "LATER_THAN_CUTOFF_EXCLUDED"
    assert filtered["market_strength"]["components"]["indices"] is not None

    unknown = dict(payload)
    unknown.pop("component_provenance")
    excluded = build_market_context(unknown, task_id="pit-components-unknown", as_of=cutoff)
    assert excluded["component_timing_status"] == "UNKNOWN_EXCLUDED"
    assert excluded["indices"] == []
    assert excluded["breadth"] is None
    assert excluded["sector_strength"] == {}


def test_same_day_market_review_pit_lookup_rejects_later_record_and_uses_earlier_record():
    cutoff = datetime(2026, 8, 21, 6, 30, tzinfo=timezone.utc)

    def record(created_at, summary):
        payload = {
            "kind": "market_review",
            "region": "cn",
            "date": "2026-08-21",
            "sections": [{"key": "overview", "markdown": summary}],
            "markdown_report": summary,
        }
        snapshot = {
            "report_kind": "market_review",
            "market_review_region": "cn",
            "market_review_payload": payload,
            "report_language": "zh",
        }
        return SimpleNamespace(
            id=created_at.minute,
            query_id="pit-review",
            report_type="market_review",
            analysis_summary=summary,
            news_content=summary,
            raw_result=json.dumps({"raw_response": summary}),
            context_snapshot=json.dumps(snapshot),
            created_at=created_at,
        )

    class HistoryDb:
        def get_analysis_history(self, **_kwargs):
            return [
                record(
                    datetime(2026, 8, 21, 7, 5, tzinfo=timezone.utc),
                    "15:05 review must not enter the 14:30 decision.",
                ),
                record(
                    datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc),
                    "06:00 review is causal for the 06:30 decision.",
                ),
            ]

    context = DailyMarketContextService(
        db_manager=HistoryDb(),
        today_fn=lambda: date(2026, 8, 21),
    ).get_context(
        region="cn",
        config=SimpleNamespace(report_language="zh"),
        notifier=SimpleNamespace(),
        analyzer=None,
        search_service=None,
        allow_generate=False,
        decision_as_of=cutoff,
    )

    assert context is not None
    assert context.summary == "06:00 review is causal for the 06:30 decision."
    assert "15:05" not in context.summary
    assert context.created_at == datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)

    service = DailyMarketContextService(
        db_manager=HistoryDb(),
        today_fn=lambda: date(2026, 8, 21),
    )
    assert service._build_context_from_payload(
        region="cn",
        trade_date=date(2026, 8, 21),
        payload={
            "summary": "payload evidence is later",
            "generated_at": "2026-08-21T07:05:00+00:00",
        },
        source="market_review_runtime",
        created_at=datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc),
        decision_as_of=cutoff,
    ) is None
    assert service._build_context_from_payload(
        region="cn",
        trade_date=date(2026, 8, 21),
        payload={"summary": "no causal evidence"},
        source="market_review_runtime",
        decision_as_of=cutoff,
    ) is None


def test_actual_dsa_provider_and_collector_paths_keep_news_audit_only(monkeypatch):
    cutoff = datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc)
    pick = Pick(rank=1, code="000001", name="Ping An", final_score=90.0, screen_score=90.0)
    notes = apply_dsa_provider_context(
        [pick],
        {
            "dsa": {
                "get_candidate_context": lambda *_args: {
                    "quote": {"price": 10.0},
                    "news": [
                        {"title": "before", "published_at": "2026-08-21T06:00:00+00:00"},
                        {"title": "after", "published_at": "2026-08-21T08:00:00+00:00"},
                    ],
                },
            },
        },
        decision_as_of=cutoff,
    )
    assert notes == ["DSA provider context applied 1 of 1 candidates"]
    assert [item["title"] for item in pick.dsa_news] == ["before"]
    assert pick.dsa_context["news_audit_excluded"][0]["title"] == "after"

    monkeypatch.setattr(
        candidate_context_module,
        "fetch_stock_news_summary",
        lambda *_args, **_kwargs: "provider text without publication timestamp",
    )
    rows, errors = candidate_context_module.collect_candidate_context(
        pd.DataFrame([{"code": "000001", "name": "Ping An"}]),
        providers=["news"],
        decision_as_of=cutoff,
    )
    assert not errors
    assert rows[0].get("news") is None
    assert rows[0]["news_audit_excluded"][0]["point_in_time_status"] == "EXCLUDED_UNKNOWN_OR_LATER_THAN_CUTOFF"


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


def test_price_plan_evidence_ignores_unrelated_nested_event_and_accepts_dedicated_lineage():
    now = datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc)
    unrelated = price_plan_evidence(
        context_snapshot={
            "market_event": {
                "source_event_time": now,
                "provider": "unrelated",
                "reference": "unrelated-ref",
            },
        },
        source_report_id=32,
        now=now,
    )
    assert unrelated.source_event_time is None
    assert unrelated.availability_status == "UNKNOWN"

    dedicated = price_plan_evidence(
        context_snapshot={
            "price_plan": {
                "source_event_time": now,
                "retrieved_at": now,
                "provider": "quote-provider",
                "source_reference": "quote:000001",
                "completion_status": "CLOSE_CONFIRMED",
            },
        },
        source_report_id=33,
        now=now,
    )
    assert dedicated.source_event_time == now
    assert dedicated.availability_status == "AVAILABLE"


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


def test_missing_open_fallback_does_not_evaluate_same_bar_targets():
    bars = [
        SimpleNamespace(date=T1, open=None, high=150.0, low=99.0, close=100.0),
        SimpleNamespace(date=date(2026, 8, 25), open=100.0, high=101.0, low=99.0, close=100.5),
    ]
    result = BacktestEngine.evaluate_single_next_eligible_bar(
        operation_advice="买入",
        analysis_date=T,
        forward_bars=bars,
        stop_loss=80.0,
        take_profit=120.0,
        config=EvaluationConfig(eval_window_days=2),
    )
    assert result["entry_timing"] == "NEXT_ELIGIBLE_BAR_CLOSE_FALLBACK"
    assert result["hit_take_profit"] is False
    assert result["first_hit"] == "neither"
