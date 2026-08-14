from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.investment.m2.orchestration import M2ShadowBlocked, M2ShadowLoopService
from src.services.runtime_scheduler import (
    RuntimeSchedulerService,
    SCHEDULER_MODE_PROPOSAL_HANDOFF_ONLY,
    build_single_brain_m2_background_tasks,
)
from src.services.single_brain_m2_readiness_service import (
    SingleBrainM2ReadinessService,
)
from tests.test_m2_webui_only_scheduler_repair import (
    _BackgroundOnlyScheduler,
    _NoopThread,
)


def _config():
    return SimpleNamespace(
        schedule_enabled=True,
        schedule_time="18:00",
        schedule_times=["18:00"],
        agent_event_monitor_enabled=True,
        single_brain_m2_enabled=True,
        single_brain_m2_interval_minutes=60,
        single_brain_m2_run_immediately=False,
        single_brain_execution_mode="PROPOSAL_HANDOFF",
    )


def test_issue_9_uses_exactly_one_proposal_handoff_scheduler_at_m2_cadence():
    _BackgroundOnlyScheduler.instances = []
    config = _config()
    ordinary_runner = MagicMock()
    service = RuntimeSchedulerService(
        config_provider=lambda: config,
        task_runner=ordinary_runner,
        m2_shadow_only=True,
    )
    service._reload_config = lambda: config

    with patch("src.services.runtime_scheduler.Scheduler", _BackgroundOnlyScheduler), patch(
        "src.services.runtime_scheduler.threading.Thread", _NoopThread
    ):
        service.reconcile_from_config()
        first_scheduler = service._scheduler
        service.reconcile_from_config()

    assert len(_BackgroundOnlyScheduler.instances) == 1
    assert service._scheduler is first_scheduler
    assert first_scheduler.daily_task_calls == []
    assert [item["name"] for item in first_scheduler._background_tasks] == [
        "single_brain_proposal_handoff"
    ]
    assert first_scheduler._background_tasks[0]["interval_seconds"] == 3600
    assert ordinary_runner.call_count == 0
    assert service.status()["mode"] == SCHEDULER_MODE_PROPOSAL_HANDOFF_ONLY


def test_registered_scheduler_mode_change_fails_closed_until_reconciled():
    config = _config()
    task = build_single_brain_m2_background_tasks(
        config,
        config_provider=lambda: config,
    )[0]
    config.single_brain_execution_mode = "SHADOW"

    with patch(
        "src.investment.m2.orchestration.M2ShadowLoopService.from_config"
    ) as factory:
        task["task"]()

    factory.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "authorized"),
    (("SHADOW", True), ("SIMULATION_EXECUTION", False), ("INVALID", False)),
)
def test_m3_configuration_contradictions_fail_closed(mode, authorized):
    config = Config()
    config.single_brain_m2_snapshot_url = (
        "http://127.0.0.1:18761/v1/simulation/portfolio-snapshot"
    )
    config.single_brain_m2_risk_policy_path = "/tmp/m3-policy.json"
    config.single_brain_execution_mode = mode
    config.single_brain_simulation_execution_authorized = authorized

    with pytest.raises(M2ShadowBlocked):
        M2ShadowLoopService.from_config(config)


def test_readiness_reports_issue_9_proposal_authority_and_execution_off(monkeypatch):
    config = _config()
    config.single_brain_simulation_execution_authorized = False

    class _Repository:
        def readiness(self):
            return {"latest_cycle": None, "symbols": []}

        def latest_authoritative_snapshot(self):
            return None

    class _M3Repository:
        def readiness(self):
            return {
                "pending_execution_count": 0,
                "latest_execution_state": None,
            }

    class _Scheduler:
        def status(self):
            return {
                "enabled": True,
                "mode": SCHEDULER_MODE_PROPOSAL_HANDOFF_ONLY,
                "background_tasks": [{
                    "name": "single_brain_proposal_handoff",
                    "interval_seconds": 3600,
                    "next_run_at": "2026-08-10T03:30:00",
                }],
            }

    monkeypatch.setattr(
        "src.services.single_brain_m2_readiness_service.get_config",
        lambda: config,
    )
    readiness = SingleBrainM2ReadinessService(
        repository=_Repository(),
        runtime_scheduler=_Scheduler(),
        m3_repository=_M3Repository(),
    ).get()

    assert readiness["mission"] == "ISSUE_9_PROPOSAL_HANDOFF"
    assert readiness["execution_mode"] == "PROPOSAL_HANDOFF"
    assert readiness["execution_authorization"] == "OFF"
    assert readiness["dsa_authority_boundary"] == "RESEARCH_AND_PROPOSAL_ONLY"
    assert readiness["allocation_authority"] == "ATHENA_RUNTIME"
    assert readiness["mandate_authority"] == "ATHENA_RUNTIME"
    assert readiness["simulation_execution"]["legacy_runtime_disabled"] is True
    assert readiness["recurring_scheduler"]["authority_count"] == 1
    assert readiness["recurring_scheduler"]["mode"] == (
        SCHEDULER_MODE_PROPOSAL_HANDOFF_ONLY
    )
