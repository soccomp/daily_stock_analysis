"""Read-only projection of Athena authoritative account truth for DSA UI."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import get_config
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.integration.runtime_snapshot_ingress import (
    CanonicalHttpPortfolioSnapshotSource,
    PortfolioSnapshotSource,
    SnapshotIngressError,
)
from src.investment.snapshot_timing import (
    MAX_PORTFOLIO_SNAPSHOT_CLOCK_SKEW,
    portfolio_snapshot_is_future_dated,
)


class ConnectedPortfolioSnapshotUnavailable(RuntimeError):
    """The connected account cannot be proven safe to display."""


class ConnectedPortfolioSnapshotService:
    """Capture one canonical Snapshot without touching either portfolio ledger."""

    MAX_SNAPSHOT_AGE = timedelta(minutes=5)
    # Compatibility alias; the shared authority timing module owns this budget.
    MAX_SNAPSHOT_CLOCK_SKEW = MAX_PORTFOLIO_SNAPSHOT_CLOCK_SKEW

    def __init__(
        self,
        *,
        config: Any | None = None,
        snapshot_source: PortfolioSnapshotSource | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config or get_config()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if snapshot_source is not None:
            self._snapshot_source = snapshot_source
            return

        url = str(
            getattr(self._config, "single_brain_m2_snapshot_url", "") or ""
        ).strip()
        if not url:
            raise ConnectedPortfolioSnapshotUnavailable(
                "authoritative connected account endpoint is not configured"
            )
        try:
            self._snapshot_source = CanonicalHttpPortfolioSnapshotSource(
                url=url,
                timeout_seconds=float(
                    getattr(
                        self._config,
                        "single_brain_m2_snapshot_timeout_seconds",
                        5.0,
                    )
                ),
                clock=self._clock,
            )
        except (TypeError, ValueError) as exc:
            raise ConnectedPortfolioSnapshotUnavailable(
                "authoritative connected account endpoint is invalid"
            ) from exc

    def get(self) -> dict[str, Any]:
        """Return the exact canonical object inside an observational envelope."""

        try:
            snapshot = self._snapshot_source.capture_snapshot()
        except SnapshotIngressError as exc:
            raise ConnectedPortfolioSnapshotUnavailable(
                "authoritative connected account is unavailable"
            ) from exc
        except Exception as exc:
            raise ConnectedPortfolioSnapshotUnavailable(
                "authoritative connected account could not be validated"
            ) from exc

        received_at = getattr(
            self._snapshot_source,
            "last_response_received_at",
            None,
        )
        if received_at is None:
            received_at = self._clock()
        self._validate(snapshot=snapshot, received_at=received_at)
        return {"item": json.loads(snapshot.canonical_json())}

    def _validate(
        self,
        *,
        snapshot: PortfolioSnapshot,
        received_at: datetime,
    ) -> None:
        if not isinstance(snapshot, PortfolioSnapshot):
            raise ConnectedPortfolioSnapshotUnavailable(
                "canonical PortfolioSnapshot is required"
            )
        if (
            snapshot.source != "ATHENA_RUNTIME"
            or snapshot.authoritative is not True
            or snapshot.read_only is not True
        ):
            raise ConnectedPortfolioSnapshotUnavailable(
                "connected account authority semantics are invalid"
            )
        if (
            snapshot.account_mode != "SIMULATION"
            or snapshot.simulation_only is not True
        ):
            raise ConnectedPortfolioSnapshotUnavailable(
                "connected account is not simulation-only"
            )
        expected_account_id = str(
            getattr(self._config, "single_brain_m2_account_id", "") or ""
        ).strip()
        if not expected_account_id or snapshot.account_id != expected_account_id:
            raise ConnectedPortfolioSnapshotUnavailable(
                "connected account identity cannot be verified"
            )
        if (
            snapshot.as_of.utcoffset() != timedelta(0)
            or snapshot.created_at.utcoffset() != timedelta(0)
        ):
            raise ConnectedPortfolioSnapshotUnavailable(
                "connected account timestamps must be UTC"
            )
        if (
            not isinstance(received_at, datetime)
            or received_at.tzinfo is None
            or received_at.utcoffset() is None
        ):
            raise ConnectedPortfolioSnapshotUnavailable(
                "connected account receipt clock must be timezone-aware"
            )
        received_at = received_at.astimezone(timezone.utc)
        if portfolio_snapshot_is_future_dated(
            as_of=snapshot.as_of,
            reference_time=received_at,
        ):
            raise ConnectedPortfolioSnapshotUnavailable(
                "connected account snapshot is future-dated"
            )
        freshness_age = max(timedelta(0), received_at - snapshot.as_of)
        if freshness_age > self.MAX_SNAPSHOT_AGE:
            raise ConnectedPortfolioSnapshotUnavailable(
                "connected account snapshot is stale"
            )
