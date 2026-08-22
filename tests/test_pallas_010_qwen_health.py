from src.services.qwen_health import summarize_generation_metrics


def test_qwen_generation_metrics_are_conservative_for_slow_or_missing_samples():
    summary = summarize_generation_metrics([
        {"success": True, "latency_ms": 67851},
        {"success": False, "latency_ms": 90000, "failure_class": "TIMEOUT"},
    ])
    assert summary["p50_latency_ms"] == 67851
    assert summary["p95_latency_ms"] == 67851
    assert summary["concurrency_limit"] == 1
    assert summary["max_operational_context"] == 16384
    assert summary["status"] == "DEGRADED"
