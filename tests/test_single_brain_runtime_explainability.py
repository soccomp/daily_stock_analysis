"""Read-only runtime-reason projection for the Single Brain operator surface."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.investment.m2.runtime_diagnostics import (
    analysis_failure_marker,
    classify_runtime_failure,
)
from src.investment.m3.repository import M3ExecutionRepository
from src.services.single_brain_m2_readiness_service import (
    SingleBrainM2ReadinessService,
)
from src.storage import DatabaseManager, SingleBrainM3ExecutionRecord


class _Repository:
    def __init__(self, *, reason: str, symbol_reason: str | None = None):
        self._reason = reason
        self._symbol_reason = symbol_reason

    def readiness(self):
        return {
            "latest_cycle": {
                "decision_cycle_id": "cycle-safe-1",
                "scheduled_for": "2026-08-11T01:00:00Z",
                "completed_at": "2026-08-11T01:02:00Z",
                "status": "FAILED_CLOSED",
                "failure_reason": self._reason,
            },
            "latest_completed_cycle": None,
            "symbols": [],
            "last_successful_shadow_persistence_at": None,
        }

    def cycle_symbols(self, cycle_id):
        assert cycle_id == "cycle-safe-1"
        return ({
            "symbol": "600519",
            "status": "BLOCKED",
            "source_report_id": None,
            "decision_id": None,
            "failure_reason": self._symbol_reason,
        },)

    def latest_authoritative_snapshot(self):
        return None


class _M3Repository:
    def readiness(self):
        return {"pending_execution_count": 0, "latest_execution_state": None}

    def readiness_for_cycle(self, cycle_id):
        assert cycle_id == "cycle-safe-1"
        return {
            "mandate_count": 0,
            "dispatch_attempt_count": 0,
            "broker_submission_state": "NONE",
            "recorded_submitted_quantity": 0,
        }


class _Scheduler:
    def status(self):
        return {
            "enabled": True,
            "mode": "M3_SIMULATION_EXECUTION_ONLY",
            "background_tasks": [{
                "name": "single_brain_m3_simulation_execution",
                "interval_seconds": 3600,
                "next_run_at": "2026-08-11T02:00:00Z",
            }],
        }


def _readiness(monkeypatch, *, reason, symbol_reason=None):
    config = SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_execution_mode="SIMULATION_EXECUTION",
        single_brain_simulation_execution_authorized=True,
    )
    monkeypatch.setattr(
        "src.services.single_brain_m2_readiness_service.get_config",
        lambda: config,
    )
    return SingleBrainM2ReadinessService(
        repository=_Repository(reason=reason, symbol_reason=symbol_reason),
        runtime_scheduler=_Scheduler(),
        m3_repository=_M3Repository(),
    ).get()


def test_known_quota_reason_projects_safe_chinese_without_raw_error(monkeypatch):
    payload = _readiness(
        monkeypatch,
        reason="no shadow decision lineage was persisted",
        symbol_reason="provider returned 429: quota exceeded secret=do-not-expose",
    )

    diagnostics = payload["latest_cycle_diagnostics"]
    assert diagnostics["failure_stage"] == "RESEARCH"
    assert diagnostics["failure_code"] == "AI_QUOTA_EXHAUSTED"
    assert diagnostics["failure_summary"] == "AI 分析额度不足"
    assert diagnostics["research_completed"] is False
    assert diagnostics["decision_created"] is False
    assert diagnostics["mandate_created"] is False
    assert diagnostics["broker_submission_state"] == "NONE"
    assert "do-not-expose" not in json.dumps(diagnostics, ensure_ascii=False)


def test_unknown_research_reason_never_invents_quota(monkeypatch):
    payload = _readiness(
        monkeypatch,
        reason="no shadow decision lineage was persisted",
        symbol_reason="runtime_reason=RESEARCH_INCOMPLETE",
    )

    diagnostics = payload["latest_cycle_diagnostics"]
    assert diagnostics["failure_code"] == "RESEARCH_INCOMPLETE"
    assert diagnostics["failure_summary"] == "研究阶段未完成，具体原因待确认"
    assert "额度" not in diagnostics["failure_summary"]


def test_authority_failure_uses_exact_persisted_snapshot_reason(monkeypatch):
    payload = _readiness(
        monkeypatch,
        reason="authoritative PortfolioSnapshot is stale",
        symbol_reason="runtime_reason=RESEARCH_INCOMPLETE",
    )

    diagnostics = payload["latest_cycle_diagnostics"]
    assert diagnostics["failure_stage"] == "AUTHORITY_INPUT"
    assert diagnostics["failure_code"] == "SNAPSHOT_STALE"
    assert diagnostics["failure_summary"] == "账户快照已过期"


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("429 RESOURCE_EXHAUSTED: token=secret", "runtime_reason=AI_QUOTA_EXHAUSTED"),
        ("api key missing", "runtime_reason=AI_SERVICE_UNAVAILABLE"),
        ("no data returned", "runtime_reason=RESEARCH_DATA_UNAVAILABLE"),
        ("unclassified provider failure token=secret", "runtime_reason=RESEARCH_INCOMPLETE"),
    ),
)
def test_analysis_failure_marker_persists_only_safe_category(raw, expected):
    marker = analysis_failure_marker(raw)
    assert marker == expected
    assert "secret" not in marker


def test_m3_cycle_projection_distinguishes_recorded_from_unknown_submission(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'runtime-reason.db'}")
    now = datetime(2026, 8, 11, 1, 0, 0)
    try:
        with db.session_scope() as session:
            session.add_all((
                SingleBrainM3ExecutionRecord(
                    decision_id="decision-recorded",
                    cycle_id="cycle-recorded",
                    symbol="600519",
                    status="COMPLETED",
                    source_report_id=1,
                    mandate_id="mandate-recorded",
                    mandate_hash="a" * 64,
                    idempotency_key="b" * 64,
                    mandate_json="{}",
                    lineage_json="{}",
                    results_json=json.dumps([{
                        "status": "BLOCKED",
                        "submitted_quantity": 0,
                    }]),
                    dispatch_attempt_count=1,
                    created_at=now,
                    updated_at=now,
                ),
                SingleBrainM3ExecutionRecord(
                    decision_id="decision-unknown",
                    cycle_id="cycle-unknown",
                    symbol="000001",
                    status="PENDING_RECONCILIATION",
                    source_report_id=2,
                    mandate_id="mandate-unknown",
                    mandate_hash="c" * 64,
                    idempotency_key="d" * 64,
                    mandate_json="{}",
                    lineage_json="{}",
                    results_json="[]",
                    dispatch_attempt_count=1,
                    created_at=now,
                    updated_at=now,
                ),
            ))

        repository = M3ExecutionRepository(db)
        blocked = repository.readiness_for_cycle("cycle-recorded")
        unknown = repository.readiness_for_cycle("cycle-unknown")

        assert blocked["mandate_count"] == 1
        assert blocked["broker_submission_state"] == "NONE"
        assert unknown["broker_submission_state"] == "UNKNOWN"
    finally:
        DatabaseManager.reset_instance()


def test_runtime_reason_classifier_keeps_execution_uncertainty_separate():
    explanation = classify_runtime_failure(("M3 recovery failed: pending_reconciliation",))
    assert explanation.stage == "EXECUTION"
    assert explanation.code == "EXECUTION_PENDING"


@pytest.mark.parametrize(
    "reason",
    (
        "no database connection",
        "prerequisite migration missing",
        "api key missing from unrelated integration",
        "login_required by admin console",
    ),
)
def test_legacy_weak_tokens_do_not_invent_research_or_provider_cause(reason):
    explanation = classify_runtime_failure((reason,))
    assert explanation.stage == "CYCLE"
    assert explanation.code == "CYCLE_FAILURE"

    proven_research_failure = classify_runtime_failure(
        (reason,),
        research_incomplete=True,
    )
    assert proven_research_failure.stage == "RESEARCH"
    assert proven_research_failure.code == "RESEARCH_INCOMPLETE"
