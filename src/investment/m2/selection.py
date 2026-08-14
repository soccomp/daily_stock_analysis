"""Shared M2 research-object selection from Athena's portfolio snapshot."""

from __future__ import annotations

from typing import Any

from data_provider.base import canonical_stock_code, normalize_stock_code

from src.core.trading_calendar import get_market_for_stock
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot


def select_m2_research_objects(*, config: Any, snapshot: PortfolioSnapshot) -> list[dict[str, str]]:
    """Return the established holdings-first M2 scope with source lineage."""

    max_symbols = min(50, max(1, int(getattr(config, "single_brain_m2_max_symbols", 10))))
    holdings_limit = min(
        50,
        max(0, int(getattr(config, "single_brain_m2_holdings_limit", 10))),
    )
    holding_symbols: list[str] = []
    for position in snapshot.positions:
        if position.quantity <= 0 or str(position.market).upper() != "CN":
            continue
        normalized = _cn_symbol(position.symbol)
        if normalized and normalized not in holding_symbols:
            holding_symbols.append(normalized)
        if len(holding_symbols) >= holdings_limit:
            break

    allowlist: list[str] = []
    for raw in getattr(config, "single_brain_m2_symbols", ()) or ():
        normalized = _cn_symbol(raw)
        if normalized and normalized not in allowlist:
            allowlist.append(normalized)

    ordered = (
        holding_symbols
        + [item for item in allowlist if item not in holding_symbols]
    )[:max_symbols]
    holding_set = set(holding_symbols)
    allowlist_set = set(allowlist)
    return [
        {
            "symbol": symbol,
            "source": (
                "BOTH"
                if symbol in holding_set and symbol in allowlist_set
                else "HOLDING"
                if symbol in holding_set
                else "ALLOWLIST"
            ),
        }
        for symbol in ordered
    ]


def _cn_symbol(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        normalized = canonical_stock_code(normalize_stock_code(raw))
    except Exception:
        return None
    if str(get_market_for_stock(normalized) or "").upper() != "CN":
        return None
    return normalized
