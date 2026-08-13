"""Focused tests for the non-production local-Qwen evaluation transport."""

from __future__ import annotations

import importlib.util
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace


_TOOL_PATH = Path(__file__).parents[1] / "tools" / "local_qwen_evaluation.py"
_SPEC = importlib.util.spec_from_file_location("local_qwen_evaluation", _TOOL_PATH)
assert _SPEC and _SPEC.loader
evaluation = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = evaluation
_SPEC.loader.exec_module(evaluation)


def test_mock_analysis_result_survives_child_transport_and_serialization():
    outcome = evaluation.evaluate_payload({}, mode="mock", timeout_seconds=2)

    assert outcome.status == "result"
    assert outcome.exit_code == 0
    assert outcome.result == {
        "success": True,
        "model_used": "openai/Qwen3-14B-MLX-6bit",
        "action": "buy",
        "decision_type": "buy",
        "entry": 10.0,
        "stop": 9.0,
        "target": 11.0,
        "raw_response_present": True,
        "error_type": None,
    }


def test_child_exception_is_explicit_not_swallowed():
    outcome = evaluation.evaluate_payload({}, mode="raise", timeout_seconds=2)

    assert outcome.status == "child_error"
    assert outcome.error_type == "RuntimeError"
    assert outcome.exit_code == 0


def test_child_persists_sanitized_result_when_a_parent_capture_is_unavailable(tmp_path):
    result_path = tmp_path / "evaluation-result.json"

    outcome = evaluation.evaluate_payload(
        {}, mode="mock", timeout_seconds=2, result_path=result_path
    )

    assert outcome.status == "result"
    persisted = json.loads(result_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "result"
    assert persisted["result"]["action"] == "buy"


def test_evaluation_mode_suppresses_analyzer_usage_persistence():
    writes = []

    class FakeAnalyzer:
        def analyze(self, context, **kwargs):
            return evaluation._mock_result()

    fake_module = SimpleNamespace(
        persist_llm_usage=lambda *args, **kwargs: writes.append((args, kwargs)),
        GeminiAnalyzer=FakeAnalyzer,
    )

    result = evaluation._run_analyzer({"context": {}}, analyzer_module=fake_module)

    assert result.action == "buy"
    assert writes == []


def test_timeout_is_distinct_from_model_or_parser_failure():
    outcome = evaluation.evaluate_payload(
        {"sleep_seconds": 0.2}, mode="sleep", timeout_seconds=0.01
    )

    assert outcome.status == "timeout"
    assert outcome.exit_code is None


def test_transport_uses_an_isolated_child_session():
    source = _TOOL_PATH.read_text(encoding="utf-8")

    assert "start_new_session=True" in source


def test_tool_has_no_authoritative_or_execution_imports():
    tree = ast.parse(_TOOL_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert imported.count("src.analyzer") == 1  # Lazily imported only in child mode.
    assert not any(
        name.startswith(("src.investment", "src.trading", "src.risk", "src.portfolio"))
        for name in imported
    )
