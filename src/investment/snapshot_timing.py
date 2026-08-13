"""Infrastructure-only timing rules for authoritative PortfolioSnapshots."""

from __future__ import annotations

from datetime import datetime, timedelta


# Cross-host clock budget. This is not an investment, RiskPolicy, or contract rule.
MAX_PORTFOLIO_SNAPSHOT_CLOCK_SKEW = timedelta(seconds=1)


def portfolio_snapshot_is_future_dated(
    *,
    as_of: datetime,
    reference_time: datetime,
) -> bool:
    """Return whether an authoritative snapshot exceeds the fixed skew budget."""

    return as_of - reference_time > MAX_PORTFOLIO_SNAPSHOT_CLOCK_SKEW
