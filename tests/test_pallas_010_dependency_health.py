from datetime import datetime, timezone

import pandas as pd
import pytest

from src.services.dependency_health import DependencyHealthStore


def test_dependency_health_persists_transitions_and_rehydrates(tmp_path):
    path = tmp_path / "dependency-health.json"
    store = DependencyHealthStore(path, transition_cooldown_seconds=0)
    store.record_result(
        "bocha",
        category="NEWS_SEARCH",
        role="PRIMARY",
        success=False,
        reachable=False,
        usable=False,
        failure_class_name="TIMEOUT",
    )
    store.record_result(
        "bocha",
        category="NEWS_SEARCH",
        role="PRIMARY",
        success=True,
        reachable=True,
        usable=True,
        records=2,
    )

    reloaded = DependencyHealthStore(path, transition_cooldown_seconds=0)
    snapshot = reloaded.snapshot()
    assert snapshot["dependencies"]["bocha"]["status"] == "HEALTHY"
    assert snapshot["dependencies"]["bocha"]["configured"] is True
    assert any(event["from"] == "FAILED" and event["to"] == "HEALTHY" for event in snapshot["transitions"])
    assert any(alert["recovery"] is True and alert["severity"] == "info" for alert in snapshot["alerts"])


def test_inventory_refresh_preserves_last_real_observation(tmp_path):
    store = DependencyHealthStore(tmp_path / "health.json")
    store.record_result(
        "tushare",
        category="MARKET_DATA",
        role="PRIMARY",
        success=True,
        reachable=True,
        usable=True,
        records=3,
    )
    previous = store.snapshot()["dependencies"]["tushare"]
    store.record_inventory([{
        "dependency_id": "tushare",
        "category": "MARKET_DATA",
        "configured": True,
        "enabled": True,
        "role": "PRIMARY",
        "priority": 1,
        "endpoint": "https://api.tushare.pro",
    }])
    current = store.snapshot()["dependencies"]["tushare"]
    assert current["status"] == "HEALTHY"
    assert current["last_success_at"] == previous["last_success_at"]


def test_successful_empty_is_degraded_not_healthy(tmp_path):
    store = DependencyHealthStore(tmp_path / "health.json")
    store.record_result(
        "searxng",
        category="NEWS_SEARCH",
        role="FALLBACK",
        success=True,
        reachable=True,
        usable=False,
        records=0,
        empty_valid=False,
    )
    assert store.snapshot()["dependencies"]["searxng"]["status"] == "DEGRADED"


def test_critical_unobserved_dependencies_fail_closed(tmp_path):
    store = DependencyHealthStore(tmp_path / "health.json")
    store.record_result("calendar", category="TRADING_CALENDAR", configured=True, enabled=True)
    readiness = store.snapshot()["readiness"]
    assert readiness["DSA_RESEARCH_READINESS"] == "BLOCKED"
    assert "RESEARCH_MARKET_DATA:UNKNOWN" in readiness["reasons"]
    assert "MARKET_CONTEXT:UNKNOWN" in readiness["reasons"]
    assert "TRADING_CALENDAR:UNKNOWN" not in readiness["reasons"]


def test_codex_identity_metadata_cannot_promote_failed_generation(tmp_path):
    store = DependencyHealthStore(tmp_path / "codex-health.json", transition_cooldown_seconds=0)
    store.record_result(
        "codex-luna",
        category="LLM_RESEARCH",
        configured=True,
        enabled=True,
        role="PRIMARY",
        success=False,
        reachable=True,
        usable=False,
        failure_class_name="TIMEOUT",
        observation_kind="generation",
        freshness_ttl_seconds=900,
    )
    store.record_result(
        "codex-luna",
        category="LLM_RESEARCH",
        configured=True,
        enabled=True,
        role="PRIMARY",
        success=True,
        reachable=True,
        usable=True,
        records=1,
        observation_kind="identity",
    )
    row = store.snapshot()["dependencies"]["codex-luna"]
    assert row["identity_status"] == "HEALTHY"
    assert row["generation_status"] == "FAILED"
    assert row["status"] == "FAILED"
    assert store.snapshot()["readiness"]["DSA_RESEARCH_READINESS"] == "BLOCKED"


