#!/usr/bin/env python3
"""Bounded, read-only Qwen3.8/oMLX audit using the real Pallas workloads.

The audit deliberately keeps identity/process observations separate from
generation observations. It never starts a scheduler, creates a proposal,
touches a broker, or submits an order.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.qwen_health import probe_qwen_identity, summarize_generation_metrics


_REAL_WORKLOAD = {
    "market_review": {
        "source": "src/market_analyzer.py:783",
        "call": "analyzer.generate_text(prompt, max_tokens=8192, temperature=0.7)",
    },
    "screening_json": {
        "source": "src/services/screening/ranker.py:_call_llm",
        "call": "JSON mode, max_tokens=2048, temperature=0.2, timeout_sec=60",
    },
    "research_bundle": {
        "source": "src/investment/contracts/research_bundle.py",
        "call": "strict ResearchBundle contract validation after generation",
    },
}


def _generation_worker(
    conn,
    endpoint: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_seconds: float,
) -> None:
    """Keep an uncooperative local response out of the audit parent."""
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=(3.0, timeout_seconds))
        response.raise_for_status()
        body = response.json()
        choice = (body.get("choices") or [{}])[0] or {}
        message = choice.get("message") or {}
        content = message.get("content") or ""
        conn.send({
            "transport_success": True,
            "content": content,
            "finish_reason": choice.get("finish_reason"),
            "usage": body.get("usage") if isinstance(body.get("usage"), dict) else None,
        })
    except requests.exceptions.Timeout as exc:
        conn.send({"transport_success": False, "failure_class": "TIMEOUT", "error": type(exc).__name__})
    except Exception as exc:  # noqa: BLE001 - audit result is fail-closed
        conn.send({"transport_success": False, "failure_class": type(exc).__name__, "error": str(exc)[:160]})
    finally:
        conn.close()


def _bounded_generation(
    endpoint: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_seconds: float,
) -> Dict[str, Any]:
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
            return {"transport_success": False, "failure_class": "TIMEOUT"}
        try:
            return parent.recv()
        except EOFError:
            return {"transport_success": False, "failure_class": "AUDIT_WORKER_EXITED"}
    finally:
        parent.close()
        process.join(1)
        if process.is_alive():
            process.terminate()
            process.join(1)


def _estimate_context_tokens(messages: Iterable[Mapping[str, Any]]) -> int:
    text = " ".join(str(message.get("content") or "") for message in messages)
    return max(1, (len(text) + 3) // 4)


def _market_review_prompt() -> str:
    return (
        "You are the Pallas Market Review analyst. Produce a concise market review from the "
        "following realistic daily snapshot. Preserve uncertainty and distinguish observed facts "
        "from inference. Include regime, breadth, liquidity, risk flags, catalysts, invalidation "
        "conditions, and a short no-trade conclusion when evidence is insufficient. This is a "
        "research artifact only.\n\n"
        "Observed date: 2026-08-23; market: CN; session: closed\n"
        "Index snapshot: SSE 3000.12 (+0.42%), CSI 500 5521.03 (-0.18%), turnover 812.4bn CNY\n"
        "Breadth: 2387 advancing, 1764 declining, 112 limit-up, 34 limit-down\n"
        "Industry leaders: semiconductors +1.8%, banks +0.3%, consumer -0.6%\n"
        "Risk observations: northbound flow unavailable; calendar evidence is available; news may be "
        "fallback-derived. Do not invent a source or a price, and do not output an order."
    )


def _screening_json_prompt() -> str:
    return (
        "Return exactly one JSON object for the Pallas screening/ranking contract. No markdown, no "
        "commentary, and no JSON array at the top level. Use the supplied evidence only.\n"
        'Required shape: {"ranked":[{"code":"600519","score":0.50,"reason":"..."}]}\n'
        "Evidence: 600519 has stable daily liquidity, neutral technical momentum, and no fresh "
        "source-confirmed catalyst. 000001 has weaker breadth participation. Ranking is advisory only."
    )


def _research_bundle_prompt() -> str:
    return (
        "Return exactly one JSON object matching the strict DSA ResearchBundle canonical contract. "
        "Do not use markdown or a preamble. Use strings for canonical decimal values and an aware "
        "ISO-8601 timestamp. Set content_hash to 64 zeroes because this audit validates the schema "
        "shape with the canonical hash check explicitly skipped; this is not a production artifact.\n\n"
        "Required example fields and values: schema_version='1.0', research_id='audit-qwen-20260823', "
        "symbol='600519', market='CN', as_of='2026-08-23T00:00:00Z', horizon='1d', "
        "trigger_source='PALLAS-010_QWEN_AUDIT', market_regime, industry_view, fundamental_view, "
        "technical_view, valuation_view, intel_view, capital_flow_view, bull_case, base_case, "
        "bear_case, expected_return_range with minimum/maximum, catalysts, risk_factors, "
        "invalidation_conditions, evidence_refs, data_quality, confidence, model_provenance with "
        "model_name/model_version/provider, strategy_refs, and content_hash. Use at least one "
        "non-empty value in each required text/list field and do not claim execution."
    )


def _comparison_prompt() -> str:
    return (
        "Return exactly one JSON object and nothing else: "
        '{"status":"ok","summary":"one sentence about the evidence","risk_flags":["one bounded risk"]}. '
        "This is a local generation health comparison; do not discuss orders or execution."
    )


def _long_context_prompt() -> str:
    evidence = "\n".join(
        f"Evidence block {index}: observed factor={index % 5}; source freshness=FRESH; "
        "interpretation must remain bounded and must not create an action."
        for index in range(180)
    )
    return (
        "Return exactly one JSON object and nothing else: "
        '{"status":"ok","summary":"one sentence","risk_flags":[]}\n'
        "The following is a bounded synthetic ResearchBundle context for context-window testing; "
        "do not invent data or execution authority.\n" + evidence
    )


def _profiles(attempts: int) -> list[Dict[str, Any]]:
    sample_count = max(1, int(attempts))
    return [
        {
            "name": "market_review",
            "purpose": "real Pallas Market Review free-form generation",
            "messages": [{"role": "user", "content": _market_review_prompt()}],
            "temperature": 0.7,
            "max_tokens": 8192,
            "timeout_seconds": 90.0,
            "thinking_mode": "server_default",
            "validator": "free_text",
            "samples": sample_count,
        },
        {
            "name": "screening_json",
            "purpose": "real Pallas screening JSON mode",
            "messages": [{"role": "user", "content": _screening_json_prompt()}],
            "temperature": 0.2,
            "max_tokens": 2048,
            "timeout_seconds": 75.0,
            "thinking_mode": "non_thinking",
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
            "validator": "ranking",
            "samples": sample_count,
        },
        {
            "name": "research_bundle",
            "purpose": "ResearchBundle contract-shaped output",
            "messages": [{"role": "user", "content": _research_bundle_prompt()}],
            "temperature": 0.2,
            "max_tokens": 2048,
            "timeout_seconds": 90.0,
            "thinking_mode": "non_thinking",
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
            "validator": "research_bundle",
            "samples": sample_count,
        },
        {
            "name": "non_thinking_comparison",
            "purpose": "explicit Qwen non-thinking control",
            "messages": [{"role": "user", "content": _comparison_prompt()}],
            "temperature": 0.0,
            "max_tokens": 256,
            "timeout_seconds": 60.0,
            "thinking_mode": "non_thinking",
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
            "validator": "comparison",
            "samples": sample_count,
        },
        {
            "name": "thinking_comparison",
            "purpose": "explicit Qwen thinking control",
            "messages": [{"role": "user", "content": _comparison_prompt()}],
            "temperature": 0.0,
            "max_tokens": 512,
            "timeout_seconds": 90.0,
            "thinking_mode": "thinking",
            "chat_template_kwargs": {"enable_thinking": True},
            "response_format": {"type": "json_object"},
            "validator": "comparison",
            "samples": sample_count,
        },
        {
            "name": "long_context",
            "purpose": "bounded long-context ResearchBundle-shaped input",
            "messages": [{"role": "user", "content": _long_context_prompt()}],
            "temperature": 0.0,
            "max_tokens": 128,
            "timeout_seconds": 75.0,
            "thinking_mode": "non_thinking",
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
            "validator": "comparison",
            "samples": sample_count,
        },
    ]


def _validate_content(content: str, validator: str) -> Dict[str, Any]:
    if validator == "free_text":
        return {"json_parse": None, "schema_valid": True, "validation_error": None}
    try:
        value = json.loads(content)
    except (TypeError, ValueError) as exc:
        return {"json_parse": False, "schema_valid": False, "validation_error": type(exc).__name__}
    if not isinstance(value, dict):
        return {"json_parse": True, "schema_valid": False, "validation_error": "TOP_LEVEL_OBJECT_REQUIRED"}
    if validator == "ranking":
        valid = isinstance(value.get("ranked"), list)
        return {"json_parse": True, "schema_valid": valid, "validation_error": None if valid else "RANKED_LIST_REQUIRED"}
    if validator == "comparison":
        missing = [key for key in ("status", "summary", "risk_flags") if key not in value]
        valid = not missing and isinstance(value.get("risk_flags"), list)
        return {
            "json_parse": True,
            "schema_valid": valid,
            "validation_error": None if valid else f"MISSING_OR_INVALID:{','.join(missing)}",
        }
    if validator == "research_bundle":
        try:
            from src.investment.contracts.research_bundle import ResearchBundle

            ResearchBundle.model_validate(
                value,
                context={"canonical_contract_skip_hash_validation": True},
            )
            return {"json_parse": True, "schema_valid": True, "validation_error": None}
        except ImportError as exc:
            return {
                "json_parse": True,
                "schema_valid": False,
                "validation_error": f"VALIDATOR_UNAVAILABLE:{type(exc).__name__}",
            }
        except Exception as exc:  # noqa: BLE001 - preserve contract failure as evidence
            return {
                "json_parse": True,
                "schema_valid": False,
                "validation_error": f"RESEARCH_BUNDLE:{type(exc).__name__}",
            }
    return {"json_parse": True, "schema_valid": False, "validation_error": "UNKNOWN_VALIDATOR"}


def _model_name(identity: Dict[str, Any]) -> str:
    return str(identity.get("expected_model") or os.getenv("LLM_OMLX_MODELS", "").split(",")[0]).strip()


def _run_profile(
    *,
    profile: Dict[str, Any],
    model: str,
    endpoint: str,
    headers: Dict[str, str],
) -> list[Dict[str, Any]]:
    samples: list[Dict[str, Any]] = []
    for attempt in range(int(profile["samples"])):
        payload = {
            "model": model,
            "temperature": profile["temperature"],
            "max_tokens": profile["max_tokens"],
            "messages": profile["messages"],
        }
        for key in ("response_format", "chat_template_kwargs"):
            if key in profile:
                payload[key] = profile[key]
        started = time.monotonic()
        raw = _bounded_generation(endpoint, headers, payload, float(profile["timeout_seconds"]))
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        content = str(raw.get("content") or "")
        validation = _validate_content(content, str(profile["validator"])) if raw.get("transport_success") else {
            "json_parse": False if profile["validator"] != "free_text" else None,
            "schema_valid": False,
            "validation_error": raw.get("failure_class"),
        }
        generation_success = bool(raw.get("transport_success") and content)
        contract_success = bool(generation_success and validation.get("schema_valid") is not False)
        samples.append({
            "profile": profile["name"],
            "attempt": attempt + 1,
            "success": contract_success,
            "transport_success": bool(raw.get("transport_success")),
            "latency_ms": latency_ms,
            "input_chars": sum(len(str(message.get("content") or "")) for message in profile["messages"]),
            "context_tokens": _estimate_context_tokens(profile["messages"]),
            "temperature": profile["temperature"],
            "max_tokens": profile["max_tokens"],
            "thinking_mode": profile["thinking_mode"],
            "json_parse": validation.get("json_parse"),
            "schema_valid": validation.get("schema_valid"),
            "validation_error": validation.get("validation_error"),
            "finish_reason": raw.get("finish_reason"),
            "failure_class": None if contract_success else (
                raw.get("failure_class") or validation.get("validation_error") or "CONTRACT_INVALID"
            ),
            "content_preview": " ".join(content.split())[:180] if content else None,
        })
    return samples


def run(*, attempts: int, timeout_seconds: float) -> Dict[str, Any]:
    identity = probe_qwen_identity(timeout_seconds=min(5.0, timeout_seconds))
    model = _model_name(identity)
    endpoint = (identity.get("endpoint") or "http://127.0.0.1:8000/v1").rstrip("/") + "/chat/completions"
    key = os.getenv("LLM_OMLX_API_KEY", "").strip()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    profiles = _profiles(attempts)
    all_samples: list[Dict[str, Any]] = []
    profile_results: Dict[str, Any] = {}
    started = time.monotonic()
    for profile in profiles:
        samples = _run_profile(profile=profile, model=model, endpoint=endpoint, headers=headers)
        all_samples.extend(samples)
        profile_results[profile["name"]] = {
            "purpose": profile["purpose"],
            "workload": _REAL_WORKLOAD.get(profile["name"]),
            "parameters": {
                key: profile[key]
                for key in (
                    "temperature", "max_tokens", "timeout_seconds", "thinking_mode",
                    "response_format", "chat_template_kwargs",
                )
                if key in profile
            },
            "samples": samples,
            "metrics": summarize_generation_metrics(samples, tested_contexts=samples),
        }
    metrics = summarize_generation_metrics(all_samples, tested_contexts=all_samples)
    has_timeout = any(row.get("failure_class") == "TIMEOUT" for row in all_samples)
    all_contracts_valid = bool(all_samples) and all(row.get("success") is True for row in all_samples)
    latency_bounded = bool(metrics.get("p95_latency_ms") is not None and metrics["p95_latency_ms"] < 30_000)
    identity_ready = identity.get("usable") is True
    if identity_ready and all_contracts_valid and latency_bounded:
        rating = "PRODUCTION_READY" if metrics.get("recommended_concurrency") == 2 else "PRODUCTION_READY_WITH_LIMITS"
    else:
        rating = "NOT_READY"

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
            success=bool(metrics.get("success_count")) and all_contracts_valid,
            reachable=bool(identity.get("reachable")),
            usable=bool(identity_ready and rating in {"PRODUCTION_READY", "PRODUCTION_READY_WITH_LIMITS"}),
            records=int(metrics.get("success_count") or 0),
            latency_ms=metrics.get("p95_latency_ms"),
            failure_class_name=("GENERATION_TIMEOUT" if has_timeout else None),
            metadata={"audit_runtime_seconds": int(time.monotonic() - started), "metrics": metrics},
            observation_kind="generation",
            freshness_ttl_seconds=int(os.getenv("DSA_QWEN_GENERATION_HEALTH_TTL_SECONDS", "900")),
        )
    except Exception:
        pass
    return {
        "dependency": "qwen-omlx",
        "identity": identity,
        "actual_pallas_workload": _REAL_WORKLOAD,
        "profiles": profile_results,
        "generation": metrics,
        "samples": all_samples,
        "production_readiness": rating,
        "observed_generation_status": metrics.get("status"),
        "derivation": {
            "latency": "p95 is emitted only with at least two successful samples",
            "context": "max_operational_context is the maximum successful tested context_tokens; no inferred fixed ceiling",
            "concurrency": "2 only when all sequential contract-valid samples are below 30s; otherwise 1",
            "audit_duration_seconds": round(time.monotonic() - started, 3),
        },
        "simulation_only": True,
        "execution_authority": "ATHENA_ONLY",
        "proof_order": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=2, help="sequential samples per workload profile")
    parser.add_argument("--timeout-seconds", type=float, default=90.0, help="identity probe ceiling")
    args = parser.parse_args()
    print(json.dumps(run(attempts=args.attempts, timeout_seconds=args.timeout_seconds), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
