"""Real admin-session and read-only API proof for M2 readiness."""

from pathlib import Path

from fastapi.testclient import TestClient

import src.auth as auth
from api.app import create_app
from api.v1.endpoints import single_brain_m2
from src.config import Config
from src.investment.m2.repository import M2OperationalRepository
from src.storage import DatabaseManager


def _reset_auth_globals():
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


def test_readiness_requires_valid_admin_session_and_exposes_get_only(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    db_path = tmp_path / "m2-readiness.db"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    env_path.write_text(
        "\n".join((
            "STOCK_LIST=600519",
            "GEMINI_API_KEY=test",
            "ADMIN_AUTH_ENABLED=true",
            f"DATABASE_PATH={db_path}",
        )) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    _reset_auth_globals()
    Config.reset_instance()
    DatabaseManager.reset_instance()

    class _Service:
        def __init__(self, *, runtime_scheduler=None):
            assert runtime_scheduler is not None

        def get(self):
            return {
                "execution_authorization": "OFF",
                "latest_cycle": None,
                "symbols": [],
            }

    monkeypatch.setattr(single_brain_m2, "SingleBrainM2ReadinessService", _Service)
    try:
        client = TestClient(create_app(static_dir=static_dir))
        assert client.get("/api/v1/single-brain/m2/readiness").status_code == 401
        invalid = client.get(
            "/api/v1/single-brain/m2/readiness",
            headers={"Cookie": f"{auth.COOKIE_NAME}=forged"},
        )
        assert invalid.status_code == 401

        login = client.post(
            "/api/v1/auth/login",
            json={"password": "m2-admin-password", "passwordConfirm": "m2-admin-password"},
        )
        assert login.status_code == 200, login.text
        valid = client.get("/api/v1/single-brain/m2/readiness")
        assert valid.status_code == 200
        assert valid.json()["item"]["execution_authorization"] == "OFF"
        assert client.post("/api/v1/single-brain/m2/readiness").status_code == 405
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()


def test_readiness_route_and_service_contain_no_mutation_methods():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "api/v1/endpoints/single_brain_m2.py",
        "src/services/single_brain_m2_readiness_service.py",
        "src/investment/m2/runtime_diagnostics.py",
    ):
        source = (root / relative).read_text(encoding="utf-8").lower()
        assert "@router.post" not in source
        assert "@router.put" not in source
        assert "@router.delete" not in source
        assert "persist_shadow" not in source


def test_readiness_failure_returns_500_without_mutating_operational_state(
    tmp_path,
    monkeypatch,
):
    env_path = tmp_path / ".env"
    db_path = tmp_path / "m2-readiness-failure.db"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    env_path.write_text(
        "\n".join((
            "STOCK_LIST=600519",
            "GEMINI_API_KEY=test",
            "ADMIN_AUTH_ENABLED=true",
            f"DATABASE_PATH={db_path}",
        )) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    _reset_auth_globals()
    Config.reset_instance()
    DatabaseManager.reset_instance()

    class _FailingService:
        def __init__(self, *, runtime_scheduler=None):
            assert runtime_scheduler is not None

        def get(self):
            raise OSError("read-only storage unavailable")

    monkeypatch.setattr(
        single_brain_m2,
        "SingleBrainM2ReadinessService",
        _FailingService,
    )
    try:
        db = DatabaseManager.get_instance()
        before = M2OperationalRepository(db).readiness()
        client = TestClient(create_app(static_dir=static_dir))
        login = client.post(
            "/api/v1/auth/login",
            json={"password": "m2-admin-password", "passwordConfirm": "m2-admin-password"},
        )
        assert login.status_code == 200, login.text

        response = client.get("/api/v1/single-brain/m2/readiness")

        assert response.status_code == 500
        assert M2OperationalRepository(db).readiness() == before
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()


def test_readiness_projects_actual_single_m2_scheduler_authority(monkeypatch):
    from src.services.single_brain_m2_readiness_service import (
        SingleBrainM2ReadinessService,
    )

    class _Repository:
        def readiness(self):
            return {"latest_cycle": None, "symbols": []}

        def latest_authoritative_snapshot(self):
            return None

    class _Scheduler:
        def status(self):
            return {
                "enabled": True,
                "mode": "M2_SHADOW_ONLY",
                "background_tasks": [{
                    "name": "single_brain_m2_shadow",
                    "interval_seconds": 3600,
                    "next_run_at": "2026-08-09T03:00:00",
                }],
            }

    monkeypatch.setattr(
        "src.services.single_brain_m2_readiness_service.get_config",
        lambda: type("_Config", (), {"single_brain_m2_enabled": True})(),
    )
    readiness = SingleBrainM2ReadinessService(
        repository=_Repository(),
        runtime_scheduler=_Scheduler(),
    ).get()

    assert readiness["execution_authorization"] == "OFF"
    assert readiness["recurring_scheduler"] == {
        "enabled": True,
        "mode": "M2_SHADOW_ONLY",
        "authority_count": 1,
        "interval_seconds": 3600,
        "next_run_at": "2026-08-09T03:00:00",
    }
