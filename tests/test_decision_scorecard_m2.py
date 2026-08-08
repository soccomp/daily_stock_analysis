"""M2 shadow persistence through the existing Single Decision Scorecard."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.scorecard import SingleDecisionScorecard
from src.investment.shadow_wiring import InvestmentShadowWiringService
from src.services.decision_scorecard_service import DecisionScorecardService
from src.storage import DatabaseManager
from tests.test_investment_canary_p1 import _hold_snapshot
from tests.test_investment_shadow_wiring_p1a import (
    NOW,
    _analysis_result,
    _policy,
    _snapshot,
)


def _buy_snapshot() -> PortfolioSnapshot:
    as_of = NOW - timedelta(minutes=1)
    return PortfolioSnapshot.build(
        snapshot_id="snapshot-m2-shadow-buy",
        trace_id="athena-snapshot-trace-m2-shadow-buy",
        created_at=as_of,
        producer="ATHENA_SIMULATION_RECONCILIATION",
        account_id="simulation-account-1",
        broker="ATHENA_DECIMAL_SIM",
        account_mode="SIMULATION",
        as_of=as_of,
        revision=1,
        currency="CNY",
        equity=Decimal("1000000.00"),
        cash=Decimal("1000000.00"),
        available_cash=Decimal("1000000.00"),
        reserved_cash=Decimal("0.00"),
        positions=(),
        active_orders=(),
        realized_pnl=Decimal("0.00"),
        unrealized_pnl=Decimal("0.00"),
        reconciliation_status="RECONCILED",
        data_quality="HIGH",
        limitations=(),
        broker_snapshot_ref="athena-sim:m2-shadow-buy",
    )


def _shadow_artifacts(
    snapshot: PortfolioSnapshot,
    *,
    trace_id: str,
):
    return InvestmentShadowWiringService(clock=lambda: NOW).build_from_analysis(
        result=_analysis_result(),
        context_snapshot={"data_quality": {"level": "good"}},
        source_report_id=42,
        trace_id=trace_id,
        trigger_source="m2_shadow_test",
        portfolio_snapshot=snapshot,
        risk_policy=_policy(),
    )


@pytest.mark.parametrize(
    ("snapshot_factory", "expected_action"),
    (
        (_buy_snapshot, "BUY"),
        (_snapshot, "ADD"),
        (_hold_snapshot, "HOLD"),
    ),
)
def test_shadow_scorecard_accepts_buy_add_and_hold_without_execution_artifacts(
    snapshot_factory,
    expected_action,
):
    artifacts = _shadow_artifacts(
        snapshot_factory(),
        trace_id=f"trace-m2-scorecard-{expected_action.lower()}",
    )

    scorecard = SingleDecisionScorecard.from_shadow(artifacts)
    restored = SingleDecisionScorecard.from_json(scorecard.to_json())
    payload = restored.to_payload()

    assert restored.scorecard_hash == scorecard.scorecard_hash
    assert payload["investment_decision"]["action"] == expected_action
    assert payload["execution_mandate"] is None
    assert payload["execution_results"] == []
    assert payload["portfolio_snapshot_b"] is None
    assert payload["execution_diagnostics"]["mode"] == "M2_SHADOW"
    assert payload["execution_diagnostics"]["execution_authorization"] == "OFF"
    assert payload["execution_diagnostics"]["execution_state"] == "NOT_AUTHORIZED"
    assert payload["decision_signal"]["shadow_only"] is True
    assert payload["decision_signal"]["execution_permitted"] is False


def test_shadow_scorecard_service_persists_full_lineage_once(tmp_path):
    artifacts = _shadow_artifacts(
        _snapshot(),
        trace_id="trace-m2-scorecard-persistence",
    )
    decision = artifacts.investment_decision
    snapshot = artifacts.portfolio_snapshot_a
    policy = artifacts.risk_policy

    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'm2-shadow-scorecard.db'}")
    try:
        service = DecisionScorecardService(db_manager=db)
        created = service.persist_shadow(artifacts)
        duplicate = service.persist_shadow(artifacts)
        restored = service.get(decision.decision_id)["item"]
    finally:
        DatabaseManager.reset_instance()

    assert created["created"] is True
    assert duplicate["created"] is False
    assert restored["research_bundle"]["research_id"] == decision.research_ids[0]
    assert restored["portfolio_snapshot_a"]["snapshot_id"] == (
        decision.portfolio_snapshot_id
    )
    assert restored["portfolio_snapshot_a"]["content_hash"] == (
        decision.portfolio_snapshot_hash
    )
    assert restored["risk_policy"]["policy_id"] == decision.risk_policy_id
    assert restored["risk_policy"]["policy_version"] == (
        decision.risk_policy_version
    )
    assert restored["investment_decision"]["decision_cycle_id"] == (
        decision.decision_cycle_id
    )
    assert restored["decision_signal"]["metadata"]["investment_decision_id"] == (
        decision.decision_id
    )
    assert restored["decision_signal"]["metadata"]["investment_decision_hash"] == (
        decision.content_hash
    )
    assert restored["execution_mandate"] is None
    assert restored["execution_results"] == []
    assert restored["portfolio_snapshot_b"] is None

    freshness = restored["execution_diagnostics"]["snapshot_freshness"]
    assert freshness == {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.content_hash,
        "as_of": snapshot.as_of.isoformat().replace("+00:00", "Z"),
        "validated_at": decision.created_at.isoformat().replace("+00:00", "Z"),
        "reconciliation_status": snapshot.reconciliation_status,
        "source": "ATHENA_RUNTIME",
        "authoritative": True,
        "read_only": True,
    }
    assert restored["execution_diagnostics"]["submitted_quantity"] is None
    assert policy.policy_id == decision.risk_policy_id
