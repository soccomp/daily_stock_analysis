"""Literal cross-repository P0 simulation closure over canonical JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.investment.contracts import ExecutionResult, PortfolioSnapshot, RiskPolicy
from src.investment.contracts.investment_decision import (
    EntryPlan,
    StopPlan,
    TakeProfitPlan,
)
from src.investment.contracts.research_bundle import ModelProvenance
from src.investment.decision import DecisionSizingInput, InvestmentDecisionEngine
from src.investment.execution_projection import ExecutionMandateProjector
from src.investment.research import ResearchBundleAdapter


NOW = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)
ATHENA_ROOT = Path(
    os.environ.get(
        "ATHENA_REPO",
        Path(__file__).resolve().parents[2] / "athena",
    )
)


def _run_athena(script: str, *, stdin: str | None = None) -> str:
    if not (ATHENA_ROOT / "src" / "trading_spine").is_dir():
        pytest.skip("sibling Athena trading_spine repository is not available")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=ATHENA_ROOT,
        env=environment,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _athena_snapshot_a() -> PortfolioSnapshot:
    wire = _run_athena(
        """
        import sys
        from datetime import datetime, timezone
        from src.trading_spine import (
            AuthoritativePortfolioSnapshotAdapter,
            DecimalSimulationBroker,
        )

        now = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)
        broker = DecimalSimulationBroker(
            account_id="simulation-account-1",
            cash="970000.00",
            positions={
                "600519": {
                    "market": "CN",
                    "quantity": 300,
                    "avg_cost": "90.00",
                    "last_price": "100.00",
                }
            },
            clock=lambda: now,
        )
        adapter = AuthoritativePortfolioSnapshotAdapter(
            broker,
            account_id=broker.account_id,
            broker=broker.broker_name,
            default_market="CN",
        )
        sys.stdout.write(adapter.capture().to_json())
        """
    )
    return PortfolioSnapshot.model_validate_json(wire)


def _athena_execute(mandate_json: str) -> dict:
    output = _run_athena(
        """
        import json
        import sys
        from datetime import datetime, timezone
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from src.trading_spine import (
            AuthoritativePortfolioSnapshotAdapter,
            DecimalSimulationBroker,
            ExecutionJournal,
            ExecutionMandate,
            MandateExecutionService,
            OperationalSafetyKernel,
        )

        now = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)
        broker = DecimalSimulationBroker(
            account_id="simulation-account-1",
            cash="970000.00",
            positions={
                "600519": {
                    "market": "CN",
                    "quantity": 300,
                    "avg_cost": "90.00",
                    "last_price": "100.00",
                }
            },
            clock=lambda: now,
        )
        adapter = AuthoritativePortfolioSnapshotAdapter(
            broker,
            account_id=broker.account_id,
            broker=broker.broker_name,
            default_market="CN",
        )
        snapshot_a = adapter.capture()
        mandate = ExecutionMandate.from_json(sys.stdin.read())
        journal_directory = TemporaryDirectory()
        journal = ExecutionJournal(
            Path(journal_directory.name) / "execution-lineage.jsonl"
        )
        service = MandateExecutionService(
            broker=broker,
            portfolio_adapter=adapter,
            safety_kernel=OperationalSafetyKernel(
                market_session=lambda _mandate, _now: True,
                contract_validator=lambda _mandate: True,
            ),
            journal=journal,
            clock=lambda: now,
        )
        result = service.execute(mandate, snapshot_a)
        sys.stdout.write(json.dumps({
            "result": result.to_wire(),
            "snapshot_b": adapter.current.to_wire(),
            "submitted_quantities": broker.submitted_quantities,
            "durable_intent_count": len(journal.reservations),
        }, ensure_ascii=False, sort_keys=True))
        """,
        stdin=mandate_json,
    )
    return json.loads(output)


@pytest.mark.integration
def test_dsa_brain_to_athena_exact_buy_200_vertical_slice() -> None:
    snapshot_a = _athena_snapshot_a()
    research = ResearchBundleAdapter.from_dsa_views(
        research_id="research-600519-p0-e2e",
        trace_id="trace-600519-p0-e2e",
        created_at=NOW,
        producer="DSA_RESEARCH_ADAPTER",
        symbol="600519",
        market="CN",
        as_of=NOW,
        horizon="swing",
        trigger_source="p0_cross_repository_test",
        market_regime="constructive",
        industry_view="positive",
        fundamental_view="positive",
        technical_view="positive",
        valuation_view="neutral",
        intel_view="positive",
        capital_flow_view="neutral",
        bull_case="Demand and margins improve.",
        base_case="Earnings remain resilient.",
        bear_case="Demand weakens.",
        expected_return_minimum=Decimal("0.100000"),
        expected_return_maximum=Decimal("0.200000"),
        catalysts=("earnings",),
        risk_factors=("demand slowdown",),
        invalidation_conditions=("close below stop",),
        evidence_refs=("dsa-analysis:600519:p0-e2e",),
        data_quality="HIGH",
        confidence=Decimal("0.840000"),
        model_provenance=(
            ModelProvenance(
                model_name="dsa-research-synthesis",
                model_version="p0-v1",
                provider="DSA",
                prompt_hash="a" * 64,
            ),
        ),
        strategy_refs=("p0-single-stock",),
    )
    policy = RiskPolicy.build(
        policy_id="risk-policy-p0-e2e",
        policy_version="1.0.0",
        trace_id="owner-policy-p0-e2e",
        created_at=NOW - timedelta(days=1),
        producer="OWNER_POLICY",
        account_scope=(snapshot_a.account_id,),
        effective_from=NOW - timedelta(days=1),
        max_single_position_weight=Decimal("0.150000"),
        max_total_exposure=Decimal("0.900000"),
        min_cash_weight=Decimal("0.100000"),
        risk_budget_per_trade=Decimal("0.010000"),
        max_concurrent_positions=10,
        min_data_quality="MEDIUM",
        allowed_markets=("CN",),
        allowed_instruments=("EQUITY",),
    )
    sizing = DecisionSizingInput(
        decision_id="decision-p0-e2e",
        decision_cycle_id="decision-cycle-p0-e2e",
        created_at=NOW,
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
        proposed_target_weight=Decimal("0.050000"),
        lot_size=100,
        entry_plan=EntryPlan(
            limit_price=Decimal("100.00"),
            price_floor=Decimal("95.00"),
            price_ceiling=Decimal("100.00"),
        ),
        stop_plan=StopPlan(stop_price=Decimal("50.00")),
        take_profit_plan=TakeProfitPlan(target_price=Decimal("130.00")),
        rationale="Positive research supports one policy-constrained ADD.",
        horizon="swing",
    )

    decision = InvestmentDecisionEngine().decide(
        research=research,
        portfolio=snapshot_a,
        risk_policy=policy,
        sizing=sizing,
    )
    mandate = ExecutionMandateProjector.project(decision)
    observed = _athena_execute(mandate.canonical_json())
    result = ExecutionResult.model_validate_json(json.dumps(observed["result"]))
    snapshot_b = PortfolioSnapshot.model_validate_json(
        json.dumps(observed["snapshot_b"])
    )

    assert decision.action == "ADD"
    assert decision.delta_quantity == mandate.quantity == 200
    assert result.requested_quantity == result.submitted_quantity == 200
    assert observed["submitted_quantities"] == [200]
    assert observed["durable_intent_count"] == 1
    assert result.filled_quantity == 200
    assert snapshot_b.position_for(symbol="600519", market="CN").quantity == (
        snapshot_a.position_for(symbol="600519", market="CN").quantity
        + result.filled_quantity
    )
    assert result.decision_id == mandate.decision_id == decision.decision_id
    assert result.decision_hash == mandate.decision_hash == decision.content_hash
    assert result.mandate_id == mandate.mandate_id
    assert result.mandate_hash == mandate.content_hash
    assert result.broker_order_id and result.correlation_id
    assert result.portfolio_snapshot_after_id == snapshot_b.snapshot_id
    assert result.portfolio_snapshot_after_hash == snapshot_b.content_hash
    assert snapshot_b.authoritative is snapshot_b.read_only is True
    assert snapshot_b.source == "ATHENA_RUNTIME"
