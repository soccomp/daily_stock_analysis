"""M2 uses the existing scheduler provider and shared analysis lock."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.config import Config
from src.services.runtime_scheduler import build_single_brain_m2_background_tasks
from src.services.runtime_scheduler import build_cli_schedule_background_tasks


def _config(*, enabled):
    return SimpleNamespace(
        single_brain_m2_enabled=enabled,
        single_brain_m2_interval_minutes=17,
        single_brain_m2_run_immediately=False,
    )


def test_m2_scheduler_provider_is_empty_when_default_off():
    config = _config(enabled=False)
    assert build_single_brain_m2_background_tasks(
        config,
        config_provider=lambda: config,
    ) == []


def test_m2_scheduler_provider_runs_one_bounded_attempt_on_existing_lock():
    config = _config(enabled=True)
    seen = []

    class _Service:
        def run_cycle(self):
            seen.append(True)
            return SimpleNamespace(
                cycle_id="cycle-1",
                status="COMPLETED",
                persisted_decision_ids=("decision-1",),
            )

    tasks = build_single_brain_m2_background_tasks(
        config,
        config_provider=lambda: config,
    )
    assert len(tasks) == 1
    assert tasks[0]["interval_seconds"] == 17 * 60
    assert tasks[0]["run_immediately"] is False
    with patch(
        "src.investment.m2.orchestration.M2ShadowLoopService.from_config",
        return_value=_Service(),
    ) as factory:
        tasks[0]["task"]()

    factory.assert_called_once_with(config)
    assert seen == [True]


def test_m2_pipeline_safety_flag_blocks_preexisting_p1_runtime_hooks():
    from tests.test_investment_shadow_wiring_p1a import _analysis_result, _shadow_pipeline

    pipeline = _shadow_pipeline(enabled=True)
    pipeline.config.investment_canary_enabled = True
    pipeline._investment_runtime_paths_disabled = True
    with (
        patch.object(pipeline, "_run_investment_canary_after_history_save") as canary,
        patch("src.investment.shadow_wiring.InvestmentShadowWiringService.build_from_analysis") as shadow,
    ):
        pipeline._run_investment_shadow_after_history_save(
            result=_analysis_result(),
            query_id="m2-safety",
            source_report_id=1,
            context_snapshot={},
        )
    canary.assert_not_called()
    shadow.assert_not_called()


def test_m2_config_is_separate_default_off_and_loads_explicit_inputs():
    assert Config().single_brain_m2_enabled is False
    with patch.dict(
        os.environ,
        {
            "DSA_SINGLE_BRAIN_M2_ENABLED": "true",
            "DSA_SINGLE_BRAIN_M2_ACCOUNT_ID": "athena-sim",
            "DSA_SINGLE_BRAIN_M2_SYMBOLS": "600519,000001",
            "DSA_SINGLE_BRAIN_M2_MAX_SYMBOLS": "4",
            "DSA_SINGLE_BRAIN_M2_HOLDINGS_LIMIT": "3",
            "DSA_SINGLE_BRAIN_M2_INTERVAL_MINUTES": "15",
            "DSA_SINGLE_BRAIN_M2_RUN_IMMEDIATELY": "true",
            "DSA_SINGLE_BRAIN_M2_SNAPSHOT_URL": (
                "http://127.0.0.1:18761/v1/simulation/portfolio-snapshot"
            ),
            "DSA_SINGLE_BRAIN_M2_SNAPSHOT_TIMEOUT_SECONDS": "2.5",
            "DSA_SINGLE_BRAIN_M2_RISK_POLICY_PATH": "/tmp/m2-policy.json",
        },
        clear=False,
    ):
        loaded = Config._load_from_env()

    assert loaded.single_brain_m2_enabled is True
    assert loaded.single_brain_m2_account_id == "athena-sim"
    assert loaded.single_brain_m2_symbols == ["600519", "000001"]
    assert loaded.single_brain_m2_max_symbols == 4
    assert loaded.single_brain_m2_holdings_limit == 3
    assert loaded.single_brain_m2_interval_minutes == 15
    assert loaded.single_brain_m2_run_immediately is True
    assert loaded.single_brain_m2_snapshot_timeout_seconds == 2.5


def test_cli_schedule_composes_m2_task_and_uses_shared_analysis_lock():
    config = _config(enabled=True)
    config.agent_event_monitor_enabled = False
    tasks = build_cli_schedule_background_tasks(
        config,
        config_provider=lambda: config,
    )
    assert [task["name"] for task in tasks] == ["single_brain_m2_shadow"]

    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8"
    )
    assert "build_cli_schedule_background_tasks" in source
    assert "_run_analysis_with_runtime_scheduler_lock(" in source
