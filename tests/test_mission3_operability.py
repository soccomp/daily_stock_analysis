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
        readiness_service=_Readiness(), health_store=_Health(), canonical_repository=_Canonical()
    ).get()

    assert result["read_only"] is True
    assert result["simulation_only"] is True
    assert result["LIVE_TRADING"] is False
    assert result["dsa_execution_authority"] is False
    assert result["dsa_research_readiness"] == "READY"
    assert result["canonical_cycle"]["current_cycle_id"] == "canonical-cycle-1"
    assert result["canonical_cycle"]["current_stage"] == "MARKET_REVIEW"
    assert result["recurring_scheduler"]["next_run_at"] == "2026-08-24T06:00:00+00:00"
