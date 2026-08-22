"""Read-only Qwen/oMLX identity and bounded generation health probes."""

from __future__ import annotations

import json
import os
import time
from statistics import median
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def _load_runtime_env() -> None:
    try:
        from src.config import setup_env

        setup_env()
    except Exception:
        return


def _base_url() -> str:
    return (os.getenv("LLM_OMLX_BASE_URL") or "http://127.0.0.1:8000/v1").rstrip("/")


def _expected_model() -> str:
    value = (os.getenv("LLM_OMLX_MODEL") or os.getenv("LITELLM_MODEL") or "").strip()
    if "/" in value:
        value = value.rsplit("/", 1)[-1]
    if not value:
        value = (os.getenv("LLM_OMLX_MODELS") or "").split(",")[0].strip()
    return value


def _request_json(path: str, *, timeout: float) -> tuple[bool, Any, Optional[str], int]:
    url = urljoin(_base_url() + "/", path.lstrip("/"))
    headers = {"Accept": "application/json"}
    api_key = os.getenv("LLM_OMLX_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    started = time.monotonic()
    try:
        with urlopen(Request(url, headers=headers, method="GET"), timeout=timeout) as response:
            raw = response.read()
            return True, json.loads(raw.decode("utf-8")), None, max(0, int((time.monotonic() - started) * 1000))
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}", max(0, int((time.monotonic() - started) * 1000))


def probe_qwen_identity(*, timeout_seconds: float = 3.0) -> Dict[str, Any]:
    """Probe only local oMLX metadata; no generation and no trading path."""
    _load_runtime_env()
    enabled = os.getenv("LLM_OMLX_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    configured = bool(os.getenv("LLM_OMLX_BASE_URL", "").strip() or os.getenv("LLM_OMLX_API_KEY", "").strip())
    endpoint = _base_url()
    expected = _expected_model()
    result: Dict[str, Any] = {
        "dependency_id": "qwen-omlx",
        "category": "LLM_RESEARCH",
        "configured": configured,
        "enabled": enabled,
        "endpoint": endpoint,
        "expected_model": expected,
        "success": None,
        "reachable": None,
        "usable": None,
        "failure_class": None,
        "error": None,
        "latency_ms": None,
    }
    if not enabled:
        result.update(success=None, reachable=None, usable=None, status="DISABLED")
        return result
    if not configured:
        result.update(success=None, reachable=None, usable=None, status="UNKNOWN", failure_class="NOT_CONFIGURED")
        return result

    models_ok, models, models_error, models_latency = _request_json("/models", timeout=timeout_seconds)
    status_ok, status_payload, status_error, status_latency = _request_json("/models/status", timeout=timeout_seconds)
    result["latency_ms"] = max(models_latency, status_latency)
    if not models_ok and not status_ok:
        result.update(success=False, reachable=False, usable=False, status="FAILED", failure_class="UNREACHABLE", error=models_error or status_error)
        return result

    model_ids = []
    if isinstance(models, dict):
        model_ids = [str(item.get("id")) for item in models.get("data", []) if isinstance(item, dict) and item.get("id")]
    status_models = status_payload.get("models", []) if isinstance(status_payload, dict) else []
    loaded = [item for item in status_models if isinstance(item, dict) and item.get("loaded") is True]
    loaded_exact_record = next((item for item in loaded if item.get("id") == expected), loaded[0] if loaded else {})
    exact = any(item == expected for item in model_ids) if expected else bool(model_ids)
    loaded_exact = any(item.get("id") == expected and item.get("loaded") is True for item in loaded) if expected else bool(loaded)
    result.update(
        success=True,
        reachable=True,
        usable=bool(exact and loaded_exact),
        status="HEALTHY" if exact and loaded_exact else "DEGRADED",
        model_ids=model_ids,
        loaded_model_ids=[item.get("id") for item in loaded],
        loaded_count=len(loaded),
        model_count=(status_payload.get("model_count") if isinstance(status_payload, dict) else len(model_ids)),
        current_model_memory=(status_payload.get("current_model_memory") if isinstance(status_payload, dict) else None),
        final_ceiling=(status_payload.get("final_ceiling") if isinstance(status_payload, dict) else None),
        model_context_length=loaded_exact_record.get("model_context_length"),
        max_context_window=(status_payload.get("max_context_window") if isinstance(status_payload, dict) else None) or loaded_exact_record.get("max_context_window"),
        max_tokens=(status_payload.get("max_tokens") if isinstance(status_payload, dict) else None) or loaded_exact_record.get("max_tokens"),
        identity_match=exact,
        loaded_identity_match=loaded_exact,
        error=(models_error or status_error),
    )
    return result


def summarize_generation_metrics(samples: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(samples)
    latencies = sorted(float(row["latency_ms"]) for row in rows if row.get("success") and row.get("latency_ms") is not None)
    successes = sum(1 for row in rows if row.get("success") is True)
    timeouts = sum(1 for row in rows if row.get("failure_class") in {"TIMEOUT", "READ_TIMEOUT"})
    return {
        "sample_count": len(rows),
        "success_count": successes,
        "success_rate": (successes / len(rows)) if rows else 0.0,
        "timeout_count": timeouts,
        "p50_latency_ms": (median(latencies) if latencies else None),
        "p95_latency_ms": (latencies[min(len(latencies) - 1, max(0, int(len(latencies) * 0.95) - 1))] if latencies else None),
        "concurrency_limit": 1 if not latencies or (latencies and max(latencies) >= 30_000) else 2,
        "max_operational_context": 16_384 if not latencies or (latencies and max(latencies) >= 30_000) else 65_536,
        "status": "HEALTHY" if rows and successes == len(rows) else ("DEGRADED" if successes else "FAILED"),
    }


__all__ = ["probe_qwen_identity", "summarize_generation_metrics"]
