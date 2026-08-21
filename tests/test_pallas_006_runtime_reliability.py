from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.investment.contracts.data_evidence import analysis_context_evidence
from src.services.single_brain_m2_readiness_service import (
    SingleBrainM2ReadinessService,
)
from src.storage import (
    AnalysisHistory,
    DatabaseManager,
    ResearchTriggerLedgerRecord,
)


def _config():
    return SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_execution_mode="PROPOSAL_HANDOFF",
        single_brain_simulation_execution_authorized=False,
    )


class _StaleShadowRepository:
    def readiness(self):
        return {
            "latest_cycle": {
                "decision_cycle_id": "stale-shadow-cycle",
                "status": "COMPLETED",
            },
            "latest_completed_cycle": None,
            "symbols": [],
        }

    def latest_authoritative_snapshot(self):
        return object()


class _ProposalHandoffScheduler:
    def status(self):
        return {
            "enabled": True,
            "mode": "PROPOSAL_HANDOFF_ONLY",
            "background_tasks": [{
                "name": "single_brain_proposal_handoff",
                "interval_seconds": 3600,
                "next_run_at": "2026-08-21T10:00:00Z",
            }],
        }


def test_proposal_handoff_readiness_does_not_project_stale_m2_shadow_state(
    tmp_path, monkeypatch,
):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'pallas-006.db'}")
    now = datetime(2026, 8, 21, 9, 30)
    with db.session_scope() as session:
        analysis = AnalysisHistory(
            query_id="m2-analysis-cycle-600519",
            code="600519",
            raw_result="{}",
            context_snapshot="{}",
            created_at=now,
        )
        session.add(analysis)
        session.add(ResearchTriggerLedgerRecord(
            research_trigger_id="research-trigger-pallas-006",
            trigger_type="SCHEDULED_HOLDING_REVIEW",
            trigger_source="proposal-handoff",
            symbol="600519",
            market="CN",
            priority=10,
            created_at=now,
            source_event_time=now,
            effective_at=now,
            scheduled_for=now,
            dedup_key="pallas-006:600519",
            policy_version="pallas-004-v1",
            evidence_refs_json="[]",
            content_hash="a" * 64,
            status="PROCESSED",
            processed_at=now,
            created_at_ledger=now,
            last_seen_at=now,
        ))

    monkeypatch.setattr(
        "src.services.single_brain_m2_readiness_service.get_config",
        lambda: _config(),
    )
    try:
        readiness = SingleBrainM2ReadinessService(
            repository=_StaleShadowRepository(),
            db_manager=db,
            runtime_scheduler=_ProposalHandoffScheduler(),
        ).get()
    finally:
        DatabaseManager.reset_instance()

    assert readiness["latest_cycle"] is None
    assert readiness["latest_authoritative_snapshot"] is None
    assert readiness["latest_cycle_diagnostics"] is None
    projection = readiness["proposal_handoff_persistence"]
    assert projection["projection_scope"] == "PROPOSAL_HANDOFF"
    assert projection["shadow_projection"] == "NOT_CURRENT"
    assert projection["read_status"] == "AVAILABLE"
    assert projection["latest_analysis"]["source_report_id"] == 1
    assert projection["latest_processed_trigger"]["research_trigger_id"] == (
        "research-trigger-pallas-006"
    )


def test_analysis_evidence_marks_partial_and_missing_blocks_degraded():
    evidence = analysis_context_evidence(
        context_snapshot={
            "analysis_context_pack_overview": {
                "blocks": [
                    {"key": "quote", "status": "available"},
                    {"key": "technical", "status": "partial"},
                    {"key": "chip", "status": "missing"},
                ],
                "data_quality": {"level": "good"},
                "warnings": ["intraday_realtime_overlay"],
            },
        },
        source_report_id=101,
        now=datetime(2026, 8, 21, 9, 30, tzinfo=timezone.utc),
    )

    assert evidence.availability_status == "DEGRADED"
    assert "EXPLICIT_HIGH" in evidence.quality_flags
    assert "BLOCK_PARTIAL:technical" in evidence.quality_flags
    assert "BLOCK_MISSING:chip" in evidence.quality_flags
    assert "WARNING:intraday_realtime_overlay" in evidence.quality_flags
