"""Observational readiness projection for Single Brain M2."""

from __future__ import annotations

from src.config import get_config
from src.investment.m2.repository import M2OperationalRepository
from src.investment.m2.runtime_diagnostics import classify_runtime_failure
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
                "single_brain_proposal_handoff",
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
        latest_cycle_diagnostics = self._latest_cycle_diagnostics(
            operational.get("latest_cycle")
        )
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
                "ISSUE_9_PROPOSAL_HANDOFF"
                if execution_mode == "PROPOSAL_HANDOFF"
                else "SINGLE_BRAIN_M3"
                if execution_mode == "SIMULATION_EXECUTION"
                else "SINGLE_BRAIN_M2"
            ),
            "feature_enabled": bool(getattr(config, "single_brain_m2_enabled", False)),
            "execution_mode": execution_mode,
            "execution_authorization": "ON" if execution_authorized else "OFF",
            "portfolio_authority": "ATHENA_RUNTIME",
            "allocation_authority": "ATHENA_RUNTIME",
            "mandate_authority": "ATHENA_RUNTIME",
            "dsa_authority_boundary": "RESEARCH_AND_PROPOSAL_ONLY",
            "recurring_scheduler": self._recurring_scheduler(),
            "latest_authoritative_snapshot": snapshot,
            "simulation_execution": {
                **self._m3_repository.readiness(),
                "authoritative": execution_mode != "PROPOSAL_HANDOFF",
                "legacy_runtime_disabled": execution_mode == "PROPOSAL_HANDOFF",
            },
            "latest_cycle_diagnostics": latest_cycle_diagnostics,
            **operational,
        }

    def _latest_cycle_diagnostics(self, latest_cycle: dict | None) -> dict | None:
        if not latest_cycle:
            return None
        cycle_id = str(latest_cycle.get("decision_cycle_id") or "").strip()
        cycle_symbols = ()
        symbol_reader = getattr(self._repository, "cycle_symbols", None)
        if cycle_id and callable(symbol_reader):
            cycle_symbols = tuple(symbol_reader(cycle_id))

        research_completed_count = sum(
            item.get("source_report_id") is not None for item in cycle_symbols
        )
        decision_count = sum(bool(item.get("decision_id")) for item in cycle_symbols)
        expected_symbol_count = len(cycle_symbols)
        research_completed = (
            expected_symbol_count > 0
            and research_completed_count == expected_symbol_count
        )

        execution = None
        execution_reader = getattr(self._m3_repository, "readiness_for_cycle", None)
        if cycle_id and callable(execution_reader):
            execution = execution_reader(cycle_id)
        if execution is None:
            execution = {
                "mandate_count": 0 if decision_count == 0 else None,
                "dispatch_attempt_count": 0 if decision_count == 0 else None,
                "broker_submission_state": "NONE" if decision_count == 0 else "UNKNOWN",
                "recorded_submitted_quantity": 0 if decision_count == 0 else None,
            }

        explanation = classify_runtime_failure(
            (
                latest_cycle.get("failure_reason"),
                *(item.get("failure_reason") for item in cycle_symbols),
            ),
            research_incomplete=(
                latest_cycle.get("status") == "FAILED_CLOSED"
                and not research_completed
            ),
        )
        return {
            "decision_cycle_id": cycle_id,
            "status": latest_cycle.get("status"),
            "failure_stage": (
                explanation.stage
                if latest_cycle.get("status") in {"FAILED", "FAILED_CLOSED"}
                else None
            ),
            "failure_code": (
                explanation.code
                if latest_cycle.get("status") in {"FAILED", "FAILED_CLOSED"}
                else None
            ),
            "failure_summary": (
                explanation.summary
                if latest_cycle.get("status") in {"FAILED", "FAILED_CLOSED"}
                else None
            ),
            "expected_symbol_count": expected_symbol_count,
            "research_completed_count": research_completed_count,
            "research_completed": research_completed,
            "decision_count": decision_count,
            "decision_created": decision_count > 0,
            "mandate_count": execution.get("mandate_count"),
            "mandate_created": (
                None
                if execution.get("mandate_count") is None
                else int(execution.get("mandate_count") or 0) > 0
            ),
            "dispatch_attempt_count": execution.get("dispatch_attempt_count"),
            "broker_submission_state": execution.get("broker_submission_state"),
            "recorded_submitted_quantity": execution.get("recorded_submitted_quantity"),
        }
