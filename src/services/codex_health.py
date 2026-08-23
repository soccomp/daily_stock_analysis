"""Read-only Codex/Luna identity and real-generation health evidence."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import time
from statistics import median
from typing import Any, Dict, Iterable, Mapping, Optional


CODEX_DEPENDENCY_ID = "codex-luna"
CODEX_PROVIDER_ID = "codex_chatgpt_oauth"
DEFAULT_CODEX_MODEL = "gpt-5.6-luna"
DEFAULT_CODEX_GENERATION_TTL_SECONDS = 900
DEFAULT_CODEX_TIMEOUT_SECONDS = 300
HEALTHY_LATENCY_MARGIN_RATIO = 0.75


def _load_runtime_env() -> None:
    try:
        from src.config import setup_env

        setup_env()
    except Exception:
        return


def _safe_text(value: Any, limit: int = 160) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:limit] if text else None


def _configured_model(config: Any = None) -> str:
    value = (
        getattr(config, "codex_cli_model", None)
        if config is not None
        else None
    ) or os.getenv("CODEX_CLI_MODEL") or DEFAULT_CODEX_MODEL
    return str(value).strip() or DEFAULT_CODEX_MODEL


def _configured_backends(config: Any = None) -> tuple[str, str]:
    generation = (
        getattr(config, "generation_backend", None)
        if config is not None
        else None
    ) or os.getenv("GENERATION_BACKEND", "")
    agent = (
        getattr(config, "agent_backend", None)
        if config is not None
        else None
    ) or os.getenv("AGENT_BACKEND", "")
    return str(generation).strip().lower(), str(agent).strip().lower()


def _run_codex_command(command: list[str], *, timeout_seconds: float) -> tuple[bool, str, str]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(0.1, float(timeout_seconds)),
            check=False,
        )
    except FileNotFoundError:
        return False, "COMMAND_NOT_FOUND", ""
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", ""
    except (OSError, subprocess.SubprocessError) as exc:
        return False, type(exc).__name__.upper(), ""
    output = _safe_text(result.stdout or result.stderr, 200) or ""
    if result.returncode != 0:
        folded = output.casefold()
        if any(marker in folded for marker in ("not logged in", "login", "authentication", "sign in")):
            return False, "LOGIN_REQUIRED", ""
        if any(marker in folded for marker in ("quota", "usage limit", "rate limit", "too many requests")):
            return False, "QUOTA_EXHAUSTED", ""
        return False, "COMMAND_FAILED", ""
    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    return True, "", output or str(elapsed_ms)


def probe_codex_identity(*, config: Any = None, timeout_seconds: float = 3.0) -> Dict[str, Any]:
    """Probe executable, ChatGPT OAuth login, and configured model identity only.

    This is intentionally a metadata probe. It never generates text and never
    changes login, provider, model, scheduler, proposal, or execution state.
    """
    _load_runtime_env()
    generation_backend, agent_backend = _configured_backends(config)
    model = _configured_model(config)
    configured = generation_backend == "codex_cli" or agent_backend == "codex_app_server"
    enabled = configured and bool(model)
    result: Dict[str, Any] = {
        "dependency_id": CODEX_DEPENDENCY_ID,
        "category": "LLM_RESEARCH",
        "configured": configured,
        "enabled": enabled,
        "endpoint": "codex://chatgpt-oauth",
        "expected_model": model,
        "expected_provider": CODEX_PROVIDER_ID,
        "generation_backend": generation_backend,
        "agent_backend": agent_backend,
        "auth_mode": "codex_managed_chatgpt_oauth",
        "success": None,
        "reachable": None,
        "usable": None,
        "status": "UNKNOWN",
        "failure_class": None,
        "error": None,
        "latency_ms": None,
    }
    if not enabled:
        result.update(status="DISABLED", failure_class="NOT_CONFIGURED")
        return result

    executable = shutil.which("codex")
    if not executable:
        result.update(
            success=False,
            reachable=False,
            usable=False,
            status="FAILED",
            failure_class="COMMAND_NOT_FOUND",
        )
        return result

    version_ok, version_failure, version_text = _run_codex_command(
        [executable, "--version"], timeout_seconds=timeout_seconds
    )
    login_ok, login_failure, login_text = _run_codex_command(
        [executable, "login", "status"], timeout_seconds=timeout_seconds
    )
    if not version_ok or not login_ok:
        failure = version_failure if not version_ok else login_failure
        result.update(
            success=False,
            reachable=version_ok,
            usable=False,
            status="FAILED",
            failure_class=failure,
            metadata={
                "executable": os.path.basename(executable),
                "cli_version": version_text if version_ok else None,
                "login_status": "HEALTHY" if login_ok else login_failure,
            },
        )
        return result

    result.update(
        success=True,
        reachable=True,
        usable=True,
        status="HEALTHY",
        metadata={
            "executable": os.path.basename(executable),
            "cli_version": version_text,
            "login_status": "HEALTHY",
            "login_evidence": login_text or "present",
            "model": model,
            "provider": CODEX_PROVIDER_ID,
        },
    )
    return result


def _generation_failure_class(row: Mapping[str, Any]) -> str:
    return str(row.get("failure_class") or row.get("error_code") or "UNKNOWN").upper()


def summarize_generation_metrics(
    samples: Iterable[Mapping[str, Any]],
    *,
    timeout_seconds: float = DEFAULT_CODEX_TIMEOUT_SECONDS,
    tested_contexts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Summarize real Luna workload samples conservatively.

    A healthy result requires multiple successful, structured samples and at
    least 25% timing margin below the configured timeout. A single executable
    or login probe cannot make this summary healthy.
    """
    rows = [dict(row) for row in samples]
    latencies = sorted(
        float(row["latency_ms"])
        for row in rows
        if row.get("success") is True and row.get("latency_ms") is not None
    )
    successes = sum(1 for row in rows if row.get("success") is True)
    structured_successes = sum(
        1
        for row in rows
        if row.get("success") is True
        and (row.get("schema_valid") is True or row.get("structured_output_valid") is True)
    )
    failure_counts: Dict[str, int] = {}
    for row in rows:
        if row.get("success") is True:
            continue
        failure = _generation_failure_class(row)
        failure_counts[failure] = failure_counts.get(failure, 0) + 1
    timeout_count = sum(1 for row in rows if _generation_failure_class(row) in {"TIMEOUT", "READ_TIMEOUT"})
    p95_index = min(len(latencies) - 1, max(0, math.ceil(len(latencies) * 0.95) - 1)) if len(latencies) >= 2 else None
    timeout_budget_ms = max(1, int(float(timeout_seconds) * 1000))
    healthy_latency_budget_ms = int(timeout_budget_ms * HEALTHY_LATENCY_MARGIN_RATIO)
    worst_case_margin_ms = (
        timeout_budget_ms - int(max(latencies))
        if latencies
        else None
    )
    context_rows = [dict(item) for item in (tested_contexts or ())]
    successful_contexts = [
        int(item["context_tokens"])
        for item in context_rows
        if item.get("success") is True and item.get("context_tokens") is not None
    ]
    healthy = bool(
        len(rows) >= 2
        and successes == len(rows)
        and structured_successes == len(rows)
        and max(latencies, default=timeout_budget_ms + 1) < healthy_latency_budget_ms
    )
    status = "HEALTHY" if healthy else ("DEGRADED" if successes else "FAILED")
    return {
        "sample_count": len(rows),
        "success_count": successes,
        "success_rate": (successes / len(rows)) if rows else 0.0,
        "structured_output_success_count": structured_successes,
        "structured_output_success_rate": (structured_successes / len(rows)) if rows else 0.0,
        "timeout_count": timeout_count,
        "timeout_rate": (timeout_count / len(rows)) if rows else 0.0,
        "failure_class_counts": failure_counts,
        "p50_latency_ms": median(latencies) if latencies else None,
        "p95_latency_ms": latencies[p95_index] if p95_index is not None else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "latency_sample_count": len(latencies),
        "latency_sample_sufficient": len(latencies) >= 2,
        "timeout_budget_ms": timeout_budget_ms,
        "healthy_latency_budget_ms": healthy_latency_budget_ms,
        "worst_case_margin_ms": worst_case_margin_ms,
        "concurrency_limit": 1,
        "recommended_concurrency": 1,
        "max_operational_context": max(successful_contexts) if successful_contexts else None,
        "context_samples": context_rows,
        "status": status,
    }


