"""P1A real analysis-completion shadow wiring and zero-execution tests."""

from __future__ import annotations

import ast
import inspect
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.analyzer import AnalysisResult
from src.config import Config
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot, Position
from src.investment.contracts.risk_policy import RiskPolicy
from src.investment.execution_projection.mandate import ExecutionMandateProjector
from src.investment.shadow_wiring import (
    InvestmentShadowWiringService,
    ShadowWiringRejected,
)
from tests.test_pipeline_market_phase_context import _make_pipeline, _phase_payload


NOW = datetime(2026, 8, 8, 2, 0, tzinfo=timezone.utc)


def _analysis_result() -> AnalysisResult:
    result = AnalysisResult(
        code="600519",
        name="贵州茅台",
        sentiment_score=76,
        trend_prediction="中期上行趋势",
        operation_advice="加仓",
        decision_type="buy",
        confidence_level="高",
        action="add",
        technical_analysis="均线多头排列，量价配合改善。",
        fundamental_analysis="盈利质量与现金流保持稳健。",
        sector_position="高端白酒行业龙头，行业需求企稳。",
        company_highlights="品牌壁垒和渠道韧性支持上行情景。",
        news_summary="近期渠道反馈保持稳定。",
        market_sentiment="市场情绪偏正面。",
        volume_analysis="资金流和成交量同步改善。",
        analysis_summary="基本面与技术面共同支持中期正向研究结论。",
        risk_warning="需求转弱或跌破止损位将使研究结论失效。",
        model_used="test-provider/dsa-analysis-model",
        dashboard={
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": 95,
                    "secondary_buy": 100,
                    "stop_loss": 80,
                    "take_profit": 130,
                }
            },
            "intelligence": {"risk_alerts": ["渠道库存异常上升"]},
        },
    )
    result.analysis_context_pack_overview = {
        "data_quality": {"level": "good"},
    }
    return result


def _snapshot(*, as_of: datetime = NOW - timedelta(minutes=1)) -> PortfolioSnapshot:
    return PortfolioSnapshot.build(
        snapshot_id="snapshot-p1a-a",
        trace_id="athena-snapshot-trace-p1a",
        created_at=as_of,
        producer="ATHENA_SIMULATION_RECONCILIATION",
        account_id="simulation-account-1",
        broker="ATHENA_DECIMAL_SIM",
        account_mode="SIMULATION",
        as_of=as_of,
        revision=1,
        currency="CNY",
        equity=Decimal("1000000.00"),
        cash=Decimal("400000.00"),
        available_cash=Decimal("400000.00"),
        reserved_cash=Decimal("0.00"),
        positions=(
            Position(
                symbol="600519",
                market="CN",
                quantity=300,
                available_quantity=300,
                avg_cost=Decimal("90.00"),
                last_price=Decimal("100.00"),
                market_value=Decimal("30000.00"),
                unrealized_pnl=Decimal("3000.00"),
                price_as_of=as_of,
                price_source="ATHENA_DECIMAL_SIM",
            ),
        ),
        active_orders=(),
        realized_pnl=Decimal("0.00"),
        unrealized_pnl=Decimal("3000.00"),
        reconciliation_status="RECONCILED",
        data_quality="HIGH",
        limitations=(),
        broker_snapshot_ref="athena-sim:p1a-snapshot-a",
    )


def _policy(
    *,
    effective_from: datetime = NOW - timedelta(days=1),
    effective_until: datetime | None = NOW + timedelta(days=1),
) -> RiskPolicy:
    return RiskPolicy.build(
        policy_id="risk-policy-p1a",
        policy_version="1.0.0",
        trace_id="owner-policy-trace-p1a",
        created_at=effective_from,
        producer="OWNER_POLICY",
        account_scope=("simulation-account-1",),
        effective_from=effective_from,
        effective_until=effective_until,
        max_single_position_weight=Decimal("0.150000"),
        max_total_exposure=Decimal("0.900000"),
        min_cash_weight=Decimal("0.100000"),
        risk_budget_per_trade=Decimal("0.010000"),
        max_concurrent_positions=10,
        min_data_quality="UNKNOWN",
        allowed_markets=("CN",),
        allowed_instruments=("EQUITY",),
        position_sizing_method="TARGET_WEIGHT",
        stop_required=True,
    )


