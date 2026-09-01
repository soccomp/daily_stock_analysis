from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.investment.rule_decision import RULE_MODEL_ID, build_rule_analysis_result
from src.investment.m2.orchestration import DSAAnalysisCompletionRunner
from src.investment.proposal.builder import InvestmentProposalBuilder
from src.core.pipeline import StockAnalysisPipeline
from src.storage import DatabaseManager
from tests.test_investment_shadow_wiring_p1a import _snapshot
from src.stock_analyzer import BuySignal, TrendAnalysisResult, TrendStatus


def _trend(score: int, signal: BuySignal) -> TrendAnalysisResult:
    return TrendAnalysisResult(
        code="600519",
        trend_status=TrendStatus.BULL if score >= 60 else TrendStatus.BEAR,
        signal_score=score,
        buy_signal=signal,
        current_price=100.0,
        ma5=98.0,
        ma10=95.0,
        ma20=90.0,
        support_levels=[90.0, 95.0],
        resistance_levels=[120.0],
        signal_reasons=["趋势与量价规则确认"],
        risk_factors=["跌破支撑则失效"],
    )


def _build(
    trend: TrendAnalysisResult | None,
    *,
    has_position: bool = False,
    current_weight: Decimal | None = None,
    simulation_relaxed: bool = False,
    position_avg_cost: Decimal | None = None,
    change_60d: float | None = None,
):
    realtime = {"price": 100.0}
    if change_60d is not None:
        realtime["change_60d"] = change_60d
    return build_rule_analysis_result(
        code="600519",
        name="贵州茅台",
        trend_result=trend,
        enhanced_context={"today": {"close": 100.0}, "realtime": realtime},
        decision_context={
            "candidate_source": "HOLDING" if has_position else "SCREENING",
            "has_position": has_position,
            "current_weight": current_weight,
            "position_avg_cost": position_avg_cost,
            "simulation_relaxed": simulation_relaxed,
        },
        report_language="zh",
    )


def test_screening_candidate_buy_is_rule_authoritative_and_has_price_plan():
    result = _build(_trend(76, BuySignal.BUY))

    assert result.action == "buy"
    assert result.decision_type == "buy"
    assert result.model_used == RULE_MODEL_ID
    assert result.search_performed is False
    assert result.dashboard["rule_decision"]["ai_used_for_action"] is False
    assert result.dashboard["battle_plan"]["sniper_points"] == {
        "ideal_buy": 98.0,
        "secondary_buy": 100.0,
        "stop_loss": 90.0,
        "take_profit": 120.0,
    }


@pytest.mark.parametrize(
    ("score", "expected"),
    ((30, "reduce"), (10, "sell")),
)
def test_holding_uses_canonical_negative_score_bands(score, expected):
    result = _build(
        _trend(score, BuySignal.SELL),
        has_position=True,
        current_weight=Decimal("0.120000"),
    )

    assert result.action == expected
    assert result.decision_type == "sell"
    if expected == "reduce":
        assert (
            result.dashboard["battle_plan"]["position_strategy"]["suggested_position"]
            == "6.000000%"
        )


def test_non_holding_negative_signal_never_creates_a_sell_order_advice():
    result = _build(_trend(10, BuySignal.STRONG_SELL))

    assert result.action == "watch"
    assert result.decision_type == "hold"
    assert "空仓状态" in result.dashboard["decision_stability"]["reason"]


def test_missing_trend_fails_closed_without_ai():
    result = _build(None, has_position=False)

    assert result.action == "watch"
    assert result.confidence_level == "低"
    assert result.model_used == RULE_MODEL_ID


def test_buy_without_a_verifiable_target_is_downgraded_to_watch():
    trend = _trend(76, BuySignal.BUY)
    trend.resistance_levels = []

    result = _build(trend)

    assert result.action == "watch"
    assert result.dashboard["battle_plan"]["sniper_points"] == {}
    assert "缺少可验证" in result.dashboard["decision_stability"]["reason"]


def test_explicitly_stale_realtime_quote_cannot_authorize_a_buy():
    result = build_rule_analysis_result(
        code="600519",
        name="贵州茅台",
        trend_result=_trend(76, BuySignal.BUY),
        enhanced_context={
            "today": {"close": 100.0},
            "realtime": {"price": 100.0, "is_stale": True},
        },
        decision_context={"candidate_source": "SCREENING", "has_position": False},
    )

    assert result.action == "watch"
    assert result.dashboard["battle_plan"]["sniper_points"] == {}


def test_simulation_relaxed_profile_emits_buy_with_deterministic_fallback_plan():
    trend = _trend(68, BuySignal.WAIT)
    trend.resistance_levels = []

    result = _build(trend, simulation_relaxed=True)

    assert result.action == "buy"
    assert result.dashboard["rule_decision"]["profile"] == "SIMULATION_RELAXED_V1"
    assert result.dashboard["rule_decision"]["fallback_price_plan"] is True
    assert result.dashboard["battle_plan"]["sniper_points"] == {
        "ideal_buy": 99.5,
        "secondary_buy": 100.0,
        "stop_loss": 97.0,
        "take_profit": 105.0,
    }
    assert "固定价格兜底" in result.dashboard["decision_stability"]["reason"]


def test_simulation_relaxed_profile_still_blocks_buy_for_a_bear_trend():
    trend = _trend(68, BuySignal.WAIT)
    trend.trend_status = TrendStatus.BEAR

    result = _build(trend, simulation_relaxed=True)

    assert result.action == "watch"


