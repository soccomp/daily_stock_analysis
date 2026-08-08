"""P1B real analysis lifecycle -> local Athena simulation canary."""

from __future__ import annotations

import os
import ast
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.analyzer import AnalysisResult
from src.config import Config
from src.enums import ReportType
from src.investment.canary import InvestmentCanaryService
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot, Position
from src.investment.decision import risk_budget_target_weight
from src.investment.integration import LocalAthenaCanaryTransport
from tests.test_investment_shadow_wiring_p1a import (
    NOW,
    _analysis_result,
    _policy,
    _shadow_pipeline,
)
from tests.test_pipeline_market_phase_context import _phase_payload


ATHENA_ROOT = Path(
    os.environ.get(
        "ATHENA_REPO",
        Path(__file__).resolve().parents[2] / "athena",
    )
)


class CaptureOnlyTransport:
    def __init__(self, snapshot: PortfolioSnapshot):
        self.snapshot = snapshot
        self.capture_count = 0
        self.execute_count = 0

    def capture_snapshot(self) -> PortfolioSnapshot:
        self.capture_count += 1
        return self.snapshot

    def execute(self, _mandate, _snapshot):
        self.execute_count += 1
        raise AssertionError("HOLD must not reach Athena execution")


class ForbiddenTransport:
    def capture_snapshot(self):
        raise AssertionError("disabled or non-allowlisted canary reached transport")

    def execute(self, _mandate, _snapshot):
        raise AssertionError("disabled or non-allowlisted canary reached execution")


class RecordingScorecardService:
    def __init__(self):
        self.artifacts = None

    def persist_canary(self, artifacts):
        self.artifacts = artifacts
        return {
            "item": {
                "decision_id": artifacts.investment_decision.decision_id,
                "read_only": True,
            },
            "created": True,
        }


def _hold_snapshot() -> PortfolioSnapshot:
    as_of = NOW - timedelta(minutes=1)
    return PortfolioSnapshot.build(
        snapshot_id="snapshot-p1b-hold",
        trace_id="athena-snapshot-trace-p1b-hold",
        created_at=as_of,
        producer="ATHENA_SIMULATION_RECONCILIATION",
        account_id="simulation-account-1",
        broker="ATHENA_DECIMAL_SIM",
        account_mode="SIMULATION",
        as_of=as_of,
        revision=1,
        currency="CNY",
        equity=Decimal("1000000.00"),
        cash=Decimal("940000.00"),
        available_cash=Decimal("940000.00"),
        reserved_cash=Decimal("0.00"),
        positions=(
            Position(
                symbol="600519",
                market="CN",
                quantity=600,
                available_quantity=600,
                avg_cost=Decimal("90.00"),
                last_price=Decimal("100.00"),
                market_value=Decimal("60000.00"),
                unrealized_pnl=Decimal("6000.00"),
                price_as_of=as_of,
                price_source="ATHENA_DECIMAL_SIM",
            ),
        ),
        active_orders=(),
        realized_pnl=Decimal("0.00"),
        unrealized_pnl=Decimal("6000.00"),
        reconciliation_status="RECONCILED",
        data_quality="HIGH",
        limitations=(),
        broker_snapshot_ref="athena-sim:p1b-hold",
    )


def test_p1_risk_budget_target_weight_uses_max_position_only_as_cap() -> None:
    target = risk_budget_target_weight(
        entry_limit=Decimal("100"),
        stop_price=Decimal("80"),
        risk_budget_per_trade=Decimal("0.01"),
        max_single_position_weight=Decimal("0.15"),
    )
    capped = risk_budget_target_weight(
        entry_limit=Decimal("100"),
        stop_price=Decimal("95"),
        risk_budget_per_trade=Decimal("0.01"),
        max_single_position_weight=Decimal("0.15"),
    )

    assert target == Decimal("0.05")
    assert capped == Decimal("0.15")
    assert target != Decimal("0.15")


def test_position_at_or_above_risk_target_holds_without_execution() -> None:
    transport = CaptureOnlyTransport(_hold_snapshot())
    artifacts = InvestmentCanaryService(clock=lambda: NOW).run_from_analysis(
        result=_analysis_result(),
        context_snapshot={"data_quality": {"level": "good"}},
        source_report_id=42,
        trace_id="trace-p1b-hold",
        trigger_source="test",
        risk_policy=_policy(),
        transport=transport,
        account_id="simulation-account-1",
        allowed_symbols=frozenset({"600519"}),
    )

    assert artifacts.investment_decision.action == "HOLD"
    assert artifacts.investment_decision.delta_quantity == 0
    assert artifacts.execution_mandate is None
    assert artifacts.execution_result is None
    assert transport.capture_count == 1
    assert transport.execute_count == 0


