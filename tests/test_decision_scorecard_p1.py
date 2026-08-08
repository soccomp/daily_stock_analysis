"""P1C persistent, read-only Single Decision Scorecard."""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from api.v1.endpoints import decision_scorecards
from src.investment.canary import InvestmentCanaryService
from src.investment.integration import LocalAthenaCanaryTransport
from src.repositories.decision_scorecard_repo import (
    DecisionScorecardConflictError,
    DecisionScorecardRepository,
)
from src.services.decision_scorecard_service import (
    DecisionScorecardNotFoundError,
    DecisionScorecardService,
)
from src.storage import DatabaseManager
from tests.test_investment_canary_p1 import ATHENA_ROOT
from tests.test_investment_shadow_wiring_p1a import (
    NOW,
    _analysis_result,
    _policy,
)


def _canary_artifacts(tmp_path):
    with LocalAthenaCanaryTransport.for_athena_worktree(
        athena_root=ATHENA_ROOT,
        journal_path=tmp_path / "athena-scorecard-canary.jsonl",
        account_id="simulation-account-1",
        symbol="600519",
        allowed_symbols=("600519",),
        cash=Decimal("970000.00"),
        position_quantity=300,
        avg_cost=Decimal("90.00"),
        last_price=Decimal("100.00"),
        now=NOW,
    ) as transport:
        return InvestmentCanaryService(clock=lambda: NOW).run_from_analysis(
            result=_analysis_result(),
            context_snapshot={"data_quality": {"level": "good"}},
            source_report_id=42,
            trace_id="trace-p1c-scorecard",
            trigger_source="p1c_test",
            risk_policy=_policy(),
            transport=transport,
            account_id="simulation-account-1",
            allowed_symbols=frozenset({"600519"}),
        )


@pytest.mark.integration
def test_scorecard_persists_and_reconstructs_one_complete_decision_lineage(tmp_path):
    if not (ATHENA_ROOT / "src" / "trading_spine" / "canary.py").is_file():
        pytest.skip("sibling Athena P1 canary repository is unavailable")
    artifacts = _canary_artifacts(tmp_path)
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'scorecards.db'}")
    try:
        service = DecisionScorecardService(db_manager=db)
        created = service.persist_canary(artifacts)
        duplicate = service.persist_canary(artifacts)
        restored = service.get(artifacts.investment_decision.decision_id)["item"]
    finally:
        DatabaseManager.reset_instance()

    assert created["created"] is True
    assert duplicate["created"] is False
    assert restored["research_bundle"]["research_id"] == (
        artifacts.research_bundle.research_id
    )
    assert restored["portfolio_snapshot_a"]["snapshot_id"] == (
        artifacts.portfolio_snapshot_a.snapshot_id
    )
    assert restored["risk_policy"]["policy_id"] == artifacts.risk_policy.policy_id
    assert restored["investment_decision"]["decision_id"] == (
        artifacts.investment_decision.decision_id
    )
    assert restored["decision_signal"]["metadata"]["investment_decision_id"] == (
        artifacts.investment_decision.decision_id
    )
    assert restored["execution_mandate"]["quantity"] == 200
    assert restored["execution_results"][0]["submitted_quantity"] == 200
    assert restored["portfolio_snapshot_b"]["positions"][0]["quantity"] == 500
    diagnostics = restored["execution_diagnostics"]
    assert diagnostics == {
        "requested_quantity": 200,
        "submitted_quantity": 200,
        "filled_quantity": 200,
        "remaining_quantity": 0,
        "average_fill_price": "100.0",
        "fees": "0",
        "slippage_bps": "0",
        "execution_state": "FILLED",
        "reconciliation_state": "RECONCILED",
    }
    assert len(restored["scorecard_hash"]) == 64


def test_scorecard_repository_is_write_once_and_detects_conflict(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'scorecard-conflict.db'}")
    try:
        repo = DecisionScorecardRepository(db)
        repo.create_if_absent(
            decision_id="decision-immutable",
            trace_id="trace-immutable",
            account_id="simulation-account-1",
            symbol="600519",
            action="ADD",
            payload_hash="1" * 64,
            payload_json='{"immutable":true}',
        )
        with pytest.raises(DecisionScorecardConflictError):
            repo.create_if_absent(
                decision_id="decision-immutable",
                trace_id="trace-immutable",
                account_id="simulation-account-1",
                symbol="600519",
                action="ADD",
                payload_hash="2" * 64,
                payload_json='{"immutable":false}',
            )
    finally:
        DatabaseManager.reset_instance()


def test_scorecard_api_is_get_only_and_maps_not_found(monkeypatch):
    paths = {
        (route.path, method)
        for route in decision_scorecards.router.routes
        for method in getattr(route, "methods", set())
    }
    assert ("/{decision_id}", "GET") in paths
    assert not any(
        path.startswith("/") and method != "GET"
        for path, method in paths
    )

    class MissingService:
        def get(self, decision_id):
            raise DecisionScorecardNotFoundError(decision_id)

    monkeypatch.setattr(
        decision_scorecards,
        "DecisionScorecardService",
        MissingService,
    )
    with pytest.raises(Exception) as error:
        decision_scorecards.get_scorecard("missing-decision")
    assert getattr(error.value, "status_code", None) == 404


def test_scorecard_layers_have_no_decision_execution_or_retry_authority():
    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "src" / "investment" / "scorecard.py",
        root / "src" / "services" / "decision_scorecard_service.py",
        root / "src" / "repositories" / "decision_scorecard_repo.py",
        root / "api" / "v1" / "endpoints" / "decision_scorecards.py",
    )
    forbidden_calls = {
        "project",
        "submit",
        "retry",
        "reconcile",
        "capture_snapshot",
        "create_mandate",
    }
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert "src.investment.decision.engine" not in imports, (path, imports)
        assert not any(
            name.startswith("src.investment.execution_projection")
            for name in imports
        ), (path, imports)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert calls.isdisjoint(forbidden_calls), (path, calls & forbidden_calls)
