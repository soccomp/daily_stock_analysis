"""Read-only Qwen/oMLX identity and bounded generation health probes."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
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


def _process_health() -> Dict[str, Any]:
    """Read coarse launchd/process health without persisting command lines."""
    if sys.platform != "darwin":
        return {"service_label": None, "status": "UNAVAILABLE", "reason": "PLATFORM_UNSUPPORTED"}
    label = os.getenv("LLM_OMLX_LAUNCHD_LABEL", "com.athena.olmx").strip()
    if not label:
        return {"service_label": None, "status": "UNKNOWN", "reason": "SERVICE_LABEL_NOT_CONFIGURED"}
    domain = f"gui/{os.getuid()}/{label}"
    try:
        result = subprocess.run(
            ["launchctl", "print", domain],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"service_label": label, "status": "UNKNOWN", "reason": type(exc).__name__}
    if result.returncode != 0:
        return {"service_label": label, "status": "FAILED", "reason": "LAUNCHD_SERVICE_UNAVAILABLE"}
    values: Dict[str, Any] = {"service_label": label, "status": "UNKNOWN"}
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("state ="):
            values["state"] = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("pid ="):
            try:
                values["pid"] = int(stripped.split("=", 1)[1].strip())
            except ValueError:
                pass
        elif stripped.startswith("runs ="):
            try:
                values["launchd_runs"] = int(stripped.split("=", 1)[1].strip())
            except ValueError:
                pass
        elif stripped.startswith("last exit code ="):
            values["last_exit_code"] = stripped.split("=", 1)[1].strip()
    values["status"] = "HEALTHY" if values.get("state") in {"running", "active"} else "DEGRADED"
    pid = values.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            ps = subprocess.run(
                ["ps", "-p", str(pid), "-o", "etime=,rss="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            fields = ps.stdout.strip().split()
            if fields:
                values["uptime"] = fields[0]
            if len(fields) > 1:
                values["process_rss_kb"] = int(fields[1])
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return values


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
        "process": _process_health(),
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
        status="HEALTHY" if exact and loaded_exact else "FAILED",
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
        failure_class=None if exact and loaded_exact else "MODEL_IDENTITY_MISMATCH",
        error=(models_error or status_error or (None if exact and loaded_exact else "EXPECTED_MODEL_NOT_LOADED")),
    )
    return result


def summarize_generation_metrics(samples: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(samples)
    latencies = sorted(float(row["latency_ms"]) for row in rows if row.get("success") and row.get("latency_ms") is not None)
    successes = sum(1 for row in rows if row.get("success") is True)
    timeouts = sum(1 for row in rows if row.get("failure_class") in {"TIMEOUT", "READ_TIMEOUT"})
    structured_successes = sum(1 for row in rows if row.get("success") is True and row.get("json_parse") is True)
    empty_or_truncated = sum(
        1 for row in rows if row.get("failure_class") in {"EMPTY_RESPONSE", "TRUNCATED_RESPONSE"}
    )
    p95_index = min(len(latencies) - 1, max(0, math.ceil(len(latencies) * 0.95) - 1)) if latencies else None
    recommended_concurrency = 1 if not latencies or max(latencies) >= 30_000 else 2
    operational_context = 16_384 if not latencies or max(latencies) >= 30_000 else 65_536
    return {
        "sample_count": len(rows),
        "success_count": successes,
        "success_rate": (successes / len(rows)) if rows else 0.0,
        "structured_output_success_count": structured_successes,
        "structured_output_success_rate": (structured_successes / len(rows)) if rows else 0.0,
        "timeout_count": timeouts,
        "timeout_rate": (timeouts / len(rows)) if rows else 0.0,
        "empty_or_truncated_count": empty_or_truncated,
        "p50_latency_ms": (median(latencies) if latencies else None),
        "p95_latency_ms": (latencies[p95_index] if p95_index is not None else None),
        "concurrency_limit": recommended_concurrency,
        "recommended_concurrency": recommended_concurrency,
        "max_operational_context": operational_context,
        "status": "HEALTHY" if rows and successes == len(rows) else ("DEGRADED" if successes else "FAILED"),
    }


__all__ = ["probe_qwen_identity", "summarize_generation_metrics"]