def _shadow_pipeline(*, enabled: bool = True) -> StockAnalysisPipeline:
    pipeline = _make_pipeline(agent_mode=False, save_context_snapshot=True)
    pipeline.config.investment_shadow_wiring_enabled = enabled
    pipeline.trace_id = "trace-real-analysis-p1a"
    pipeline.query_source = "api"
    pipeline.db.save_analysis_history.return_value = 42
    pipeline.analyzer.analyze.return_value = _analysis_result()
    pipeline._investment_shadow_portfolio_snapshot = _snapshot()
    pipeline._investment_shadow_risk_policy = _policy()
    pipeline._investment_shadow_clock = lambda: NOW
    return pipeline


def test_shadow_feature_switch_is_off_by_default_and_env_opt_in() -> None:
    assert Config().investment_shadow_wiring_enabled is False
    with patch.dict(os.environ, {"DSA_INVESTMENT_SHADOW_ENABLED": "true"}):
        assert Config._load_from_env().investment_shadow_wiring_enabled is True


def test_real_legacy_analysis_completion_builds_one_private_shadow_lineage() -> None:
    pipeline = _shadow_pipeline()
    phase_context = SimpleNamespace(to_dict=lambda: _phase_payload())

    with (
        patch("src.core.pipeline.build_market_phase_context", return_value=phase_context),
        patch("src.core.pipeline.extract_and_persist_from_analysis_result") as legacy_signal,
    ):
        result = pipeline.analyze_stock(
            "600519",
            ReportType.SIMPLE,
            "query-real-analysis-p1a",
            current_time=NOW,
        )

    assert isinstance(result, AnalysisResult)
    artifacts = result._investment_shadow_artifacts
    research = artifacts.research_bundle
    decision = artifacts.investment_decision
    signal = artifacts.decision_signal

    assert research.technical_view == "均线多头排列，量价配合改善。"
    assert research.fundamental_view == "盈利质量与现金流保持稳健。"
    assert research.base_case == "基本面与技术面共同支持中期正向研究结论。"
    assert decision.action == "ADD"
    assert decision.delta_quantity == 200
    assert decision.research_ids == (research.research_id,)
    assert decision.portfolio_snapshot_id == _snapshot().snapshot_id
    assert decision.portfolio_snapshot_hash == _snapshot().content_hash
    assert decision.risk_policy_id == _policy().policy_id
    assert decision.risk_policy_version == _policy().policy_version
    assert signal["metadata"]["investment_decision_id"] == decision.decision_id
    assert signal["metadata"]["investment_decision_hash"] == decision.content_hash
    assert signal["evidence"]["research_ids"] == (research.research_id,)
    assert signal["evidence"]["portfolio_snapshot_hash"] == decision.portfolio_snapshot_hash
    assert signal["evidence"]["risk_policy_id"] == decision.risk_policy_id
    assert signal["evidence"]["risk_policy_version"] == decision.risk_policy_version
    assert signal["shadow_only"] is True
    assert signal["execution_permitted"] is False
    assert artifacts.shadow_mandate is None
    assert artifacts.execution_permitted is False
    assert "_investment_shadow_artifacts" not in result.to_dict()
    pipeline.db.save_analysis_history.assert_called_once()
    legacy_signal.assert_called_once()


def test_disabled_shadow_wiring_does_not_import_or_build_shadow_service() -> None:
    pipeline = _shadow_pipeline(enabled=False)
    result = _analysis_result()

    with patch.object(InvestmentShadowWiringService, "build_from_analysis") as build:
        pipeline._run_investment_shadow_after_history_save(
            result=result,
            query_id="query-disabled",
            source_report_id=42,
            context_snapshot={"analysis_context_pack_overview": {"data_quality": {"level": "good"}}},
        )

    build.assert_not_called()
    assert not hasattr(result, "_investment_shadow_artifacts")


