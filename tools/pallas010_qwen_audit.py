#!/usr/bin/env python3
"""Bounded, read-only Qwen3.8/oMLX production health audit.

This command probes identity first and then sends a tiny deterministic JSON
request. It is intentionally single-concurrency, never references an order or
broker, and returns a non-ready result when the local model is slow or
unavailable. It is suitable for evidence collection, not for scheduling.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.qwen_health import probe_qwen_identity, summarize_generation_metrics


def _generation_worker(conn, endpoint: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_seconds: float) -> None:
    """Keep an uncooperative streaming response out of the audit parent."""
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=(3.0, timeout_seconds))
        response.raise_for_status()
        body = response.json()
        content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        conn.send({
            "success": bool(content),
            "json_parse": bool(content and "{" in content and "}" in content),
            "failure_class": None if content else "EMPTY_RESPONSE",
            "finish_reason": ((body.get("choices") or [{}])[0].get("finish_reason")),
        })
    except requests.exceptions.Timeout as exc:
        conn.send({"success": False, "failure_class": "TIMEOUT", "error": type(exc).__name__})
    except Exception as exc:  # noqa: BLE001 - audit result is fail-closed
        conn.send({"success": False, "failure_class": type(exc).__name__, "error": str(exc)[:120]})
    finally:
        conn.close()


def _bounded_generation(endpoint: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_seconds: float) -> Dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_generation_worker,
        args=(child, endpoint, headers, payload, timeout_seconds),
        name="pallas010-qwen-generation-audit",
        daemon=True,
    )
    process.start()
    child.close()
    try:
        if not parent.poll(max(0.1, timeout_seconds)):
            if process.is_alive():
                process.terminate()
                process.join(1)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(1)
            return {"success": False, "failure_class": "TIMEOUT"}
        return parent.recv()
    finally:
        parent.close()
        process.join(1)
        if process.is_alive():
            process.terminate()
            process.join(1)



def _model_name(identity: Dict[str, Any]) -> str:
    return str(identity.get("expected_model") or os.getenv("LLM_OMLX_MODELS", "").split(",")[0]).strip()


def run(*, attempts: int, timeout_seconds: float) -> Dict[str, Any]:
    identity = probe_qwen_identity(timeout_seconds=min(5.0, timeout_seconds))
    model = _model_name(identity)
    endpoint = (identity.get("endpoint") or "http://127.0.0.1:8000/v1").rstrip("/") + "/chat/completions"
    key = os.getenv("LLM_OMLX_API_KEY", "").strip()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 96,
        "messages": [{"role": "user", "content": "Return JSON only: {\"ok\":true}"}],
    }
    samples = []
    for index in range(max(0, int(attempts))):
        started = time.monotonic()
        try:
            result = _bounded_generation(endpoint, headers, payload, timeout_seconds)
            elapsed = max(0, int((time.monotonic() - started) * 1000))
            samples.append({
                "attempt": index + 1,
                "success": bool(result.get("success")),
                "latency_ms": elapsed,
                "json_parse": bool(result.get("json_parse")),
                "failure_class": result.get("failure_class"),
                "finish_reason": result.get("finish_reason"),
                "error": result.get("error"),
            })
        except requests.exceptions.Timeout as exc:
            samples.append({"attempt": index + 1, "success": False, "latency_ms": max(0, int((time.monotonic() - started) * 1000)), "failure_class": "TIMEOUT", "error": type(exc).__name__})
        except Exception as exc:  # noqa: BLE001 - audit result is fail-closed
            samples.append({"attempt": index + 1, "success": False, "latency_ms": max(0, int((time.monotonic() - started) * 1000)), "failure_class": type(exc).__name__, "error": str(exc)[:120]})
    metrics = summarize_generation_metrics(samples)
    try:
        from src.services.dependency_health import get_dependency_health_store

        get_dependency_health_store().record_result(
            "qwen-omlx",
            category="LLM_RESEARCH",
            configured=bool(identity.get("configured")),
            enabled=bool(identity.get("enabled")),
            role="PRIMARY",
            priority=1,
            endpoint=identity.get("endpoint"),
            success=bool(metrics.get("success_count")),
            reachable=bool(identity.get("reachable")),
            usable=bool(identity.get("usable") and metrics.get("status") == "HEALTHY" and (metrics.get("p95_latency_ms") or 0) < 30_000),
            records=int(metrics.get("success_count") or 0),
            latency_ms=metrics.get("p95_latency_ms"),
            failure_class_name="GENERATION_SLOW" if (metrics.get("p95_latency_ms") or 0) >= 30_000 else None,
            metadata={"identity": identity, "generation": metrics},
        )
    except Exception:
        pass
    ready = identity.get("usable") is True and metrics.get("status") == "HEALTHY" and (metrics.get("p95_latency_ms") or 0) < 30_000
    return {
        "dependency": "qwen-omlx",
        "identity": identity,
        "generation": metrics,
        "samples": samples,
        "production_readiness": "PRODUCTION_READY_WITH_LIMITS" if ready else "NOT_READY",
        "simulation_only": True,
        "execution_authority": "ATHENA_ONLY",
        "proof_order": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args()
    print(json.dumps(run(attempts=args.attempts, timeout_seconds=args.timeout_seconds), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
