#!/usr/bin/env python3
"""Bounded, non-production transport for local Analyzer evaluations.

This tool deliberately keeps evaluation results outside production persistence.
It accepts already-persisted Research-only context from its caller and does not
load portfolio, policy, scheduler, or execution dependencies.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


_RESULT_MARKER = "LOCAL_QWEN_EVALUATION_RESULT="


@dataclass(frozen=True)
class EvaluationOutcome:
    """Sanitized parent-side observation of one isolated evaluation child."""

    status: str
    elapsed_ms: int
    exit_code: int | None
    result: dict[str, Any] | None = None
    error_type: str | None = None
    stderr_present: bool = False


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sanitize_analysis_result(result: Any) -> dict[str, Any]:
    """Return only evidence needed for output-quality evaluation."""
    return {
        "success": bool(getattr(result, "success", False)),
        "model_used": str(getattr(result, "model_used", "") or "") or None,
        "action": str(getattr(result, "action", "") or "") or None,
        "decision_type": str(getattr(result, "decision_type", "") or "") or None,
        "entry": _number(getattr(result, "ideal_buy", None)),
        "stop": _number(getattr(result, "stop_loss", None)),
        "target": _number(getattr(result, "take_profit", None)),
        "raw_response_present": bool(getattr(result, "raw_response", None)),
        "error_type": (
            str(getattr(result, "error_message", "") or "").split(":", 1)[0] or None
        ),
    }


def _mock_result() -> Any:
    class MockResult:
        success = True
        model_used = "openai/Qwen3-14B-MLX-6bit"
        action = "buy"
        decision_type = "buy"
        ideal_buy = 10.0
        stop_loss = 9.0
        take_profit = 11.0
        raw_response = "{}"
        error_message = None

    return MockResult()


def _run_analyzer(payload: Mapping[str, Any], *, analyzer_module: Any = None) -> Any:
    """Use the existing Analyzer path while suppressing evaluation telemetry writes."""
    if analyzer_module is None:
        import src.analyzer as analyzer_module

    # Evaluation isolation: Analyzer/parser behavior remains unchanged, but an
    # offline measurement must not create llm_usage rows.
    analyzer_module.persist_llm_usage = lambda *args, **kwargs: None
    analyzer = analyzer_module.GeminiAnalyzer()
    return analyzer.analyze(
        dict(payload["context"]),
        news_context=payload.get("news_context"),
        analysis_context_pack_summary=payload.get("analysis_context_pack_summary"),
    )


def _emit_child(payload: Mapping[str, Any], mode: str) -> int:
    try:
        if mode == "mock":
            result = _mock_result()
        elif mode == "raise":
            raise RuntimeError("evaluation-child-test-error")
        elif mode == "sleep":
            time.sleep(float(payload.get("sleep_seconds", 0)))
            result = _mock_result()
        elif mode == "analyzer":
            result = _run_analyzer(payload)
        else:
            raise ValueError("unsupported evaluation mode")
        envelope = {"status": "result", "result": sanitize_analysis_result(result)}
    except BaseException as exc:  # Serialize child errors rather than swallowing them.
        envelope = {"status": "error", "error_type": type(exc).__name__}
    result_path = payload.get("evaluation_result_path")
    if isinstance(result_path, str) and result_path:
        destination = Path(result_path)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
        temporary.replace(destination)
    print(_RESULT_MARKER + json.dumps(envelope, sort_keys=True), flush=True)
    return 0


def _parse_marker(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_RESULT_MARKER):
            try:
                parsed = json.loads(line[len(_RESULT_MARKER) :])
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def evaluate_payload(
    payload: Mapping[str, Any],
    *,
    mode: str = "analyzer",
    timeout_seconds: float = 6100.0,
    python_executable: str | None = None,
    result_path: Path | None = None,
) -> EvaluationOutcome:
    """Evaluate a payload in a subprocess with explicit transport outcomes."""
    with tempfile.TemporaryDirectory(prefix="dsa-local-qwen-eval-") as directory:
        payload_path = Path(directory) / "payload.json"
        child_payload = dict(payload)
        if result_path is not None:
            child_payload["evaluation_result_path"] = str(result_path)
        payload_path.write_text(json.dumps(child_payload), encoding="utf-8")
        command = [
            python_executable or sys.executable,
            str(Path(__file__).resolve()),
            "--child",
            "--mode",
            mode,
            "--payload",
            str(payload_path),
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                # A local generation client may own its own signal lifecycle.
                # Keep an evaluation child in a distinct group so it cannot
                # terminate the evaluator that must report its outcome.
                start_new_session=True,
            )
        except subprocess.TimeoutExpired:
            return EvaluationOutcome(
                status="timeout",
                elapsed_ms=round((time.monotonic() - started) * 1000),
                exit_code=None,
            )

    elapsed_ms = round((time.monotonic() - started) * 1000)
    envelope = _parse_marker(completed.stdout)
    if envelope is None and result_path is not None and result_path.is_file():
        try:
            loaded = json.loads(result_path.read_text(encoding="utf-8"))
            envelope = loaded if isinstance(loaded, dict) else None
        except (OSError, json.JSONDecodeError):
            envelope = None
    if envelope is None:
        return EvaluationOutcome(
            status="transport_error",
            elapsed_ms=elapsed_ms,
            exit_code=completed.returncode,
            stderr_present=bool(completed.stderr.strip()),
        )
    if envelope.get("status") == "error":
        return EvaluationOutcome(
            status="child_error",
            elapsed_ms=elapsed_ms,
            exit_code=completed.returncode,
            error_type=str(envelope.get("error_type") or "UnknownError"),
            stderr_present=bool(completed.stderr.strip()),
        )
    return EvaluationOutcome(
        status="result",
        elapsed_ms=elapsed_ms,
        exit_code=completed.returncode,
        result=dict(envelope["result"]),
        stderr_present=bool(completed.stderr.strip()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--mode", default="analyzer", choices=("analyzer", "mock", "raise", "sleep"))
    parser.add_argument("--payload", required=True)
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    if not args.child:
        parser.error("this tool is invoked by its parent API")
    return _emit_child(payload, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
