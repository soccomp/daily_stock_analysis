"""Read-only list projection for the DSA investment-decisions UI."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from api.v1.endpoints import decision_scorecards
from src.investment.contracts.execution_result import ExecutionResult, SafetyCheck
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.execution_projection.mandate import ExecutionMandateProjector
from src.investment.m3.orchestration import M3ExecutionArtifacts
from src.investment.shadow_wiring import InvestmentShadowWiringService
from src.services.decision_scorecard_service import DecisionScorecardService
from src.storage import DatabaseManager
from tests.test_decision_scorecard_m2 import _buy_snapshot
from tests.test_investment_canary_p1 import _hold_snapshot
from tests.test_investment_shadow_wiring_p1a import NOW, _analysis_result, _policy, _snapshot
from tests.test_single_brain_m3_simulation_execution import _snapshot_b


def _shadow(
    snapshot,
    *,
    decision_id: str,
    source_report_id: int,
    created_at=NOW,
):
    return InvestmentShadowWiringService(clock=lambda: created_at).build_from_analysis(
        result=_analysis_result(),
        context_snapshot={"data_quality": {"level": "good"}},
        source_report_id=source_report_id,
        trace_id=f"trace:{decision_id}",
        trigger_source="ui_v1_list_test",
        portfolio_snapshot=snapshot,
        risk_policy=_policy(),
        decision_cycle_id=f"cycle:{decision_id}",
        decision_id=decision_id,
    )


def _m3_artifacts(*, status: str, decision_id: str):
    shadow = _shadow(_snapshot(), decision_id=decision_id, source_report_id=91)
    mandate = ExecutionMandateProjector.project(shadow.investment_decision)
    observed_snapshot = _snapshot_b(shadow.portfolio_snapshot_a, filled_quantity=0)
    snapshot_b = PortfolioSnapshot.build(
        **{
            **observed_snapshot.model_dump(exclude={"content_hash"}),
            "snapshot_id": f"snapshot-after:{decision_id}",
        }
    )
    submitted = mandate.quantity if status == "UNKNOWN" else 0
    result = ExecutionResult.build(
        result_id=f"result:{decision_id}",
        trace_id=mandate.trace_id,
        created_at=NOW,
        producer="ATHENA_SINGLE_BRAIN_M3_SIMULATION",
        mandate_id=mandate.mandate_id,
        mandate_hash=mandate.content_hash,
        decision_id=mandate.decision_id,
        decision_hash=mandate.decision_hash,
        attempt_no=1,
        account_id=mandate.account_id,
        symbol=mandate.symbol,
        status=status,
        requested_quantity=mandate.quantity,
        submitted_quantity=submitted,
        filled_quantity=0,
        remaining_quantity=mandate.quantity,
        requested_limit_price=mandate.limit_price,
        average_fill_price=None,
        fees=Decimal("0.00"),
        slippage_bps=None,
        broker_order_id=None,
        correlation_id=f"correlation:{decision_id}",
        safety_checks=(
            SafetyCheck(
                check="MARKET_SESSION" if status == "BLOCKED" else "SUBMISSION_STATE",
                status="BLOCKED" if status == "BLOCKED" else "UNKNOWN",
            ),
        ),
        block_reason="MARKET_SESSION_CLOSED" if status == "BLOCKED" else None,
        submitted_at=NOW if submitted else None,
        last_update_at=NOW,
        completed_at=NOW if status == "BLOCKED" else None,
        reconciliation_status=(
            "PENDING_RECONCILIATION" if status == "UNKNOWN" else "RECONCILED"
        ),
        portfolio_snapshot_after_id=snapshot_b.snapshot_id,
        portfolio_snapshot_after_hash=snapshot_b.content_hash,
    )
    return M3ExecutionArtifacts(
        source_report_id=shadow.source_report_id,
        research_bundle=shadow.research_bundle,
        portfolio_snapshot_a=shadow.portfolio_snapshot_a,
        risk_policy=shadow.risk_policy,
        investment_decision=shadow.investment_decision,
        decision_signal={
            **shadow.decision_signal,
            "shadow_only": False,
            "execution_permitted": True,
            "metadata": {
                **shadow.decision_signal["metadata"],
                "shadow_only": False,
                "execution_permitted": True,
            },
        },
        execution_mandate=mandate,
        execution_results=(result,),
        portfolio_snapshot_b=snapshot_b,
    )


def test_list_is_newest_first_paginated_and_filters_exact_lineage(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'ui-list.db'}")
    try:
        service = DecisionScorecardService(db_manager=db)
        artifacts = (
            _shadow(
                _buy_snapshot(),
                decision_id="decision-ui-buy",
                source_report_id=41,
            ),
            _shadow(
                _snapshot(),
                decision_id="decision-ui-add",
                source_report_id=42,
                created_at=NOW + timedelta(minutes=1),
            ),
            _shadow(
                _hold_snapshot(),
                decision_id="decision-ui-hold",
                source_report_id=43,
                created_at=NOW + timedelta(minutes=2),
            ),
        )
        for item in artifacts:
            service.persist_shadow(item)

        first_page = service.list(mode="M2_SHADOW", page=1, page_size=2)
        second_page = service.list(mode="M2_SHADOW", page=2, page_size=2)
        assert [item["action"] for item in first_page["items"]] == ["HOLD", "ADD"]
        assert [item["action"] for item in second_page["items"]] == ["BUY"]
        assert first_page["total"] == second_page["total"] == 3

        add = service.list(
            symbol="600519",
            action="ADD",
            mode="M2_SHADOW",
            source_report_id=42,
        )
        assert add["total"] == 1
        assert add["items"][0]["decision_id"] == "decision-ui-add"
        assert add["items"][0]["current_quantity"] == 300
        assert add["items"][0]["target_quantity"] == 500
        assert add["items"][0]["delta_quantity"] == 200

        assert service.list(mode="SIMULATION_EXECUTION")["items"] == []
    finally:
        DatabaseManager.reset_instance()


def test_hold_blocked_and_unknown_summaries_preserve_execution_meaning(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'ui-states.db'}")
    try:
        service = DecisionScorecardService(db_manager=db)
        hold = _shadow(
            _hold_snapshot(),
            decision_id="decision-ui-hold-state",
            source_report_id=90,
        )
        service.persist_shadow(hold)
        service.persist_m3(
            _m3_artifacts(status="BLOCKED", decision_id="decision-ui-blocked")
        )
        service.persist_m3(
            _m3_artifacts(status="UNKNOWN", decision_id="decision-ui-unknown")
        )

        hold_item = service.list(mode="M2_SHADOW")["items"][0]
        assert hold_item["action"] == "HOLD"
        assert hold_item["requested_quantity"] is None
        assert hold_item["snapshot_b_available"] is False

        items = {
            item["execution_status"]: item
            for item in service.list(mode="SIMULATION_EXECUTION")["items"]
        }
        blocked = items["BLOCKED"]
        assert blocked["requested_quantity"] == 200
        assert blocked["submitted_quantity"] == 0
        assert blocked["filled_quantity"] == 0
        assert blocked["remaining_quantity"] == 200
        assert blocked["block_reason"] == "MARKET_SESSION_CLOSED"

        unknown = items["UNKNOWN"]
        assert unknown["requested_quantity"] == 200
        assert unknown["submitted_quantity"] == 200
        assert unknown["filled_quantity"] == 0
        assert unknown["remaining_quantity"] == 200
        assert unknown["reconciliation_status"] == "PENDING_RECONCILIATION"
    finally:
        DatabaseManager.reset_instance()


def test_scorecard_list_router_is_get_only():
    paths = {
        (route.path, method)
        for route in decision_scorecards.router.routes
        for method in getattr(route, "methods", set())
    }
    assert ("", "GET") in paths
    assert ("/{decision_id}", "GET") in paths
    assert all(method == "GET" for _, method in paths)