@pytest.mark.parametrize(
    ("average_cost", "expected_action", "reason"),
    (
        (Decimal("120"), "sell", "止损阈值"),
        (Decimal("80"), "sell", "止盈阈值"),
    ),
)
def test_simulation_relaxed_profile_applies_cost_based_exit_rules(
    average_cost, expected_action, reason
):
    result = _build(
        _trend(68, BuySignal.WAIT),
        has_position=True,
        current_weight=Decimal("0.120000"),
        position_avg_cost=average_cost,
        simulation_relaxed=True,
    )

    assert result.action == expected_action
    assert reason in result.dashboard["decision_stability"]["reason"]
    assert result.dashboard["rule_decision"]["exit_rules"]["trigger"]


def test_simulation_relaxed_profile_reduces_on_negative_momentum_and_weak_trend():
    trend = _trend(68, BuySignal.WAIT)
    trend.trend_status = TrendStatus.WEAK_BEAR

    result = _build(
        trend,
        has_position=True,
        current_weight=Decimal("0.120000"),
        position_avg_cost=Decimal("100"),
        change_60d=-4.0,
        simulation_relaxed=True,
    )

    assert result.action == "reduce"
    assert "动量为负" in result.dashboard["decision_stability"]["reason"]


def test_strict_profile_does_not_apply_simulation_exit_override():
    result = _build(
        _trend(68, BuySignal.WAIT),
        has_position=True,
        current_weight=Decimal("0.120000"),
        position_avg_cost=Decimal("120"),
        simulation_relaxed=False,
    )

    assert result.action == "hold"


def test_simulation_relaxed_buy_carries_athena_strategy_evidence():
    now = datetime.now(timezone.utc)
    proposal = InvestmentProposalBuilder(clock=lambda: now).build(
        result=_build(_trend(68, BuySignal.WAIT), simulation_relaxed=True),
        context_snapshot={},
        source_report_id=103,
        cycle_id="cycle-rule-relaxed-buy",
        trigger_source="test",
    ).proposal

    assert proposal.strategy_evidence is not None
    assert proposal.strategy_evidence.ranking_score == Decimal("0.680000")
    assert proposal.strategy_evidence.completion_basis == "RULES_SIMULATION_RELAXED_TREND_SCORE"


def test_same_structured_inputs_produce_the_same_decision_payload():
    first = _build(_trend(76, BuySignal.BUY)).to_dict()
    second = _build(_trend(76, BuySignal.BUY)).to_dict()

    assert first == second


def test_rule_buy_and_reduce_keep_the_existing_advisory_proposal_contract():
    now = datetime.now(timezone.utc)
    buy = InvestmentProposalBuilder(clock=lambda: now).build(
        result=_build(_trend(76, BuySignal.BUY)),
        context_snapshot={},
        source_report_id=101,
        cycle_id="cycle-rule-buy",
        trigger_source="test",
    ).proposal
    reduce = InvestmentProposalBuilder(clock=lambda: now).build(
        result=_build(
            _trend(30, BuySignal.SELL),
            has_position=True,
            current_weight=Decimal("0.030000"),
        ),
        context_snapshot={},
        source_report_id=102,
        cycle_id="cycle-rule-reduce",
        trigger_source="test",
        authoritative_snapshot=_snapshot(as_of=now),
    ).proposal

    assert buy.action == "BUY"
    assert buy.execution_permitted is False
    assert reduce.action == "REDUCE"
    assert reduce.suggested_target_weight == Decimal("0.015000")
    assert reduce.execution_permitted is False


def test_rule_pipeline_does_not_construct_ai_or_news_services():
    config = SimpleNamespace(
        max_workers=1,
        save_context_snapshot=True,
        enable_realtime_quote=True,
        enable_chip_distribution=False,
        realtime_source_priority=[],
    )
    with (
        patch("src.core.pipeline.get_db"),
        patch("src.core.pipeline.DataFetcherManager"),
        patch("src.core.pipeline.GeminiAnalyzer") as analyzer,
        patch("src.core.pipeline.SearchService") as search,
        patch("src.core.pipeline.NotificationService"),
        patch("src.core.pipeline.MarketStructureService"),
        patch("src.core.pipeline.MarketHotspotService"),
    ):
        pipeline = StockAnalysisPipeline(config=config, decision_mode="rules")

    assert pipeline.analyzer is None
    assert pipeline.search_service is None
    analyzer.assert_not_called()
    search.assert_not_called()


def test_proposal_runner_persists_and_recovers_only_rule_decisions(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'rule-runner.sqlite'}")
    factory_kwargs = []

    def factory(**kwargs):
        factory_kwargs.append(kwargs)

        class Pipeline:
            def process_single_stock(self, symbol, **process_kwargs):
                result = _build(_trend(76, BuySignal.BUY))
                result.code = symbol
                source_id = db.save_analysis_history(
                    result=result,
                    query_id=process_kwargs["analysis_query_id"],
                    report_type="simple",
                    news_content=None,
                    context_snapshot={"data_quality": {"level": "good"}},
                    save_snapshot=True,
                )
                assert source_id > 0
                return result

        return Pipeline()

    try:
        runner = DSAAnalysisCompletionRunner(
            config=object(),
            db_manager=db,
            pipeline_factory=factory,
            decision_mode="rules",
        )
        now = datetime.now(timezone.utc)
        first = runner.complete(
            cycle_id="cycle-rules",
            symbol="600519",
            query_id="query-rules",
            current_time=now,
            decision_context={"candidate_source": "SCREENING", "has_position": False},
        )
        recovered = runner.complete(
            cycle_id="cycle-rules",
            symbol="600519",
            query_id="query-rules",
            current_time=now,
        )
    finally:
        DatabaseManager.reset_instance()

    assert factory_kwargs[0]["decision_mode"] == "rules"
    assert factory_kwargs[0]["daily_market_context_allow_generate"] is False
    assert first.result.model_used == RULE_MODEL_ID
    assert first.recovered is False
    assert recovered.recovered is True
