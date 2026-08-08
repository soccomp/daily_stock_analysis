"""Single-Brain P0 decision engine: research + portfolio + policy -> quantity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

from src.investment.contracts.base import decimal_to_json
from src.investment.contracts.investment_decision import (
    EntryPlan,
    InvestmentDecision,
    StopPlan,
    TakeProfitPlan,
)
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.contracts.research_bundle import ModelProvenance, ResearchBundle
from src.investment.contracts.risk_policy import RiskPolicy


_WEIGHT_QUANTUM = Decimal("0.000001")
_DATA_QUALITY_RANK = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def _require_exact_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    return value


def _floor_lot(quantity: Decimal, lot_size: int) -> int:
    lots = (quantity / Decimal(lot_size)).to_integral_value(rounding=ROUND_DOWN)
    return max(0, int(lots) * lot_size)


def _weight(value: Decimal, equity: Decimal) -> Decimal:
    return (value / equity).quantize(_WEIGHT_QUANTUM, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class DecisionSizingInput:
    """Explicit deterministic capital-allocation inputs owned by DSA Brain."""

    decision_id: str
    decision_cycle_id: str
    created_at: datetime
    valid_from: datetime
    valid_until: datetime
    proposed_target_weight: Decimal
    lot_size: int
    entry_plan: EntryPlan
    stop_plan: StopPlan | None
    take_profit_plan: TakeProfitPlan | None
    rationale: str
    horizon: str
    instrument: str = "EQUITY"
    producer: str = "DSA_INVESTMENT_DECISION_ENGINE"
    supersedes_decision_id: str | None = None

    def __post_init__(self) -> None:
        target = _require_exact_decimal(self.proposed_target_weight, "proposed_target_weight")
        if target <= 0 or target > 1:
            raise ValueError("proposed_target_weight must be in (0, 1]")
        if not isinstance(self.lot_size, int) or isinstance(self.lot_size, bool) or self.lot_size <= 0:
            raise ValueError("lot_size must be a positive integer")
        for field_name in ("created_at", "valid_from", "valid_until"):
            timestamp = getattr(self, field_name)
            if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
        for field_name in (
            "decision_id",
            "decision_cycle_id",
            "rationale",
            "horizon",
            "instrument",
            "producer",
        ):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} is required")


class InvestmentDecisionEngine:
    """The only P0 service allowed to convert target weight into final quantity."""

    ENGINE_VERSION = "dsa-investment-decision-engine-p0-v1"

    def decide(
        self,
        *,
        research: ResearchBundle,
        portfolio: PortfolioSnapshot,
        risk_policy: RiskPolicy,
        sizing: DecisionSizingInput,
    ) -> InvestmentDecision:
        self._validate_authorities(
            research=research,
            portfolio=portfolio,
            risk_policy=risk_policy,
            sizing=sizing,
        )
        equity = portfolio.equity
        if equity <= 0:
            raise ValueError("authoritative portfolio equity must be positive")

        position = portfolio.position_for(symbol=research.symbol, market=research.market)
        current_quantity = position.quantity if position is not None else 0
        current_value = position.market_value if position is not None else Decimal("0")
        current_weight = _weight(current_value, equity)
        entry_price = sizing.entry_plan.limit_price

        total_exposure = sum(
            (item.market_value for item in portfolio.positions),
            Decimal("0"),
        )
        requested_add_value = max(
            Decimal("0"),
            sizing.proposed_target_weight * equity - current_value,
        )
        single_position_add_cap = max(
            Decimal("0"),
            risk_policy.max_single_position_weight * equity - current_value,
        )
        total_exposure_add_cap = max(
            Decimal("0"),
            risk_policy.max_total_exposure * equity - total_exposure,
        )
        cash_add_cap = max(
            Decimal("0"),
            portfolio.available_cash - risk_policy.min_cash_weight * equity,
        )
        add_value_cap = min(
            requested_add_value,
            single_position_add_cap,
            total_exposure_add_cap,
            cash_add_cap,
        )

        value_capped_delta = _floor_lot(add_value_cap / entry_price, sizing.lot_size)

        risk_capped_delta = self._risk_capped_delta(
            equity=equity,
            risk_policy=risk_policy,
            sizing=sizing,
            fallback_delta=value_capped_delta,
        )
        delta_quantity = min(value_capped_delta, risk_capped_delta)
        expected_return = (
            research.expected_return_range.minimum + research.expected_return_range.maximum
        ) / Decimal("2")
        if expected_return <= 0:
            delta_quantity = 0
        if current_quantity == 0:
            position_count = sum(position.quantity > 0 for position in portfolio.positions)
            if position_count >= risk_policy.max_concurrent_positions:
                delta_quantity = 0

        target_quantity = current_quantity + delta_quantity
        action = "HOLD"
        if delta_quantity > 0:
            action = "BUY" if current_quantity == 0 else "ADD"
        target_weight = (
            _weight(current_value + Decimal(delta_quantity) * entry_price, equity)
            if delta_quantity > 0
            else current_weight
        )
        expected_risk = self._expected_risk(sizing)
        risk_reasoning = self._risk_reasoning(
            requested_weight=sizing.proposed_target_weight,
            target_weight=target_weight,
            value_capped_delta=value_capped_delta,
            risk_capped_delta=risk_capped_delta,
            lot_size=sizing.lot_size,
            expected_return=expected_return,
        )

        return InvestmentDecision.build(
            decision_id=sizing.decision_id,
            decision_cycle_id=sizing.decision_cycle_id,
            trace_id=research.trace_id,
            created_at=sizing.created_at,
            producer=sizing.producer,
            supersedes_id=sizing.supersedes_decision_id,
            supersedes_decision_id=sizing.supersedes_decision_id,
            account_id=portfolio.account_id,
            symbol=research.symbol,
            market=research.market,
            action=action,
            research_ids=(research.research_id,),
            portfolio_snapshot_id=portfolio.snapshot_id,
            portfolio_snapshot_hash=portfolio.content_hash,
            risk_policy_id=risk_policy.policy_id,
            risk_policy_version=risk_policy.policy_version,
            current_quantity=current_quantity,
            current_weight=current_weight,
            target_quantity=target_quantity,
            target_weight=target_weight,
            delta_quantity=delta_quantity,
            entry_plan=sizing.entry_plan,
            stop_plan=sizing.stop_plan,
            take_profit_plan=sizing.take_profit_plan,
            horizon=sizing.horizon,
            valid_from=sizing.valid_from,
            valid_until=sizing.valid_until,
            expected_return=expected_return,
            expected_risk=expected_risk,
            confidence=research.confidence,
            rationale=sizing.rationale,
            risk_reasoning=risk_reasoning,
            invalidation_conditions=research.invalidation_conditions,
            model_provenance=(
                ModelProvenance(
                    model_name="deterministic-investment-decision-engine",
                    model_version=self.ENGINE_VERSION,
                    provider="DSA",
                    prompt_hash=None,
                ),
            ),
        )

    @staticmethod
    def _validate_authorities(
        *,
        research: ResearchBundle,
        portfolio: PortfolioSnapshot,
        risk_policy: RiskPolicy,
        sizing: DecisionSizingInput,
    ) -> None:
        if portfolio.account_mode != "SIMULATION" or portfolio.simulation_only is not True:
            raise ValueError("P0 Brain only accepts authoritative simulation portfolios")
        if portfolio.reconciliation_status != "RECONCILED":
            raise ValueError("portfolio must be reconciled before a decision")
        if not risk_policy.applies_to(portfolio.account_id):
            raise ValueError("risk policy does not apply to the authoritative account")
        if not risk_policy.is_effective_at(sizing.valid_from):
            raise ValueError("risk policy is not effective for the decision")
        if (
            risk_policy.effective_until is not None
            and sizing.valid_until > risk_policy.effective_until
        ):
            raise ValueError("decision validity cannot outlive the risk policy")
        if research.symbol == "" or research.market == "":
            raise ValueError("research asset identity is required")
        if research.market not in risk_policy.allowed_markets:
            raise ValueError("market is not allowed by risk policy")
        if sizing.instrument not in risk_policy.allowed_instruments:
            raise ValueError("instrument is not allowed by risk policy")
        if _DATA_QUALITY_RANK[research.data_quality] < _DATA_QUALITY_RANK[risk_policy.min_data_quality]:
            raise ValueError("research data quality is below risk policy minimum")
        if _DATA_QUALITY_RANK[portfolio.data_quality] < _DATA_QUALITY_RANK[risk_policy.min_data_quality]:
            raise ValueError("portfolio data quality is below risk policy minimum")
        if research.as_of > sizing.valid_from or portfolio.as_of > sizing.valid_from:
            raise ValueError("decision inputs cannot be from the future")
        if sizing.created_at > sizing.valid_from:
            raise ValueError("decision created_at cannot be after valid_from")
        if sizing.valid_until <= sizing.valid_from:
            raise ValueError("decision validity window is invalid")
        if risk_policy.stop_required and sizing.stop_plan is None:
            raise ValueError("risk policy requires a stop plan")

    @staticmethod
    def _risk_capped_delta(
        *,
        equity: Decimal,
        risk_policy: RiskPolicy,
        sizing: DecisionSizingInput,
        fallback_delta: int,
    ) -> int:
        if sizing.stop_plan is None:
            return fallback_delta
        loss_per_share = sizing.entry_plan.limit_price - sizing.stop_plan.stop_price
        if loss_per_share <= 0:
            raise ValueError("stop price must be below entry limit price")
        risk_quantity = equity * risk_policy.risk_budget_per_trade / loss_per_share
        return _floor_lot(risk_quantity, sizing.lot_size)

    @staticmethod
    def _expected_risk(sizing: DecisionSizingInput) -> Decimal:
        if sizing.stop_plan is None:
            return Decimal("0")
        return (
            (sizing.entry_plan.limit_price - sizing.stop_plan.stop_price)
            / sizing.entry_plan.limit_price
        ).quantize(_WEIGHT_QUANTUM, rounding=ROUND_DOWN)

    @staticmethod
    def _risk_reasoning(
        *,
        requested_weight: Decimal,
        target_weight: Decimal,
        value_capped_delta: int,
        risk_capped_delta: int,
        lot_size: int,
        expected_return: Decimal,
    ) -> str:
        return (
            f"DSA Brain applied RiskPolicy before execution: requested_weight="
            f"{decimal_to_json(requested_weight)}, final_target_weight="
            f"{decimal_to_json(target_weight)}, value_cap_delta={value_capped_delta}, "
            f"risk_budget_delta={risk_capped_delta}, lot_size={lot_size}."
            f" expected_return={decimal_to_json(expected_return)}."
        )
