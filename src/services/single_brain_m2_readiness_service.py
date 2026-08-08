"""Observational readiness projection for Single Brain M2."""

from __future__ import annotations

from src.config import get_config
from src.investment.m2.repository import M2OperationalRepository
from src.storage import DatabaseManager


class SingleBrainM2ReadinessService:
    """Read M2 operational facts; it cannot mutate or initiate work."""

    def __init__(
        self,
        *,
        repository: M2OperationalRepository | None = None,
        db_manager: DatabaseManager | None = None,
    ) -> None:
        self._repository = repository or M2OperationalRepository(db_manager)

    def get(self) -> dict:
        operational = self._repository.readiness()
        canonical_snapshot = self._repository.latest_authoritative_snapshot()
        snapshot = None
        if canonical_snapshot is not None:
            snapshot = {
                "snapshot_id": canonical_snapshot.snapshot_id,
                "content_hash": canonical_snapshot.content_hash,
                "as_of": canonical_snapshot.as_of,
                "reconciliation_status": canonical_snapshot.reconciliation_status,
                "source": canonical_snapshot.source,
                "authoritative": canonical_snapshot.authoritative,
                "read_only": canonical_snapshot.read_only,
            }
        return {
            "mission": "SINGLE_BRAIN_M2",
            "feature_enabled": bool(getattr(get_config(), "single_brain_m2_enabled", False)),
            "execution_authorization": "OFF",
            "portfolio_authority": "ATHENA_RUNTIME",
            "latest_authoritative_snapshot": snapshot,
            **operational,
        }