def test_missing_injected_authority_fails_closed_without_a_decision() -> None:
    pipeline = _shadow_pipeline()
    pipeline._investment_shadow_risk_policy = None
    result = _analysis_result()

    pipeline._run_investment_shadow_after_history_save(
        result=result,
        query_id="query-missing-policy",
        source_report_id=42,
        context_snapshot={"analysis_context_pack_overview": {"data_quality": {"level": "good"}}},
    )

    assert result._investment_shadow_artifacts is None


def test_noncanonical_injected_snapshot_fails_closed_without_a_decision() -> None:
    pipeline = _shadow_pipeline()
    pipeline._investment_shadow_portfolio_snapshot = {
        "source": "ATHENA_RUNTIME",
        "authoritative": True,
    }
    result = _analysis_result()

    pipeline._run_investment_shadow_after_history_save(
        result=result,
        query_id="query-invalid-snapshot",
        source_report_id=42,
        context_snapshot={
            "analysis_context_pack_overview": {"data_quality": {"level": "good"}}
        },
    )

    assert result._investment_shadow_artifacts is None


def test_stale_snapshot_and_expired_policy_fail_closed_without_a_decision() -> None:
    context = {"analysis_context_pack_overview": {"data_quality": {"level": "good"}}}

    stale_pipeline = _shadow_pipeline()
    stale_pipeline._investment_shadow_portfolio_snapshot = _snapshot(
        as_of=NOW - timedelta(minutes=6)
    )
    stale_result = _analysis_result()
    stale_pipeline._run_investment_shadow_after_history_save(
        result=stale_result,
        query_id="query-stale-snapshot",
        source_report_id=42,
        context_snapshot=context,
    )

    expired_pipeline = _shadow_pipeline()
    expired_pipeline._investment_shadow_risk_policy = _policy(
        effective_from=NOW - timedelta(days=2),
        effective_until=NOW - timedelta(days=1),
    )
    expired_result = _analysis_result()
    expired_pipeline._run_investment_shadow_after_history_save(
        result=expired_result,
        query_id="query-expired-policy",
        source_report_id=42,
        context_snapshot=context,
    )

    assert stale_result._investment_shadow_artifacts is None
    assert expired_result._investment_shadow_artifacts is None


@pytest.mark.parametrize(
    "producer_offset",
    (timedelta(milliseconds=93), timedelta(seconds=1)),
)
def test_shadow_wiring_accepts_authoritative_snapshot_within_clock_skew_budget(
    producer_offset: timedelta,
) -> None:
    snapshot = _snapshot(as_of=NOW + producer_offset)
    canonical_json = snapshot.canonical_json()
    content_hash = snapshot.content_hash

    artifacts = InvestmentShadowWiringService(clock=lambda: NOW).build_from_analysis(
        result=_analysis_result(),
        context_snapshot={"data_quality": {"level": "good"}},
        source_report_id=42,
        trace_id="cycle:bounded-skew",
        trigger_source="single_brain_m2_shadow",
        portfolio_snapshot=snapshot,
        risk_policy=_policy(),
    )

    assert artifacts.investment_decision.portfolio_snapshot_hash == content_hash
    assert snapshot.canonical_json() == canonical_json
    assert snapshot.content_hash == content_hash


def test_shadow_wiring_rejects_authoritative_snapshot_beyond_clock_skew_budget() -> None:
    with pytest.raises(ShadowWiringRejected, match="snapshot is from the future"):
        InvestmentShadowWiringService(clock=lambda: NOW).build_from_analysis(
            result=_analysis_result(),
            context_snapshot={"data_quality": {"level": "good"}},
            source_report_id=42,
            trace_id="cycle:future-skew",
            trigger_source="single_brain_m2_shadow",
            portfolio_snapshot=_snapshot(
                as_of=NOW + timedelta(seconds=1, microseconds=1)
            ),
            risk_policy=_policy(),
        )