def test_codex_generation_recovery_requires_a_new_generation_observation(tmp_path):
    store = DependencyHealthStore(tmp_path / "codex-health.json", transition_cooldown_seconds=0)
    store.record_result(
        "codex-luna", category="LLM_RESEARCH", success=False, reachable=True, usable=False,
        failure_class_name="TIMEOUT", observation_kind="generation",
    )
    store.record_result(
        "codex-luna", category="LLM_RESEARCH", success=True, reachable=True, usable=True,
        records=1, observation_kind="identity",
    )
    store.record_result(
        "codex-luna", category="LLM_RESEARCH", success=True, reachable=True, usable=True,
        records=2, observation_kind="generation", freshness_ttl_seconds=900,
    )
    row = store.snapshot()["dependencies"]["codex-luna"]
    assert row["status"] == "HEALTHY"
    assert row["generation_status"] == "HEALTHY"


def test_codex_generation_health_expires_without_new_generation(tmp_path):
    store = DependencyHealthStore(tmp_path / "codex-expiry.json", transition_cooldown_seconds=0)
    store.record_result(
        "codex-luna", category="LLM_RESEARCH", success=True, reachable=True, usable=True,
        records=1, observation_kind="identity",
    )
    store.record_result(
        "codex-luna", category="LLM_RESEARCH", success=True, reachable=True, usable=True,
        records=1, observation_kind="generation", freshness_ttl_seconds=0,
    )
    assert store.snapshot()["dependencies"]["codex-luna"]["status"] == "STALE"


def test_identity_monitor_observation_does_not_clear_generation_failure(monkeypatch, tmp_path):
    from src.services.dependency_health import DependencyHealthMonitor

    store = DependencyHealthStore(tmp_path / "monitor-codex.json", transition_cooldown_seconds=0)
    monkeypatch.setenv("GENERATION_BACKEND", "codex_cli")
    store.record_result(
        "codex-luna", category="LLM_RESEARCH", success=False, reachable=True, usable=False,
        failure_class_name="TIMEOUT", observation_kind="generation",
    )
    monkeypatch.setattr(
        "src.services.codex_health.probe_codex_identity",
        lambda: {
            "configured": True, "enabled": True, "endpoint": "codex://chatgpt-oauth",
            "success": True, "reachable": True, "usable": True, "loaded_count": 1,
        },
    )
    snapshot = DependencyHealthMonitor(store).once()
    assert snapshot["dependencies"]["codex-luna"]["identity_status"] == "HEALTHY"
    assert snapshot["dependencies"]["codex-luna"]["generation_status"] == "FAILED"
    assert snapshot["dependencies"]["codex-luna"]["status"] == "FAILED"


def test_codex_identity_probe_without_loaded_count_is_healthy(monkeypatch, tmp_path):
    from src.services.dependency_health import DependencyHealthMonitor

    store = DependencyHealthStore(tmp_path / "monitor-codex-identity.json", transition_cooldown_seconds=0)
    monkeypatch.setenv("GENERATION_BACKEND", "codex_cli")
    monkeypatch.setattr(
        "src.services.codex_health.probe_codex_identity",
        lambda: {
            "configured": True,
            "enabled": True,
            "endpoint": "codex://chatgpt-oauth",
            "success": True,
            "reachable": True,
            "usable": True,
            "metadata": {"model": "gpt-5.6-luna", "provider": "codex_chatgpt_oauth"},
        },
    )

    snapshot = DependencyHealthMonitor(store).once()

    assert snapshot["dependencies"]["codex-luna"]["identity_status"] == "HEALTHY"
    assert snapshot["dependencies"]["codex-luna"]["generation_status"] is None
    assert snapshot["dependencies"]["codex-luna"]["status"] == "UNKNOWN"


