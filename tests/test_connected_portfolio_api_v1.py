"""Read-only connected PortfolioSnapshot service and API proof."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

import src.auth as auth
from api.app import create_app
from api.v1.endpoints import portfolio
from src.config import Config
from src.investment.contracts.portfolio_snapshot import (
    ActiveOrder,
    PortfolioSnapshot,
    Position,
)
from src.investment.integration.runtime_snapshot_ingress import SnapshotIngressError
from src.services.connected_portfolio_service import (
    ConnectedPortfolioSnapshotService,
    ConnectedPortfolioSnapshotUnavailable,
)
from src.storage import DatabaseManager


NOW = datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)
ACCOUNT_ID = "simulation-account-1"


def _snapshot(
    *,
    as_of: datetime = NOW,
    created_at: datetime | None = None,
    account_id: str = ACCOUNT_ID,
    account_mode: str = "SIMULATION",
    reconciliation_status: str = "DEGRADED",
    data_quality: str = "MEDIUM",
) -> PortfolioSnapshot:
    return PortfolioSnapshot.build(
        snapshot_id="snapshot-connected-v1",
        trace_id="trace-connected-v1",
        created_at=created_at or as_of,
        producer="ATHENA_SIMULATION_RECONCILIATION",
        account_id=account_id,
        broker="ATHENA_DECIMAL_SIM",
        account_mode=account_mode,
        as_of=as_of,
        revision=7,
        currency="HKD",
        equity=Decimal("1000000.120000"),
        cash=Decimal("400000.120000"),
        available_cash=Decimal("399000.120000"),
        reserved_cash=Decimal("1000.000000"),
        positions=(
            Position(
                symbol="600519",
                market="CN",
                quantity=300,
                available_quantity=280,
                avg_cost=Decimal("90.120000"),
                last_price=Decimal("100.340000"),
                market_value=Decimal("30102.000000"),
                unrealized_pnl=Decimal("3066.000000"),
                price_as_of=as_of,
                price_source="ATHENA_RUNTIME",
            ),
            Position(
                symbol="600519",
                market="HK",
                quantity=20,
                available_quantity=20,
                avg_cost=Decimal("88.000000"),
                last_price=Decimal("91.000000"),
                market_value=Decimal("1820.000000"),
                unrealized_pnl=Decimal("60.000000"),
                price_as_of=as_of,
                price_source="ATHENA_RUNTIME",
            ),
        ),
        active_orders=(
            ActiveOrder(
                broker_order_id="order-read-only-1",
                symbol="600519",
                side="BUY",
                quantity=100,
                filled_quantity=40,
                remaining_quantity=60,
                state="PARTIALLY_FILLED",
                reserved_cash=Decimal("1000.000000"),
                submitted_at=as_of - timedelta(minutes=1),
            ),
        ),
        realized_pnl=Decimal("120.000000"),
        unrealized_pnl=Decimal("3126.000000"),
        reconciliation_status=reconciliation_status,
        data_quality=data_quality,
        limitations=("部分行情来自延迟报价",),
        broker_snapshot_ref="athena-sim:connected-v1",
        supersedes_id="snapshot-connected-v0",
    )


class _Source:
    def __init__(
        self,
        snapshot: PortfolioSnapshot | None = None,
        *,
        received_at: datetime = NOW,
        error: Exception | None = None,
    ) -> None:
        self.snapshot = snapshot or _snapshot()
        self.last_response_received_at = received_at
        self.error = error

    def capture_snapshot(self) -> PortfolioSnapshot:
        if self.error is not None:
            raise self.error
        return self.snapshot


def _service(source: _Source) -> ConnectedPortfolioSnapshotService:
    return ConnectedPortfolioSnapshotService(
        config=SimpleNamespace(single_brain_m2_account_id=ACCOUNT_ID),
        snapshot_source=source,
        clock=lambda: NOW,
    )


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


def _manual_ledger_counts(db: DatabaseManager) -> dict[str, int]:
    table_names = (
        "portfolio_accounts",
        "portfolio_trades",
        "portfolio_cash_ledger",
        "portfolio_corporate_actions",
        "portfolio_positions",
        "portfolio_position_lots",
        "portfolio_daily_snapshots",
    )
    with db.get_session() as session:
        return {
            table_name: int(
                session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
            )
            for table_name in table_names
        }


def test_connected_service_preserves_exact_canonical_snapshot_facts() -> None:
    snapshot = _snapshot()

    item = _service(_Source(snapshot)).get()["item"]
    roundtrip = PortfolioSnapshot.model_validate_json(
        json.dumps(item, ensure_ascii=False)
    )

    assert roundtrip.content_hash == snapshot.content_hash
    assert roundtrip.canonical_json() == snapshot.canonical_json()
    assert item["currency"] == "HKD"
    assert item["cash"] == "400000.120000"
    assert {(item["market"], item["symbol"]) for item in item["positions"]} == {
        ("CN", "600519"),
        ("HK", "600519"),
    }
    assert item["active_orders"][0]["quantity"] == 100
    assert item["active_orders"][0]["state"] == "PARTIALLY_FILLED"
    assert item["reconciliation_status"] == "DEGRADED"
    assert item["data_quality"] == "MEDIUM"
    assert item["limitations"] == ["部分行情来自延迟报价"]


@pytest.mark.parametrize(
    ("snapshot", "received_at", "reason"),
    (
        (_snapshot(account_id="another-account"), NOW, "identity"),
        (_snapshot(account_mode="PAPER"), NOW, "simulation-only"),
        (_snapshot(as_of=NOW - timedelta(minutes=5, microseconds=1)), NOW, "stale"),
        (_snapshot(as_of=NOW + timedelta(seconds=1, microseconds=1)), NOW, "future"),
        (
            _snapshot(),
            NOW.replace(tzinfo=None),
            "timezone-aware",
        ),
    ),
)
def test_connected_service_fails_closed_on_invalid_authority(
    snapshot: PortfolioSnapshot,
    received_at: datetime,
    reason: str,
) -> None:
    with pytest.raises(ConnectedPortfolioSnapshotUnavailable, match=reason):
        _service(_Source(snapshot, received_at=received_at)).get()


def test_connected_service_accepts_exact_clock_skew_boundary_without_rehashing() -> None:
    snapshot = _snapshot(as_of=NOW + timedelta(seconds=1))

    item = _service(_Source(snapshot, received_at=NOW)).get()["item"]

    assert item["as_of"] == "2026-08-09T03:00:01Z"
    assert item["content_hash"] == snapshot.content_hash


def test_connected_service_rejects_non_utc_producer_timestamps() -> None:
    offset = timezone(timedelta(hours=8))
    snapshot = _snapshot(
        as_of=datetime(2026, 8, 9, 11, 0, tzinfo=offset),
        created_at=datetime(2026, 8, 9, 11, 0, tzinfo=offset),
    )

    with pytest.raises(ConnectedPortfolioSnapshotUnavailable, match="must be UTC"):
        _service(_Source(snapshot)).get()


def test_connected_service_maps_ingress_failure_to_unavailable() -> None:
    source = _Source(error=SnapshotIngressError("worker unavailable"))

    with pytest.raises(ConnectedPortfolioSnapshotUnavailable, match="unavailable"):
        _service(source).get()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source", "DSA_MANUAL"),
        ("authoritative", False),
        ("read_only", False),
        ("simulation_only", False),
    ),
)
def test_connected_service_rejects_any_weakened_authority_semantics(
    field: str,
    value: object,
) -> None:
    payload = _snapshot().model_dump()
    payload[field] = value
    malformed = PortfolioSnapshot.model_construct(**payload)

    with pytest.raises(
        ConnectedPortfolioSnapshotUnavailable,
        match="authority semantics|simulation-only",
    ):
        _service(_Source(malformed)).get()


def test_connected_endpoint_is_get_only_and_does_not_touch_manual_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "portfolio-connected.db"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("ADMIN_AUTH_ENABLED", "false")
    DatabaseManager.reset_instance()
    Config.reset_instance()

    class _Service:
        def get(self):
            return {"item": json.loads(_snapshot().canonical_json())}

    monkeypatch.setattr(portfolio, "ConnectedPortfolioSnapshotService", _Service)
    try:
        db = DatabaseManager.get_instance()
        before = _manual_ledger_counts(db)
        client = TestClient(create_app(static_dir=static_dir))

        response = client.get("/api/v1/portfolio/connected-snapshot")

        assert response.status_code == 200
        assert response.json()["item"]["content_hash"] == _snapshot().content_hash
        for method in ("post", "put", "patch", "delete"):
            assert getattr(client, method)(
                "/api/v1/portfolio/connected-snapshot"
            ).status_code == 405
        after = _manual_ledger_counts(db)
        assert after == before
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()


def test_connected_endpoint_preserves_real_global_admin_session_convention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    db_path = tmp_path / "connected-auth.db"
    static_dir = tmp_path / "static"
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

    class _Service:
        def get(self):
            return {"item": json.loads(_snapshot().canonical_json())}

    monkeypatch.setattr(portfolio, "ConnectedPortfolioSnapshotService", _Service)
    try:
        client = TestClient(create_app(static_dir=static_dir))
        path = "/api/v1/portfolio/connected-snapshot"
        assert client.get(path).status_code == 401
        assert client.get(
            path,
            headers={"Cookie": f"{auth.COOKIE_NAME}=forged"},
        ).status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            json={
                "password": "portfolio-admin-password",
                "passwordConfirm": "portfolio-admin-password",
            },
        )
        assert login.status_code == 200, login.text
        assert client.get(path).status_code == 200
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()


def test_connected_surface_has_no_execution_or_manual_ledger_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    service_source = (
        root / "src/services/connected_portfolio_service.py"
    ).read_text(encoding="utf-8").lower()
    endpoint_source = (root / "api/v1/endpoints/portfolio.py").read_text(
        encoding="utf-8"
    ).lower()

    for forbidden in (
        "portfolio_service",
        "databasemanager",
        "executionmandate",
        "executionresult",
        "submit_order",
        "reconcile(",
        "cancel_order",
        "broker sdk",
    ):
        assert forbidden not in service_source
    route_block = endpoint_source.split('@router.get(\n    "/connected-snapshot"', 1)[1]
    route_block = route_block.split("@router.post(", 1)[0]
    assert "@router.post" not in route_block
    assert "@router.put" not in route_block
    assert "@router.patch" not in route_block
    assert "@router.delete" not in route_block