def test_structured_watch_reaches_brain_as_hold_without_a_price_plan_or_mandate() -> None:
    result = _analysis_result()
    # The structured action is authoritative research evidence.  The conflicting
    # display advice proves this path is not a prose heuristic.
    result.action = "watch"
    result.operation_advice = "加仓"
    result.dashboard["battle_plan"]["sniper_points"].update(
        {
            "ideal_buy": "76.97",
            "secondary_buy": None,
            "stop_loss": "78.82",
            "take_profit": "82.52",
        }
    )

    artifacts = InvestmentShadowWiringService(clock=lambda: NOW).build_from_analysis(
        result=result,
        context_snapshot={"data_quality": {"level": "good"}},
        source_report_id=42,
        trace_id="cycle:research-watch",
        trigger_source="single_brain_m3_simulation_execution",
        portfolio_snapshot=_snapshot(),
        risk_policy=_policy(),
    )

    decision = artifacts.investment_decision
    assert decision.action == "HOLD"
    assert decision.current_quantity == decision.target_quantity == 300
    assert decision.delta_quantity == 0
    assert decision.entry_plan is decision.stop_plan is decision.take_profit_plan is None
    assert decision.expected_return == decision.expected_risk == Decimal("0")
    assert artifacts.research_bundle.expected_return_range.minimum == Decimal("0")
    assert artifacts.shadow_mandate is None
    assert artifacts.execution_permitted is False
    assert "entry_low" not in artifacts.decision_signal
    assert "stop_loss" not in artifacts.decision_signal
    assert "target_price" not in artifacts.decision_signal
    with pytest.raises(ValueError, match="only actionable BUY/ADD"):
        ExecutionMandateProjector.project(decision)


@pytest.mark.parametrize(
    "sniper_points, reason",
    (
        (
            {"ideal_buy": 95, "secondary_buy": 100, "stop_loss": 100, "take_profit": 130},
            "stop is not below",
        ),
        (
            {"ideal_buy": 95, "secondary_buy": 100, "stop_loss": 80, "take_profit": None},
            "lacks an entry, stop, or target",
        ),
        (
            {"ideal_buy": 95, "secondary_buy": 100, "stop_loss": 80, "take_profit": 100},
            "target is not above",
        ),
    ),
)
def test_actionable_research_with_invalid_price_plan_fails_closed(
    sniper_points,
    reason,
) -> None:
    result = _analysis_result()
    result.action = "add"
    result.dashboard["battle_plan"]["sniper_points"] = sniper_points

    with pytest.raises(ShadowWiringRejected, match=reason):
        InvestmentShadowWiringService(clock=lambda: NOW).build_from_analysis(
            result=result,
            context_snapshot={"data_quality": {"level": "good"}},
            source_report_id=42,
            trace_id="cycle:invalid-actionable-plan",
            trigger_source="single_brain_m3_simulation_execution",
            portfolio_snapshot=_snapshot(),
            risk_policy=_policy(),
        )


def test_non_actionable_hold_contract_is_deterministic_and_immutable() -> None:
    def build():
        result = _analysis_result()
        result.action = "watch"
        result.dashboard["battle_plan"]["sniper_points"]["stop_loss"] = 110
        return InvestmentShadowWiringService(clock=lambda: NOW).build_from_analysis(
            result=result,
            context_snapshot={"data_quality": {"level": "good"}},
            source_report_id=42,
            trace_id="cycle:deterministic-watch",
            trigger_source="single_brain_m3_simulation_execution",
            portfolio_snapshot=_snapshot(),
            risk_policy=_policy(),
        ).investment_decision

    first = build()
    second = build()
    assert first.canonical_json() == second.canonical_json()
    assert first.content_hash == second.content_hash
    with pytest.raises(ValidationError):
        first.delta_quantity = 100


def test_shadow_module_has_no_execution_transport_persistence_or_retry_surface() -> None:
    module = inspect.getmodule(InvestmentShadowWiringService)
    assert module is not None
    tree = ast.parse(inspect.getsource(module))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    forbidden_imports = (
        "requests",
        "httpx",
        "urllib",
        "socket",
        "queue",
        "src.brokers",
        "src.investment.contracts.execution_mandate",
        "src.investment.execution_projection.mandate",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_imports
    )

    forbidden_calls = {
        "submit",
        "submit_order",
        "dispatch",
        "enqueue",
        "post",
        "publish",
        "execute",
        "retry",
        "save",
        "commit",
        "send",
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called_attributes.isdisjoint(forbidden_calls)
