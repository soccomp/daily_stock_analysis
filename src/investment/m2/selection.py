"""Shared M2 research-object selection from Athena's portfolio snapshot.

The M2 scope is holdings-first, then screening candidates (the production
default research source), then a manual allowlist override.  This keeps the
upstream screening engine untouched: candidates are projected in by the caller
via the thin ``screening_candidates`` adapter.
"""

from __future__ import annotations

from typing import Any

from data_provider.base import canonical_stock_code, normalize_stock_code

from src.core.trading_calendar import get_market_for_stock
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot


def select_m2_research_objects(
    *,
    config: Any,
    snapshot: PortfolioSnapshot,
    screening_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return the holdings-first M2 scope with source lineage.

    Ordering: holdings, then screening candidates, then the manual allowlist
    (override).  ``screening_candidates`` items must already be projected to the
    research-object shape (``{"symbol", "source", ...lineage}``); the caller is
    responsible for freshness/dedup via the screening-candidate adapter.
    """

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

    screening: list[dict[str, Any]] = []
    for item in screening_candidates or ():
        if not isinstance(item, dict):
            continue
        symbol = _cn_symbol(item.get("symbol"))
        if not symbol or symbol in holding_symbols:
            continue
        scope = {**item, "symbol": symbol, "source": "SCREENING"}
        screening.append(scope)

    holding_set = set(holding_symbols)
    allowlist_set = set(allowlist)
    ordered_holdings: list[dict[str, Any]] = [
        {
            "symbol": symbol,
            "source": (
                "BOTH"
                if symbol in holding_set and symbol in allowlist_set
                else "HOLDING"
            ),
        }
        for symbol in holding_symbols
    ]
    ordered_allowlist: list[dict[str, Any]] = [
        {"symbol": symbol, "source": "ALLOWLIST"}
        for symbol in allowlist
        if symbol not in holding_set
        and all(scope["symbol"] != symbol for scope in screening)
    ]

    return (ordered_holdings + screening + ordered_allowlist)[:max_symbols]


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
