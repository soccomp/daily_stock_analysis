"""Owner/system-owned RiskPolicy contract consumed by the DSA Brain."""

from __future__ import annotations

from typing import ClassVar, Literal, Mapping

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StrictStr, model_validator
from typing_extensions import Self

from .base import CanonicalContract, CanonicalDecimal, DataQuality


class RiskPolicy(CanonicalContract):
    """Capital-allocation constraints applied only by the decision layer."""

    BUILD_DEFAULTS: ClassVar[Mapping[str, object]] = {
        "schema_version": "1.0",
        "effective_until": None,
        "max_sector_weight": None,
        "max_strategy_weight": None,
        "max_turnover_per_window": None,
        "max_portfolio_drawdown": None,
        "liquidity_floor": None,
        "position_sizing_method": "TARGET_WEIGHT",
        "stop_required": True,
    }

    schema_version: Literal["1.0"]
    policy_id: StrictStr = Field(min_length=1, max_length=160)
    policy_version: StrictStr = Field(min_length=1, max_length=64)
    account_scope: tuple[StrictStr, ...] = Field(min_length=1)
    effective_from: AwareDatetime
    effective_until: AwareDatetime | None

    max_single_position_weight: CanonicalDecimal = Field(gt=0, le=1)
    max_sector_weight: CanonicalDecimal | None = Field(gt=0, le=1)
    max_total_exposure: CanonicalDecimal = Field(gt=0, le=1)
    min_cash_weight: CanonicalDecimal = Field(ge=0, lt=1)
    risk_budget_per_trade: CanonicalDecimal = Field(gt=0, le=1)
    max_strategy_weight: CanonicalDecimal | None = Field(gt=0, le=1)
    max_turnover_per_window: CanonicalDecimal | None = Field(gt=0)
    max_portfolio_drawdown: CanonicalDecimal | None = Field(gt=0, le=1)
    max_concurrent_positions: StrictInt = Field(gt=0)

    liquidity_floor: CanonicalDecimal | None = Field(ge=0)
    min_data_quality: DataQuality
    allowed_markets: tuple[StrictStr, ...] = Field(min_length=1)
    allowed_instruments: tuple[StrictStr, ...] = Field(min_length=1)
    position_sizing_method: Literal["TARGET_WEIGHT"]
    stop_required: StrictBool

    @model_validator(mode="after")
    def _policy_semantics(self) -> Self:
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        if self.max_single_position_weight > self.max_total_exposure:
            raise ValueError("max_single_position_weight cannot exceed max_total_exposure")
        if self.max_total_exposure + self.min_cash_weight > 1:
            raise ValueError("max_total_exposure plus min_cash_weight cannot exceed one")
        if self.risk_budget_per_trade > self.max_single_position_weight:
            raise ValueError("risk_budget_per_trade cannot exceed max_single_position_weight")
        for field_name in ("account_scope", "allowed_markets", "allowed_instruments"):
            values = getattr(self, field_name)
            if any(not value.strip() for value in values):
                raise ValueError(f"{field_name} cannot contain blank values")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} cannot contain duplicates")
        return self

    def applies_to(self, account_id: str) -> bool:
        return "*" in self.account_scope or account_id in self.account_scope

    def is_effective_at(self, timestamp: AwareDatetime) -> bool:
        return self.effective_from <= timestamp and (
            self.effective_until is None or timestamp < self.effective_until
        )
