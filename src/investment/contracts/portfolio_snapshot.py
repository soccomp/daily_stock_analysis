"""Athena-owned authoritative PortfolioSnapshot contract consumed by DSA."""

from __future__ import annotations

from typing import ClassVar, Literal, Mapping

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, model_validator
from typing_extensions import Self

from .base import CanonicalContract, CanonicalDecimal, DataQuality, FrozenValue, StrictTrue


class Position(FrozenValue):
    symbol: StrictStr = Field(min_length=1, max_length=64)
    market: StrictStr = Field(min_length=1, max_length=32)
    quantity: StrictInt = Field(ge=0)
    available_quantity: StrictInt = Field(ge=0)
    avg_cost: CanonicalDecimal = Field(ge=0)
    last_price: CanonicalDecimal = Field(ge=0)
    market_value: CanonicalDecimal = Field(ge=0)
    unrealized_pnl: CanonicalDecimal
    price_as_of: AwareDatetime
    price_source: StrictStr = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _available_quantity_is_bounded(self) -> Self:
        if self.available_quantity > self.quantity:
            raise ValueError("available_quantity cannot exceed quantity")
        return self


class ActiveOrder(FrozenValue):
    broker_order_id: StrictStr = Field(min_length=1, max_length=160)
    symbol: StrictStr = Field(min_length=1, max_length=64)
    side: Literal["BUY", "SELL"]
    quantity: StrictInt = Field(gt=0)
    filled_quantity: StrictInt = Field(ge=0)
    remaining_quantity: StrictInt = Field(ge=0)
    state: Literal[
        "ACCEPTED",
        "ACTIVE",
        "PARTIALLY_FILLED",
        "UNKNOWN",
    ]
    reserved_cash: CanonicalDecimal = Field(ge=0)
    submitted_at: AwareDatetime

    @model_validator(mode="after")
    def _quantities_balance(self) -> Self:
        if self.filled_quantity + self.remaining_quantity != self.quantity:
            raise ValueError("active order quantities must balance")
        return self


class PortfolioSnapshot(CanonicalContract):
    """Read-only broker/runtime-observed account truth."""

    BUILD_DEFAULTS: ClassVar[Mapping[str, object]] = {
        "schema_version": "1.0",
        "source": "ATHENA_RUNTIME",
        "authoritative": True,
        "read_only": True,
        "simulation_only": True,
        "positions": (),
        "active_orders": (),
        "limitations": (),
    }

    schema_version: Literal["1.0"]
    snapshot_id: StrictStr = Field(min_length=1, max_length=160)
    account_id: StrictStr = Field(min_length=1, max_length=160)
    broker: StrictStr = Field(min_length=1, max_length=128)
    account_mode: Literal["SIMULATION", "PAPER", "LIVE"]
    source: Literal["ATHENA_RUNTIME"]
    authoritative: StrictTrue
    read_only: StrictTrue
    simulation_only: StrictTrue
    as_of: AwareDatetime
    revision: StrictInt = Field(ge=0)
    currency: StrictStr = Field(min_length=3, max_length=8)

    equity: CanonicalDecimal = Field(ge=0)
    cash: CanonicalDecimal = Field(ge=0)
    available_cash: CanonicalDecimal = Field(ge=0)
    reserved_cash: CanonicalDecimal = Field(ge=0)
    positions: tuple[Position, ...]
    active_orders: tuple[ActiveOrder, ...]
    realized_pnl: CanonicalDecimal
    unrealized_pnl: CanonicalDecimal

    reconciliation_status: Literal[
        "RECONCILED",
        "PENDING_RECONCILIATION",
        "DEGRADED",
        "UNKNOWN",
    ]
    data_quality: DataQuality
    limitations: tuple[StrictStr, ...]
    broker_snapshot_ref: StrictStr = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def _snapshot_semantics(self) -> Self:
        if self.available_cash > self.cash:
            raise ValueError("available_cash cannot exceed cash")
        if self.available_cash + self.reserved_cash > self.cash:
            raise ValueError("available_cash plus reserved_cash cannot exceed cash")
        position_keys = [(position.market, position.symbol) for position in self.positions]
        if len(position_keys) != len(set(position_keys)):
            raise ValueError("positions must be unique by market and symbol")
        order_ids = [order.broker_order_id for order in self.active_orders]
        if len(order_ids) != len(set(order_ids)):
            raise ValueError("active_orders must have unique broker_order_id values")
        if any(not item.strip() for item in self.limitations):
            raise ValueError("limitations cannot contain blank values")
        return self

    def position_for(self, *, symbol: str, market: str) -> Position | None:
        return next(
            (
                position
                for position in self.positions
                if position.symbol == symbol and position.market == market
            ),
            None,
        )
