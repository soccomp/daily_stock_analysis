#!/usr/bin/env python3
"""Run bounded, read-only Codex/Luna workload reliability samples.

The benchmark deliberately launches the same restricted ``codex exec``
contract used by DSA.  It never starts DSA, touches a database, calls a
scheduler, submits an order, or enables web search.  Raw model output is kept
out of the report; only schema, timing, failure class, and usage metadata are
emitted.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Dict, Iterable, Mapping


DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_SETTINGS = ("max", "xhigh", "high", "medium")
SAFE_ENV_NAMES = {
    "CODEX_HOME",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "NO_COLOR",
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
}


def _safe_env() -> Dict[str, str]:
    return {name: os.environ[name] for name in SAFE_ENV_NAMES if os.environ.get(name) is not None}


def _safe_error(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _usage_from_jsonl(stdout: str) -> Dict[str, Any]:
    usage: Dict[str, Any] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        event_usage = event.get("usage")
        if isinstance(event_usage, dict):
            usage.update({key: value for key, value in event_usage.items() if isinstance(value, (int, float))})
    if "input_tokens" in usage or "output_tokens" in usage:
        usage["usage_available"] = True
    else:
        usage["usage_available"] = False
    return usage


def _validate_output(payload: Any, schema: Mapping[str, Any]) -> bool:
    try:
        import jsonschema

        jsonschema.validate(payload, schema)
        return True
    except ImportError:
        required = schema.get("required") if isinstance(schema, Mapping) else None
        return isinstance(payload, dict) and all(key in payload for key in (required or ()))
    except Exception:
        return False


def _failure_class(returncode: int, *, timed_out: bool, output_exists: bool, schema_valid: bool) -> str | None:
    if timed_out:
        return "TIMEOUT"
    if returncode != 0:
        return "COMMAND_FAILED"
    if not output_exists:
        return "EMPTY_OUTPUT"
    if not schema_valid:
        return "SCHEMA_INVALID"
    return None


def run_sample(
    *,
    prompt: str,
    schema: Mapping[str, Any],
    setting: str,
    model: str,
    timeout_seconds: int,
) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pallas010-codex-benchmark-") as cwd:
        output_path = Path(cwd) / "last-message.json"
        schema_path = Path(cwd) / "response-schema.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
        command = [
            "codex",
            "exec",
            "-m",
            model,
            "-c",
            f'model_reasoning_effort="{setting}"',
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--ephemeral",
            "--json",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                cwd=cwd,
                env=_safe_env(),
                timeout=timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = 124
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        except OSError as exc:
            returncode = 127
            stdout = ""
            stderr = str(exc)
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        output_exists = output_path.is_file()
        payload = None
        schema_valid = False
        if output_exists:
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                schema_valid = _validate_output(payload, schema)
            except (OSError, ValueError, TypeError):
                schema_valid = False
        usage = _usage_from_jsonl(stdout)
        return {
            "setting": setting,
            "model": model,
            "provider": "codex_chatgpt_oauth",
            "backend": "codex_cli",
            "auth_mode": "codex_managed_chatgpt_oauth",
            "web_search_enabled": False,
            "success": bool(returncode == 0 and schema_valid),
            "schema_valid": schema_valid,
            "structured_output_valid": schema_valid,
            "latency_ms": latency_ms,
            "timeout_seconds": timeout_seconds,
            "failure_class": _failure_class(
                returncode,
                timed_out=timed_out,
                output_exists=output_exists,
                schema_valid=schema_valid,
            ),
            "returncode": returncode,
            "usage": usage,
            "usage_available": usage.get("usage_available", False),
            "stderr_preview": _safe_error(stderr),
        }


def _p95(values: Iterable[float]) -> float | None:
    ordered = sorted(values)
    if len(ordered) < 2:
        return None
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))]


def summarize(rows: list[Mapping[str, Any]], timeout_seconds: int) -> Dict[str, Any]:
    latencies = sorted(float(row["latency_ms"]) for row in rows if row.get("success") is True)
    timeout_count = sum(1 for row in rows if row.get("failure_class") == "TIMEOUT")
    successes = sum(1 for row in rows if row.get("success") is True)
    structured = sum(1 for row in rows if row.get("structured_output_valid") is True)
    return {
        "sample_count": len(rows),
        "success_count": successes,
        "success_rate": successes / len(rows) if rows else 0.0,
        "structured_output_success_count": structured,
        "structured_output_success_rate": structured / len(rows) if rows else 0.0,
        "timeout_count": timeout_count,
        "timeout_rate": timeout_count / len(rows) if rows else 0.0,
        "failure_class_counts": {
            failure: sum(1 for row in rows if row.get("failure_class") == failure)
            for failure in sorted({str(row.get("failure_class")) for row in rows if row.get("failure_class")})
        },
        "p50_latency_ms": (latencies[(len(latencies) - 1) // 2] + latencies[len(latencies) // 2]) / 2 if latencies else None,
        "p95_latency_ms": _p95(latencies),
        "max_latency_ms": max(latencies) if latencies else None,
        "timeout_budget_ms": timeout_seconds * 1000,
        "healthy_latency_budget_ms": int(timeout_seconds * 1000 * 0.75),
        "worst_case_margin_ms": timeout_seconds * 1000 - int(max(latencies)) if latencies else None,
        "concurrency_limit": 1,
        "recommended_concurrency": 1,
        "status": (
            "HEALTHY"
            if len(rows) >= 2
            and successes == len(rows)
            and structured == len(rows)
            and max(latencies, default=timeout_seconds * 1000 + 1) < timeout_seconds * 1000 * 0.75
            else "DEGRADED" if successes else "FAILED"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--schema-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--settings", nargs="+", default=list(DEFAULT_SETTINGS), choices=DEFAULT_SETTINGS)
    args = parser.parse_args()
    prompt = args.prompt_file.read_text(encoding="utf-8")
    schema = json.loads(args.schema_file.read_text(encoding="utf-8"))
    rows = []
    for setting in args.settings:
        for sample in range(max(1, args.samples)):
            row = run_sample(
                prompt=prompt,
                schema=schema,
                setting=setting,
                model=args.model,
                timeout_seconds=max(1, args.timeout_seconds),
            )
            row["sample"] = sample + 1
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    output = {
        "schema_version": 1,
        "model": args.model,
        "provider": "codex_chatgpt_oauth",
        "backend": "codex_cli",
        "auth_mode": "codex_managed_chatgpt_oauth",
        "web_search_enabled": False,
        "timeout_seconds": args.timeout_seconds,
        "concurrency_limit": 1,
        "rows": rows,
        "by_setting": {
            setting: summarize([row for row in rows if row["setting"] == setting], args.timeout_seconds)
            for setting in args.settings
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
