from datetime import datetime, timezone

from api.v1.endpoints import mission3_operability
from src.services.mission3_operability import Mission3OperabilityService


class _Readiness:
    def get(self):
        return {
            "latest_cycle": {
                "decision_cycle_id": "cycle-1",
                "status": "NO_ACTION",
                "current_stage": "ATHENA_HANDOFF_ACK",
                "current_symbol_or_scope": "A_SHARE_UNIVERSE",
                "terminal_reason_code": "NO_CANDIDATE_OR_NO_ACTION_OUTCOME",
            },
            "recurring_scheduler": {"enabled": True, "mode": "PROPOSAL_HANDOFF", "next_run_at": "2026-08-24T06:00:00+00:00"},
        }


class _Health:
    def snapshot(self):
        return {"readiness": {"DSA_RESEARCH_READINESS": "READY"}}


class _Canonical:
    def scheduler_projection(self, *, scheduler_task_name):
        assert scheduler_task_name == "single_brain_proposal_handoff"
        return {
            "current_cycle_id": "canonical-cycle-1",
            "current_status": "RUNNING",
            "current_stage": "MARKET_REVIEW",
            "current_symbol_or_scope": "A_SHARE_UNIVERSE",
            "last_terminal_reason": None,
        }


def test_mission3_operability_is_read_only_and_keeps_canonical_facts():
    result = Mission3OperabilityService(
        readiness_service=_Readiness(), health_store=_Health(), canonical_repository=_Canonical(),
        clock=lambda: datetime(2026, 8, 24, 2, tzinfo=timezone.utc),
    ).get()

    assert result["read_only"] is True
    assert result["simulation_only"] is True
    assert result["LIVE_TRADING"] is False
    assert result["dsa_execution_authority"] is False
    assert result["dsa_research_readiness"] == "READY"
    assert result["canonical_cycle"]["current_cycle_id"] == "canonical-cycle-1"
    assert result["canonical_cycle"]["current_stage"] == "MARKET_REVIEW"
    assert result["recurring_scheduler"]["next_run_at"] == "2026-08-24T06:00:00+00:00"
    assert result["natural_work_admission"] == {
        "allowed": True,
        "reason_code": "LEGAL_TRADING_SESSION",
        "market_phase": "intraday",
        "observed_at": "2026-08-24T02:00:00+00:00",
        "source": "evaluate_natural_cycle_admission",
    }


def test_mission3_endpoint_injects_the_app_owned_scheduler(monkeypatch):
    scheduler = object()
    captured = {}

    class _Service:
        def __init__(self, *, runtime_scheduler):
            captured["runtime_scheduler"] = runtime_scheduler

        def get(self):
            return {"read_only": True}

    monkeypatch.setattr(mission3_operability, "Mission3OperabilityService", _Service)

    assert mission3_operability.get_operability(runtime_scheduler=scheduler) == {
        "read_only": True,
    }
    assert captured["runtime_scheduler"] is scheduler


def test_mission3_scheduler_fields_match_direct_readiness_projection(monkeypatch):
    class _Repository:
        def readiness(self):
            return {"latest_cycle": None, "symbols": []}

        def latest_authoritative_snapshot(self):
            return None

    class _M3Repository:
        def readiness(self):
            return {"pending_execution_count": 0}

    class _Scheduler:
        def status(self):
            return {
                "enabled": True,
                "mode": "PROPOSAL_HANDOFF_ONLY",
                "background_tasks": [{
                    "name": "single_brain_proposal_handoff",
                    "interval_seconds": 3600,
                    "next_run_at": "2026-08-25T12:54:39+00:00",
                }],
            }

    monkeypatch.setattr(
        "src.services.single_brain_m2_readiness_service.get_config",
        lambda: type(
            "_Config",
            (),
            {"single_brain_m2_enabled": True, "single_brain_execution_mode": "SHADOW"},
        )(),
    )
    from src.services.single_brain_m2_readiness_service import (
        SingleBrainM2ReadinessService,
    )

    readiness = SingleBrainM2ReadinessService(
        repository=_Repository(),
        runtime_scheduler=_Scheduler(),
        m3_repository=_M3Repository(),
    )
    direct = readiness.get()["recurring_scheduler"]

    class _Health:
        def snapshot(self):
            return {"readiness": {"DSA_RESEARCH_READINESS": "READY"}}

    observed = Mission3OperabilityService(
        readiness_service=readiness,
        health_store=_Health(),
        clock=lambda: datetime(2026, 8, 25, 4, tzinfo=timezone.utc),
    ).get()["recurring_scheduler"]

    assert {
        key: observed[key]
        for key in ("enabled", "mode", "next_run_at")
    } == {
        key: direct[key]
        for key in ("enabled", "mode", "next_run_at")
    }
