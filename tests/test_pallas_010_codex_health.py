import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.v1.endpoints.agent import _canonical_codex_tool_sources
from src.services.codex_health import probe_codex_identity, summarize_generation_metrics
from src.services.dependency_health import DependencyHealthStore, configured_dependency_inventory


def test_codex_identity_requires_executable_and_chatgpt_login(monkeypatch):
    config = SimpleNamespace(
        generation_backend="codex_cli",
        agent_backend="auto",
        codex_cli_model="gpt-5.6-luna",
    )
    monkeypatch.setattr("src.services.codex_health.shutil.which", lambda name: "/usr/local/bin/codex")
    responses = iter([
        (True, "", "codex-cli 0.149.0-alpha.4.1"),
        (True, "", "Logged in using ChatGPT"),
    ])
    monkeypatch.setattr("src.services.codex_health._run_codex_command", lambda *args, **kwargs: next(responses))

    result = probe_codex_identity(config=config)

    assert result["status"] == "HEALTHY"
    assert result["expected_model"] == "gpt-5.6-luna"
    assert result["expected_provider"] == "codex_chatgpt_oauth"
    assert result["auth_mode"] == "codex_managed_chatgpt_oauth"
    assert result["metadata"]["login_status"] == "HEALTHY"


def test_codex_identity_login_failure_is_not_cleared_by_metadata(monkeypatch):
    config = SimpleNamespace(
        generation_backend="codex_cli",
        agent_backend="auto",
        codex_cli_model="gpt-5.6-luna",
    )
    monkeypatch.setattr("src.services.codex_health.shutil.which", lambda name: "/usr/local/bin/codex")
    responses = iter([
        (True, "", "codex-cli 0.149.0-alpha.4.1"),
        (False, "LOGIN_REQUIRED", ""),
    ])
    monkeypatch.setattr("src.services.codex_health._run_codex_command", lambda *args, **kwargs: next(responses))

    result = probe_codex_identity(config=config)

    assert result["status"] == "FAILED"
    assert result["failure_class"] == "LOGIN_REQUIRED"
    assert result["usable"] is False


def test_codex_generation_metrics_require_repeated_structured_samples_and_margin():
    summary = summarize_generation_metrics(
        [
            {"success": True, "latency_ms": 120000, "schema_valid": True},
            {"success": True, "latency_ms": 140000, "schema_valid": True},
        ],
        timeout_seconds=300,
    )

    assert summary["p50_latency_ms"] == 130000
    assert summary["p95_latency_ms"] == 140000
    assert summary["timeout_rate"] == 0.0
    assert summary["worst_case_margin_ms"] == 160000
    assert summary["status"] == "HEALTHY"
    assert summary["recommended_concurrency"] == 1


def test_codex_generation_metrics_never_promote_timeout_or_unstructured_sample():
    summary = summarize_generation_metrics(
        [
            {"success": True, "latency_ms": 100000, "schema_valid": False},
            {"success": False, "latency_ms": 300000, "failure_class": "TIMEOUT"},
        ],
        timeout_seconds=300,
    )

    assert summary["status"] == "DEGRADED"
    assert summary["structured_output_success_count"] == 0
    assert summary["timeout_count"] == 1
    assert summary["failure_class_counts"] == {"TIMEOUT": 1}


def test_research_sources_are_reconstructed_from_successful_tool_evidence():
    sources = _canonical_codex_tool_sources(
        ["get_strategy_backtest_summary returned a bounded result"],
        [
            {"tool": "get_strategy_backtest_summary", "success": True},
            {"tool": "get_analysis_context", "success": False},
        ],
    )

    assert sources == ["tool:get_strategy_backtest_summary"]