def test_codex_generation_degraded_is_blocked(tmp_path):
    store = DependencyHealthStore(tmp_path / "codex-degraded.json")
    store.record_result(
        "codex-luna",
        category="LLM_RESEARCH",
        success=True,
        reachable=True,
        usable=True,
        records=1,
        observation_kind="identity",
    )
    store.record_result(
        "codex-luna",
        category="LLM_RESEARCH",
        success=True,
        reachable=True,
        usable=False,
        records=0,
        observation_kind="generation",
    )
    snapshot = store.snapshot()
    assert snapshot["dependencies"]["codex-luna"]["status"] == "DEGRADED"
    assert snapshot["readiness"]["DSA_RESEARCH_READINESS"] == "BLOCKED"
    assert "LLM_RESEARCH" in snapshot["readiness"]["blocked_categories"]


def test_legacy_qwen_observation_cannot_make_codex_research_ready(tmp_path):
    store = DependencyHealthStore(tmp_path / "legacy-qwen.json")
    store.record_result(
        "qwen-omlx",
        category="LLM_RESEARCH",
        success=True,
        reachable=True,
        usable=True,
        records=1,
        observation_kind="identity",
    )
    store.record_result(
        "qwen-omlx",
        category="LLM_RESEARCH",
        success=True,
        reachable=True,
        usable=True,
        records=1,
        observation_kind="generation",
    )

    snapshot = store.snapshot()

    assert "LLM_RESEARCH" not in snapshot["categories"]
    assert snapshot["readiness"]["DSA_RESEARCH_READINESS"] == "BLOCKED"


def test_research_market_data_health_follows_screening_source_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("SNAPSHOT_SOURCE_PRIORITY", "tushare,sina,efinance")
    monkeypatch.setenv("TUSHARE_TOKEN", "fixture-token")
    store = DependencyHealthStore(tmp_path / "screening-contract.json", transition_cooldown_seconds=0)
    store.record_result(
        "tushare", category="RESEARCH_MARKET_DATA", role="PRIMARY", priority=1,
        success=False, reachable=False, usable=False, failure_class_name="TIMEOUT",
    )
    store.record_result(
        "sina", category="RESEARCH_MARKET_DATA", role="FALLBACK", priority=2,
        success=True, reachable=True, usable=True, records=1,
    )

    snapshot = store.snapshot()
    category = snapshot["categories"]["RESEARCH_MARKET_DATA"]
    assert category["status"] == "HEALTHY"
    assert category["active_source"] == "sina"
    assert category["selection_order"] == ["tushare", "sina", "efinance"]
    assert "volume_ratio" in category["required_snapshot_columns"]

    from src.services.dependency_health import configured_dependency_inventory

    rows = {
        item["dependency_id"]: item
        for item in configured_dependency_inventory()
        if item["category"] == "RESEARCH_MARKET_DATA"
    }
    assert rows["tushare"]["role"] == "PRIMARY"
    assert rows["tushare"]["priority"] == 1
    assert rows["sina"]["role"] == "FALLBACK"
    assert rows["sina"]["priority"] == 2
    assert "efinance" in rows


def test_missing_consumed_snapshot_field_fails_closed_without_synthetic_value(monkeypatch):
    from src.services.screening import snapshot as screening_snapshot

    monkeypatch.setattr(screening_snapshot, "_SOURCE_HEALTH", {})
    monkeypatch.setattr(screening_snapshot, "_persist_dependency_observation", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        screening_snapshot,
        "fetch_cn_snapshot",
        lambda _source: pd.DataFrame([{"code": "000001", "name": "Ping An", "price": 10.0}]),
    )

    with pytest.raises(RuntimeError, match=r"missing required columns volume_ratio") as error:
        screening_snapshot.fetch_snapshot_with_fallback(
            ["sina"], required_columns=["volume_ratio"], fallback_snapshot_path=None,
        )

    assert "volume_ratio" in str(error.value)