def test_canary_flags_are_separate_and_off_by_default() -> None:
    config = Config()
    assert config.investment_shadow_wiring_enabled is False
    assert config.investment_canary_enabled is False
    with patch.dict(
        os.environ,
        {
            "DSA_INVESTMENT_SHADOW_ENABLED": "true",
            "DSA_INVESTMENT_CANARY_ENABLED": "false",
            "DSA_INVESTMENT_CANARY_ACCOUNT_ID": "simulation-account-1",
            "DSA_INVESTMENT_CANARY_SYMBOLS": "600519,000001",
        },
    ):
        loaded = Config._load_from_env()
    assert loaded.investment_shadow_wiring_enabled is True
    assert loaded.investment_canary_enabled is False
    assert loaded.investment_canary_account_id == "simulation-account-1"
    assert loaded.investment_canary_symbols == ["600519", "000001"]


def test_feature_flag_off_and_non_allowlist_have_zero_transport_side_effects() -> None:
    result = _analysis_result()
    pipeline = _shadow_pipeline(enabled=False)
    pipeline._investment_canary_transport = ForbiddenTransport()
    pipeline.config.investment_canary_enabled = False
    pipeline._run_investment_shadow_after_history_save(
        result=result,
        query_id="query-canary-off",
        source_report_id=42,
        context_snapshot={"data_quality": {"level": "good"}},
    )
    assert not hasattr(result, "_investment_canary_artifacts")

    result = _analysis_result()
    pipeline.config.investment_canary_enabled = True
    pipeline.config.investment_canary_account_id = "simulation-account-1"
    pipeline.config.investment_canary_symbols = ["000001"]
    pipeline._run_investment_shadow_after_history_save(
        result=result,
        query_id="query-canary-disallowed",
        source_report_id=42,
        context_snapshot={"data_quality": {"level": "good"}},
    )
    assert result._investment_canary_artifacts is None


def test_one_shot_canary_runner_is_explicit_and_has_no_deployment_mutation() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_p1_simulation_canary.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    option_strings = {
        argument.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for argument in node.args
        if isinstance(argument, ast.Constant)
        and isinstance(argument.value, str)
    }
    assert "--confirm-simulation-only" in option_strings
    assert "launchctl" not in source
    assert ".plist" not in source


@pytest.mark.integration
def test_real_dsa_analysis_completion_executes_exact_local_athena_canary(tmp_path) -> None:
    if not (ATHENA_ROOT / "src" / "trading_spine" / "canary.py").is_file():
        pytest.skip("sibling Athena P1 canary repository is unavailable")
    pipeline = _shadow_pipeline(enabled=True)
    pipeline.config.investment_canary_enabled = True
    pipeline.config.investment_canary_account_id = "simulation-account-1"
    pipeline.config.investment_canary_symbols = ["600519"]
    scorecard_service = RecordingScorecardService()
    pipeline._investment_scorecard_service = scorecard_service
    phase_context = SimpleNamespace(to_dict=lambda: _phase_payload())

    with LocalAthenaCanaryTransport.for_athena_worktree(
        athena_root=ATHENA_ROOT,
        journal_path=tmp_path / "athena-p1-canary.jsonl",
        account_id="simulation-account-1",
        symbol="600519",
        allowed_symbols=("600519",),
        cash=Decimal("970000.00"),
        position_quantity=300,
        avg_cost=Decimal("90.00"),
        last_price=Decimal("100.00"),
        now=NOW,
    ) as transport:
        pipeline._investment_canary_transport = transport
        with patch(
            "src.core.pipeline.build_market_phase_context",
            return_value=phase_context,
        ):
            result = pipeline.analyze_stock(
                "600519",
                ReportType.SIMPLE,
                "query-real-analysis-p1b",
                current_time=NOW,
            )

    assert isinstance(result, AnalysisResult)
    artifacts = result._investment_canary_artifacts
    decision = artifacts.investment_decision
    mandate = artifacts.execution_mandate
    execution = artifacts.execution_result
    snapshot_a = artifacts.portfolio_snapshot_a
    snapshot_b = artifacts.portfolio_snapshot_b

    assert artifacts.research_bundle.technical_view == _analysis_result().technical_analysis
    assert decision.action == "ADD"
    assert decision.target_weight == Decimal("0.050000")
    assert decision.delta_quantity == mandate.quantity == 200
    assert execution.requested_quantity == execution.submitted_quantity == 200
    assert artifacts.submitted_quantities == (200,)
    assert snapshot_b.position_for(symbol="600519", market="CN").quantity == (
        snapshot_a.position_for(symbol="600519", market="CN").quantity
        + execution.filled_quantity
    )
    assert decision.research_ids == (artifacts.research_bundle.research_id,)
    assert decision.portfolio_snapshot_id == snapshot_a.snapshot_id
    assert decision.portfolio_snapshot_hash == snapshot_a.content_hash
    assert decision.risk_policy_id == artifacts.risk_policy.policy_id
    assert mandate.decision_id == execution.decision_id == decision.decision_id
    assert execution.portfolio_snapshot_after_id == snapshot_b.snapshot_id
    assert execution.portfolio_snapshot_after_hash == snapshot_b.content_hash
    assert "_investment_canary_artifacts" not in result.to_dict()
    assert scorecard_service.artifacts is artifacts
    assert result._investment_scorecard == {
        "decision_id": decision.decision_id,
        "read_only": True,
    }
    assert "_investment_scorecard" not in result.to_dict()