def test_research_endpoint_returns_only_canonical_successful_tool_refs():
    from api.v1.endpoints.agent import ResearchRequest, agent_research

    config = SimpleNamespace(
        agent_backend="codex_app_server",
        codex_cli_model="gpt-5.6-luna",
        is_agent_available=lambda: True,
    )
    result = SimpleNamespace(
        success=True,
        content=json.dumps({
            "report": "bounded report",
            "sources": ["get_analysis_context returned the selected evidence"],
        }),
        tool_calls_log=[{"tool": "get_analysis_context", "success": True}],
        total_tokens=12,
        model="gpt-5.6-luna",
        provider="codex_chatgpt_oauth",
        backend="codex_app_server",
        diagnostics={"latency_ms": 1200},
        usage={"total_tokens": 12},
    )
    executor = MagicMock()
    executor.chat.return_value = result

    with patch("api.v1.endpoints.agent.get_config", return_value=config), patch(
        "api.v1.endpoints.agent._build_executor", return_value=executor
    ):
        response = asyncio.run(agent_research(ResearchRequest(question="research")))

    assert response.success is True
    assert response.sources == ["tool:get_analysis_context"]


def test_research_endpoint_fails_closed_when_sources_are_ungrounded():
    from api.v1.endpoints.agent import ResearchRequest, agent_research

    config = SimpleNamespace(
        agent_backend="codex_app_server",
        codex_cli_model="gpt-5.6-luna",
        is_agent_available=lambda: True,
    )
    result = SimpleNamespace(
        success=True,
        content=json.dumps({"report": "ungrounded", "sources": ["invented source"]}),
        tool_calls_log=[{"tool": "get_analysis_context", "success": True}],
        total_tokens=12,
        model="gpt-5.6-luna",
        provider="codex_chatgpt_oauth",
        backend="codex_app_server",
        diagnostics={"latency_ms": 1200},
        usage={"total_tokens": 12},
    )
    executor = MagicMock()
    executor.chat.return_value = result
    with patch("api.v1.endpoints.agent.get_config", return_value=config), patch(
        "api.v1.endpoints.agent._build_executor", return_value=executor
    ), patch("src.services.codex_health.record_codex_generation_observation") as record:
        response = asyncio.run(agent_research(ResearchRequest(question="research")))

    assert response.success is False
    assert response.error == "CODEX_RESEARCH_SOURCE_EVIDENCE_UNGROUNDED"
    record.assert_called_once()
    assert record.call_args.kwargs["failure_class"] == "SOURCE_EVIDENCE_UNGROUNDED"


def test_research_source_text_cannot_create_tool_evidence():
    sources = _canonical_codex_tool_sources(
        ["invented_web_page"],
        [{"tool": "get_analysis_context", "success": True}],
    )

    assert sources == []


def test_dependency_inventory_names_codex_luna_as_the_only_llm_primary(monkeypatch):
    monkeypatch.setenv("GENERATION_BACKEND", "codex_cli")
    monkeypatch.setenv("CODEX_CLI_MODEL", "gpt-5.6-luna")
    inventory = configured_dependency_inventory()
    llm = [item for item in inventory if item["category"] == "LLM_RESEARCH"]

    assert llm == [
        {
            "dependency_id": "codex-luna",
            "category": "LLM_RESEARCH",
            "configured": True,
            "enabled": True,
            "role": "PRIMARY",
            "priority": 1,
            "endpoint": "codex://chatgpt-oauth",
            "model": "gpt-5.6-luna",
            "provider": "codex_chatgpt_oauth",
            "auth_mode": "codex_managed_chatgpt_oauth",
        }
    ]


def test_run_diagnostics_maps_codex_generation_to_codex_luna_health(monkeypatch, tmp_path):
    store = DependencyHealthStore(tmp_path / "diagnostics-health.json")
    monkeypatch.setattr("src.services.dependency_health.get_dependency_health_store", lambda: store)
    store.record_result(
        "codex-luna",
        category="LLM_RESEARCH",
        success=True,
        reachable=True,
        usable=True,
        records=1,
        observation_kind="identity",
    )

    from src.services.run_diagnostics import record_llm_run

    record_llm_run(
        success=True,
        provider="codex_chatgpt_oauth",
        model="gpt-5.6-luna",
        duration_ms=134710,
        tokens=27672,
        call_type="market_review",
    )

    row = store.snapshot()["dependencies"]["codex-luna"]
    assert row["status"] == "HEALTHY"
    assert row["generation_status"] == "HEALTHY"
    assert row["metadata"]["provider"] == "codex_chatgpt_oauth"
    assert "codex_chatgpt_oauth" not in store.snapshot()["dependencies"]
