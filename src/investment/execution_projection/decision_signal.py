"""Human-readable legacy DecisionSignal projection from InvestmentDecision."""

from __future__ import annotations

from typing import Any

from src.investment.contracts.base import decimal_to_json
from src.investment.contracts.investment_decision import InvestmentDecision


class DecisionSignalProjector:
    """Build a legacy-compatible UI/API payload without creating a second decision."""

    @staticmethod
    def project(decision: InvestmentDecision) -> dict[str, Any]:
        entry_low = (
            decision.entry_plan.price_floor or decision.entry_plan.limit_price
            if decision.entry_plan is not None
            else None
        )
        entry_high = (
            decision.entry_plan.price_ceiling or decision.entry_plan.limit_price
            if decision.entry_plan is not None
            else None
        )
        payload: dict[str, Any] = {
            "stock_code": decision.symbol,
            "market": decision.market.lower(),
            "source_type": "agent",
            "source_agent": "DSAInvestmentDecisionEngine",
            "trace_id": decision.trace_id,
            "trigger_source": "investment_decision",
            "action": decision.action.lower(),
            "confidence": decimal_to_json(decision.confidence),
            "horizon": decision.horizon,
            "entry_low": None if entry_low is None else decimal_to_json(entry_low),
            "entry_high": None if entry_high is None else decimal_to_json(entry_high),
            "stop_loss": (
                decimal_to_json(decision.stop_plan.stop_price)
                if decision.stop_plan is not None
                else None
            ),
            "target_price": (
                decimal_to_json(decision.take_profit_plan.target_price)
                if decision.take_profit_plan is not None
                else None
            ),
            "invalidation": list(decision.invalidation_conditions),
            "reason": decision.rationale,
            "risk_summary": decision.risk_reasoning,
            "evidence": {
                "research_ids": list(decision.research_ids),
                "portfolio_snapshot_id": decision.portfolio_snapshot_id,
                "portfolio_snapshot_hash": decision.portfolio_snapshot_hash,
                "risk_policy_id": decision.risk_policy_id,
                "risk_policy_version": decision.risk_policy_version,
            },
            "status": "active",
            "expires_at": decision.valid_until,
            "metadata": {
                "projection_source": "InvestmentDecision",
                "investment_decision_id": decision.decision_id,
                "investment_decision_hash": decision.content_hash,
                "decision_cycle_id": decision.decision_cycle_id,
                "current_quantity": decision.current_quantity,
                "target_quantity": decision.target_quantity,
                "delta_quantity": decision.delta_quantity,
                "target_weight": decimal_to_json(decision.target_weight),
                "read_only_projection": True,
            },
        }
        return {key: value for key, value in payload.items() if value is not None}