def record_codex_generation_observation(
    *,
    success: bool,
    latency_ms: int,
    reachable: Optional[bool] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    backend: Optional[str] = None,
    failure_class: Optional[str] = None,
    error: Optional[Any] = None,
    schema_valid: Optional[bool] = None,
    usage_available: Optional[bool] = None,
    context_tokens: Optional[int] = None,
) -> None:
    """Persist one real CLI/App Server generation without affecting execution."""
    try:
        from src.services.dependency_health import get_dependency_health_store

        effective_model = str(model or os.getenv("CODEX_CLI_MODEL") or DEFAULT_CODEX_MODEL).strip()
        effective_provider = str(provider or CODEX_PROVIDER_ID).strip()
        metadata = {
            "model": effective_model,
            "provider": effective_provider,
            "backend": backend or "codex_cli",
            "schema_valid": schema_valid,
            "structured_output_valid": schema_valid,
            "usage_available": usage_available,
            "context_tokens": context_tokens,
            "auth_mode": "codex_managed_chatgpt_oauth",
        }
        store = get_dependency_health_store()
        store.record_result(
            CODEX_DEPENDENCY_ID,
            category="LLM_RESEARCH",
            configured=True,
            enabled=True,
            role="PRIMARY",
            priority=1,
            endpoint="codex://chatgpt-oauth",
            success=bool(success),
            reachable=reachable if reachable is not None else True,
            usable=bool(success),
            records=1 if success else 0,
            empty_valid=False,
            latency_ms=max(0, int(latency_ms)),
            failure_class_name=failure_class,
            error=error,
            metadata=metadata,
            observation_kind="generation",
            freshness_ttl_seconds=int(
                os.getenv(
                    "DSA_CODEX_GENERATION_HEALTH_TTL_SECONDS",
                    str(DEFAULT_CODEX_GENERATION_TTL_SECONDS),
                )
            ),
        )
    except Exception:
        # Health persistence cannot turn a completed research call into an
        # action or make the LLM call fail.
        return


__all__ = [
    "CODEX_DEPENDENCY_ID",
    "CODEX_PROVIDER_ID",
    "DEFAULT_CODEX_MODEL",
    "probe_codex_identity",
    "record_codex_generation_observation",
    "summarize_generation_metrics",
]
