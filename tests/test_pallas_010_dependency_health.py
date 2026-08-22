from datetime import datetime, timezone

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
    assert readiness["AUTONOMOUS_SIMULATION_READINESS"] == "BLOCKED"
    assert "TRADING_CALENDAR:UNKNOWN" in readiness["reasons"]
