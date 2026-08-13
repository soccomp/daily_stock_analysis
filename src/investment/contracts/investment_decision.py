"""The sole DSA-owned InvestmentDecision contract."""

from __future__ import annotations

from typing import ClassVar, Literal, Mapping

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, model_validator
from typing_extensions import Self

from .base import CanonicalContract, CanonicalDecimal, FrozenValue
from .research_bundle import ModelProvenance


class EntryPlan(FrozenValue):
    order_type: Literal["LIMIT"] = "LIMIT"
    limit_price: CanonicalDecimal = Field(gt=0)
    price_floor: CanonicalDecimal | None = Field(default=None, gt=0)
    price_ceiling: CanonicalDecimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _price_bounds(self) -> Self:
        if self.price_floor is not None and self.price_ceiling is not None:
            if self.price_floor > self.price_ceiling:
                raise ValueError("entry price_floor cannot exceed price_ceiling")
        if self.price_floor is not None and self.limit_price < self.price_floor:
            raise ValueError("limit_price cannot be below price_floor")
        if self.price_ceiling is not None and self.limit_price > self.price_ceiling:
            raise ValueError("limit_price cannot exceed price_ceiling")
        return self


class StopPlan(FrozenValue):
    stop_price: CanonicalDecimal = Field(gt=0)
    trigger: Literal["PRICE"] = "PRICE"


class TakeProfitPlan(FrozenValue):
    target_price: CanonicalDecimal = Field(gt=0)
    method: Literal["PRICE"] = "PRICE"


class InvestmentDecision(CanonicalContract):
    """Final account action and quantity; no downstream layer may resize it."""

    BUILD_DEFAULTS: ClassVar[Mapping[str, object]] = {
        "schema_version": "1.0",
        "entry_plan": None,
        "stop_plan": None,
        "take_profit_plan": None,
        "invalidation_conditions": (),
        "supersedes_decision_id": None,
    }

    schema_version: Literal["1.0"]
    decision_id: StrictStr = Field(min_length=1, max_length=160)
    decision_cycle_id: StrictStr = Field(min_length=1, max_length=160)
    account_id: StrictStr = Field(min_length=1, max_length=160)
    symbol: StrictStr = Field(min_length=1, max_length=64)
    market: StrictStr = Field(min_length=1, max_length=32)
    action: Literal["BUY", "ADD", "HOLD"]

    research_ids: tuple[StrictStr, ...] = Field(min_length=1)
    portfolio_snapshot_id: StrictStr = Field(min_length=1, max_length=160)
    portfolio_snapshot_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    risk_policy_id: StrictStr = Field(min_length=1, max_length=160)
    risk_policy_version: StrictStr = Field(min_length=1, max_length=64)

    current_quantity: StrictInt = Field(ge=0)
    current_weight: CanonicalDecimal = Field(ge=0, le=1)
    target_quantity: StrictInt = Field(ge=0)
    target_weight: CanonicalDecimal = Field(ge=0, le=1)
    delta_quantity: StrictInt = Field(ge=0)

    # HOLD is an account-level no-change decision and has no executable entry.
    # Existing stored decisions with a legacy entry plan remain valid/readable.
    entry_plan: EntryPlan | None
    stop_plan: StopPlan | None
    take_profit_plan: TakeProfitPlan | None
    horizon: StrictStr = Field(min_length=1, max_length=64)
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    expected_return: CanonicalDecimal
    expected_risk: CanonicalDecimal = Field(ge=0)
    confidence: CanonicalDecimal = Field(ge=0, le=1)
    rationale: StrictStr = Field(min_length=1)
    risk_reasoning: StrictStr = Field(min_length=1)
    invalidation_conditions: tuple[StrictStr, ...]
    model_provenance: tuple[ModelProvenance, ...] = Field(min_length=1)
    supersedes_decision_id: StrictStr | None = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def _decision_semantics(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if self.target_quantity - self.current_quantity != self.delta_quantity:
            raise ValueError("delta_quantity must equal target_quantity minus current_quantity")
        if self.action == "BUY" and not (
            self.current_quantity == 0 and self.delta_quantity > 0
        ):
            raise ValueError("BUY requires an empty current position and positive delta_quantity")
        if self.action == "ADD" and not (
            self.current_quantity > 0 and self.delta_quantity > 0
        ):
            raise ValueError("ADD requires an existing position and positive delta_quantity")
        if self.action in {"BUY", "ADD"} and self.entry_plan is None:
            raise ValueError("BUY/ADD requires an entry plan")
        if self.entry_plan is None and (
            self.stop_plan is not None or self.take_profit_plan is not None
        ):
            raise ValueError("stop and take-profit plans require an entry plan")
        if self.action == "HOLD" and not (
            self.delta_quantity == 0 and self.target_quantity == self.current_quantity
        ):
            raise ValueError("HOLD cannot change quantity")
        if (
            self.entry_plan is not None
            and self.stop_plan is not None
            and self.stop_plan.stop_price >= self.entry_plan.limit_price
        ):
            raise ValueError("P0 BUY/ADD stop price must be below entry limit price")
        if self.entry_plan is not None and self.take_profit_plan is not None:
            if self.take_profit_plan.target_price <= self.entry_plan.limit_price:
                raise ValueError("P0 take-profit target must be above entry limit price")
        if len(self.research_ids) != len(set(self.research_ids)):
            raise ValueError("research_ids cannot contain duplicates")
        if any(not item.strip() for item in self.invalidation_conditions):
            raise ValueError("invalidation_conditions cannot contain blank values")
        if (
            self.supersedes_id is not None
            and self.supersedes_decision_id is not None
            and self.supersedes_id != self.supersedes_decision_id
        ):
            raise ValueError("supersedes decision identifiers must agree")
        return self
