"""Deterministic P1 Brain-owned target sizing."""

from __future__ import annotations

from decimal import Decimal


def risk_budget_target_weight(
    *,
    entry_limit: Decimal,
    stop_price: Decimal,
    risk_budget_per_trade: Decimal,
    max_single_position_weight: Decimal,
) -> Decimal:
    """Return the risk-derived target weight, capped by policy maximum."""

    values = {
        "entry_limit": entry_limit,
        "stop_price": stop_price,
        "risk_budget_per_trade": risk_budget_per_trade,
        "max_single_position_weight": max_single_position_weight,
    }
    for field_name, value in values.items():
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError(f"{field_name} must be a finite Decimal")
    if entry_limit <= 0:
        raise ValueError("entry_limit must be positive")
    if stop_price <= 0 or stop_price >= entry_limit:
        raise ValueError("stop_price must be positive and below entry_limit")
    if risk_budget_per_trade <= 0 or risk_budget_per_trade > 1:
        raise ValueError("risk_budget_per_trade must be in (0, 1]")
    if max_single_position_weight <= 0 or max_single_position_weight > 1:
        raise ValueError("max_single_position_weight must be in (0, 1]")

    stop_loss_fraction = (entry_limit - stop_price) / entry_limit
    risk_target_weight = risk_budget_per_trade / stop_loss_fraction
    return min(risk_target_weight, max_single_position_weight)
