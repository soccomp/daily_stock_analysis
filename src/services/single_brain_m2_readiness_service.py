"""Observational readiness projection for Single Brain M2."""

from __future__ import annotations

from src.config import get_config
from src.investment.m2.repository import M2OperationalRepository
from src.investment.m3.repository import M3ExecutionRepository
from src.services.runtime_scheduler import RuntimeSchedulerService
from src.storage import DatabaseManager


class SingleBrainM2ReadinessService:
    """Read M2 operational facts; it cannot mutate or initiate work."""

    def __init__(
        self,
        *,
        repository: M2OperationalRepository | None = None,
        db_manager: DatabaseManager | None = None,
        runtime_scheduler: RuntimeSchedulerService | None = None,
        m3_repository: M3ExecutionRepository | None = None,
    ) -> None:
        self._repository = repository or M2OperationalRepository(db_manager)
        self._runtime_scheduler = runtime_scheduler
        self._m3_repository = m3_repository or M3ExecutionRepository(db_manager)

    def _recurring_scheduler(self) -> dict:
        if self._runtime_scheduler is None:
            return {
                "enabled": False,
                "mode": "OFF",
                "authority_count": 0,
                "interval_seconds": None,
                "next_run_at": None,
            }
        status = self._runtime_scheduler.status()
        tasks = [
            task
            for task in status.get("background_tasks", [])
            if task.get("name") in {
                "single_brain_m2_shadow",
                "single_brain_m3_simulation_execution",
            }
        ]
        task = tasks[0] if len(tasks) == 1 else None
        return {
            "enabled": bool(status.get("enabled")) and task is not None,
            "mode": status.get("mode", "OFF"),
            "authority_count": len(tasks),
            "interval_seconds": task.get("interval_seconds") if task else None,
            "next_run_at": task.get("next_run_at") if task else None,
        }

    def get(self) -> dict:
        config = get_config()
        execution_mode = str(
            getattr(config, "single_brain_execution_mode", "SHADOW")
        ).strip().upper()
        execution_authorized = (
            bool(getattr(config, "single_brain_m2_enabled", False))
            and execution_mode == "SIMULATION_EXECUTION"
            and bool(
                getattr(
                    config,
                    "single_brain_simulation_execution_authorized",
                    False,
                )
            )
        )
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
            "mission": (
                "SINGLE_BRAIN_M3"
                if execution_mode == "SIMULATION_EXECUTION"
                else "SINGLE_BRAIN_M2"
            ),
            "feature_enabled": bool(getattr(config, "single_brain_m2_enabled", False)),
            "execution_mode": execution_mode,
            "execution_authorization": "ON" if execution_authorized else "OFF",
            "portfolio_authority": "ATHENA_RUNTIME",
            "recurring_scheduler": self._recurring_scheduler(),
            "latest_authoritative_snapshot": snapshot,
            "simulation_execution": self._m3_repository.readiness(),
            **operational,
        }
