"""P1C persistent, read-only Single Decision Scorecard."""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.auth as auth
from api.app import create_app
from api.v1.endpoints import decision_scorecards
from src.config import Config
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


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


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


def test_scorecard_api_requires_a_real_valid_admin_session(tmp_path, monkeypatch):
    """Exercise the real app middleware and signed login cookie end to end."""

    env_path = tmp_path / ".env"
    db_path = tmp_path / "scorecard-auth.db"
    static_dir = tmp_path / "empty-static"
    static_dir.mkdir()
    env_path.write_text(
        "\n".join(
            (
                "STOCK_LIST=600519",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=true",
                f"DATABASE_PATH={db_path}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    _reset_auth_globals()
    Config.reset_instance()
    DatabaseManager.reset_instance()

    class ReadOnlyScorecardService:
        def get(self, decision_id):
            return {"item": {"decision_id": decision_id, "read_only": True}}

        def list(self, **_filters):
            return {"items": [], "total": 0, "page": 1, "page_size": 20}

    monkeypatch.setattr(
        decision_scorecards,
        "DecisionScorecardService",
        ReadOnlyScorecardService,
    )
    try:
        client = TestClient(create_app(static_dir=static_dir))

        unauthenticated = client.get("/api/v1/decision-scorecards/decision-auth")
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["error"] == "unauthorized"
        assert client.get("/api/v1/decision-scorecards").status_code == 401

        invalid = client.get(
            "/api/v1/decision-scorecards/decision-auth",
            headers={"Cookie": f"{auth.COOKIE_NAME}=forged-session"},
        )
        assert invalid.status_code == 401
        assert invalid.json()["error"] == "unauthorized"
        invalid_list = client.get(
            "/api/v1/decision-scorecards",
            headers={"Cookie": f"{auth.COOKIE_NAME}=forged-session"},
        )
        assert invalid_list.status_code == 401

        login = client.post(
            "/api/v1/auth/login",
            json={"password": "scorecard-admin", "passwordConfirm": "scorecard-admin"},
        )
        assert login.status_code == 200, login.text
        assert auth.verify_session(client.cookies.get(auth.COOKIE_NAME))

        authenticated = client.get("/api/v1/decision-scorecards/decision-auth")
        assert authenticated.status_code == 200, authenticated.text
        assert authenticated.json() == {
            "item": {"decision_id": "decision-auth", "read_only": True}
        }
        authenticated_list = client.get("/api/v1/decision-scorecards")
        assert authenticated_list.status_code == 200
        assert authenticated_list.json() == {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
        }
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()


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
