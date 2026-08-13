"""LLM-free InvestmentDecision -> ExecutionMandate projection."""

from __future__ import annotations

import hashlib

from src.investment.contracts.base import canonical_json_bytes
from src.investment.contracts.execution_mandate import ExecutionMandate
from src.investment.contracts.investment_decision import InvestmentDecision


class ExecutionMandateProjector:
    """Project exact final quantity; the API intentionally has no quantity input."""

    @staticmethod
    def project(decision: InvestmentDecision) -> ExecutionMandate:
        if decision.action not in {"BUY", "ADD"} or decision.delta_quantity <= 0:
            raise ValueError("only actionable BUY/ADD decisions can produce a P0 mandate")
        if decision.entry_plan is None:
            raise ValueError("actionable BUY/ADD decisions require an entry plan")
        idempotency_key = hashlib.sha256(
            canonical_json_bytes(
                {
                    "decision_id": decision.decision_id,
                    "decision_hash": decision.content_hash,
                    "operation": "SUBMIT",
                    "side": "BUY",
                    "quantity": decision.delta_quantity,
                    "order_type": "LIMIT",
                    "limit_price": decision.entry_plan.limit_price,
                    "account_id": decision.account_id,
                    "symbol": decision.symbol,
                }
            )
        ).hexdigest()
        mandate_id = f"mandate-{decision.content_hash[:32]}"
        mandate = ExecutionMandate.build(
            mandate_id=mandate_id,
            decision_id=decision.decision_id,
            decision_hash=decision.content_hash,
            decision_cycle_id=decision.decision_cycle_id,
            trace_id=decision.trace_id,
            created_at=decision.created_at,
            producer="DSA_EXECUTION_MANDATE_PROJECTOR",
            supersedes_id=None,
            supersedes_mandate_id=None,
            account_id=decision.account_id,
            symbol=decision.symbol,
            market=decision.market,
            mandate_type="ENTRY" if decision.action == "BUY" else "ADD",
            operation="SUBMIT",
            side="BUY",
            quantity=decision.delta_quantity,
            order_type="LIMIT",
            limit_price=decision.entry_plan.limit_price,
            trigger_condition="IMMEDIATE",
            time_in_force="DAY",
            valid_from=decision.valid_from,
            valid_until=decision.valid_until,
            portfolio_snapshot_id=decision.portfolio_snapshot_id,
            portfolio_snapshot_hash=decision.portfolio_snapshot_hash,
            expected_position_before=decision.current_quantity,
            expected_position_after=decision.target_quantity,
            simulation_only=True,
            idempotency_key=idempotency_key,
        )
        mandate.assert_matches_decision(decision)
        return mandate
