"""PALLAS-002 real DSA REDUCE handoff into isolated Athena authority."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

from src.investment.m2.orchestration import AnalysisCompletion
from src.investment.proposal.builder import InvestmentProposalBuilder, ProposalBuildRejected
from src.investment.proposal.orchestration import ProposalHandoffLoopService
from src.investment.proposal.transport import CanonicalHttpInvestmentProposalPublisher
from tests.test_investment_proposal_issue_9 import NOW, _result
from tests.test_investment_shadow_wiring_p1a import _snapshot


def _reduce_result(target: str = "建议仓位：2%"):
    result = _result("reduce")
    result.dashboard = {
        "battle_plan": {"position_strategy": {"suggested_position": target}},
    }
    return result


def test_reduce_target_comes_from_structured_position_strategy_and_authoritative_snapshot():
    artifacts = InvestmentProposalBuilder(clock=lambda: NOW).build(
        result=_reduce_result(),
        context_snapshot={},
        source_report_id=17,
        cycle_id="cycle-pallas-002-real-reduce",
        trigger_source="test",
        authoritative_snapshot=_snapshot(),
    )

    assert artifacts.proposal.action == "REDUCE"
    assert artifacts.proposal.suggested_target_weight == Decimal("0.020000")
    assert artifacts.proposal.advisory_only is True
    assert artifacts.proposal.final_allocation_permitted is False
    assert artifacts.proposal.execution_permitted is False


def test_reduce_target_without_deterministic_structured_semantics_fails_closed():
    with pytest.raises(ProposalBuildRejected, match="not deterministic"):
        InvestmentProposalBuilder(clock=lambda: NOW).build(
            result=_reduce_result("小仓/低仓位"),
            context_snapshot={},
            source_report_id=18,
            cycle_id="cycle-pallas-002-ambiguous-reduce",
            trigger_source="test",
            authoritative_snapshot=_snapshot(),
        )


def test_reduce_target_must_be_lower_than_authoritative_current_weight():
    with pytest.raises(ProposalBuildRejected, match="lower than current"):
        InvestmentProposalBuilder(clock=lambda: NOW).build(
            result=_reduce_result("建议仓位：5%"),
            context_snapshot={},
            source_report_id=19,
            cycle_id="cycle-pallas-002-invalid-reduce",
            trigger_source="test",
            authoritative_snapshot=_snapshot(),
        )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(process: subprocess.Popen[str], url: str) -> None:
    for _ in range(100):
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            raise AssertionError(f"isolated Athena server exited: {stderr}")
        try:
            with urlopen(url, timeout=0.2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.05)
    raise AssertionError("isolated Athena server did not become ready")


def test_real_proposal_handoff_reduce_reaches_athena_decrease_and_sell(tmp_path):
    repo_root = Path(__file__).parents[2]
    athena_root = Path(
        os.environ.get("PALLAS_002_ATHENA_IMPL_ROOT", repo_root / "pallas-002-athena-impl")
    )
    if not athena_root.is_dir():
        pytest.fail(f"Athena candidate worktree is required: {athena_root}")
    athena_python = Path(
        os.environ.get(
            "PALLAS_002_ATHENA_PYTHON",
            "/Users/m5air/Documents/Athena/.venv/bin/python",
        )
    )
    if not athena_python.is_file():
        athena_python = Path(sys.executable)
    port = _free_port()
    result_path = tmp_path / "athena-result.json"
    server_script = Path(__file__).with_name("pallas_002_athena_intake_server.py")
    portfolio = {
        "simulation_only": True,
        "LIVE_TRADING": False,
        "account_scope": "athena-sim",
        "account_mode": "SIMULATION",
        "reconciliation_status": "RECONCILED",
        "equity": "1000000",
        "cash": "400000",
        "broker_snapshot_ref": "pallas-002-real-reduce-snapshot",
        "holdings": [{"symbol": "SHSE.600519", "quantity": 300, "market_price": "100"}],
    }
    env = {
        **os.environ,
        "PYTHONPATH": str(athena_root),
        "PALLAS_ATHENA_ROOT": str(athena_root),
        "PALLAS_ATHENA_PORTFOLIO": json.dumps(portfolio),
        "PALLAS_TEST_NOW": NOW.isoformat(),
    }
    process = subprocess.Popen(
        [str(athena_python), str(server_script), str(port), str(tmp_path / "athena.jsonl"), str(result_path)],
        cwd=athena_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_server(process, f"{base_url}/health")

        class Runner:
            def complete(self, **kwargs):
                result = _reduce_result()
                result.code = kwargs["symbol"]
                return AnalysisCompletion(result, {}, 20, False, NOW)

        class SnapshotSource:
            def capture_snapshot(self):
                return _snapshot()

        config = SimpleNamespace(
            single_brain_m2_enabled=True,
            single_brain_m2_interval_minutes=60,
            single_brain_m2_symbols=("600519",),
            single_brain_m2_max_symbols=1,
            single_brain_m2_holdings_limit=1,
        )
        result = ProposalHandoffLoopService(
            config=config,
            analysis_runner=Runner(),
            publisher=CanonicalHttpInvestmentProposalPublisher(
                url=f"{base_url}/api/investment-proposals"
            ),
            snapshot_source=SnapshotSource(),
            clock=lambda: NOW,
        ).run_cycle(scheduled_for=NOW)

        assert result.status == "COMPLETED"
        assert result.acknowledgements[0].acknowledgement_state == "ACCEPTED"
        assert result.acknowledgements[0].lifecycle_state == "ALLOCATED"
        athena_result = json.loads(result_path.read_text(encoding="utf-8"))
        assert athena_result["research_id"] == "research-" + result.proposal_ids[0].removeprefix("proposal-")
        assert athena_result["proposal_id"] == result.proposal_ids[0]
        assert athena_result["proposal"]["action"] == "REDUCE"
        assert athena_result["proposal"]["suggested_target_weight"] == "0.020000"
        assert athena_result["allocation_decision"]["athena_action"] == "DECREASE"
        assert athena_result["allocation_decision"]["final_delta_quantity"] == -100
        assert athena_result["allocation_decision"]["decision_origin"] == "DSA_RESEARCH"
        assert athena_result["risk_decision"]["decision_origin"] == "ATHENA_RISK"
        assert athena_result["mandate"]["action"] == "SELL"
        investment = athena_result["investment_decision"]
        assert investment["dsa_action"] == "REDUCE"
        assert investment["athena_action"] == "DECREASE"
        assert investment["decision_origin"] == "DSA_RESEARCH"
        assert investment["current_position_state"] == "OPEN"
        assert investment["current_position_quantity"] == 300
        assert investment["semantic_reason"] == "DSA_REDUCE"
        assert athena_result["acknowledgement"]["acknowledgement_state"] == "ACCEPTED"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
