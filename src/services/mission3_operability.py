"""Read-only Mission-3 Owner operability facts owned by DSA."""

from __future__ import annotations

from typing import Any

from src.services.dependency_health import get_dependency_health_store
from src.services.single_brain_m2_readiness_service import SingleBrainM2ReadinessService


class Mission3OperabilityService:
    """Expose DSA facts without starting a cycle or refreshing a provider."""

    def __init__(self, *, readiness_service=None, health_store=None, canonical_repository=None):
        self._readiness = readiness_service or SingleBrainM2ReadinessService()
        self._health = health_store or get_dependency_health_store()
        self._canonical = canonical_repository

    def get(self) -> dict[str, Any]:
        readiness = dict(self._readiness.get())
        health = dict(self._health.snapshot())
        current = readiness.get("latest_cycle") or {}
        if self._canonical is not None:
            try:
                candidate = dict(self._canonical.scheduler_projection(
                    scheduler_task_name="single_brain_proposal_handoff"
                ))
                if candidate.get("current_cycle_id") or candidate.get("last_terminal_cycle_id"):
                    current = candidate
            except Exception:
                current = current
        else:
            try:
                from src.investment.canonical_cycle import CanonicalCycleRepository

                candidate = dict(CanonicalCycleRepository().scheduler_projection(
                    scheduler_task_name="single_brain_proposal_handoff"
                ))
                if candidate.get("current_cycle_id") or candidate.get("last_terminal_cycle_id"):
                    current = candidate
            except Exception:
                current = current
        scheduler = readiness.get("recurring_scheduler") or {}
        dsa_readiness = (health.get("readiness") or {}).get("DSA_RESEARCH_READINESS")
        return {
            "schema_version": 1,
            "read_only": True,
            "simulation_only": True,
            "LIVE_TRADING": False,
            "dsa_execution_authority": False,
            "dsa_research_readiness": dsa_readiness,
            "canonical_cycle": {
                "current_cycle_id": current.get("current_cycle_id") or current.get("decision_cycle_id") or current.get("cycle_id"),
                "current_status": current.get("current_status") or current.get("status"),
                "current_stage": current.get("current_stage"),
                "current_symbol_or_scope": current.get("current_symbol_or_scope"),
                "last_terminal_reason": current.get("last_terminal_reason", current.get("terminal_reason_code")),
            },
            "recurring_scheduler": {
                "enabled": scheduler.get("enabled"),
                "mode": scheduler.get("mode"),
                "next_run_at": scheduler.get("next_run_at"),
            },
            "source": "DSA_SINGLE_BRAIN_READINESS_AND_DEPENDENCY_STORE",
        }


__all__ = ["Mission3OperabilityService"]
