"""Canonical read-only boundary tests for the Athena M2 snapshot ingress."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.investment.integration.runtime_snapshot_ingress import (
    CanonicalHttpPortfolioSnapshotSource,
    SnapshotIngressError,
    _RejectRedirects,
)
from tests.test_investment_shadow_wiring_p1a import _snapshot


URL = "http://127.0.0.1:18761/v1/simulation/portfolio-snapshot"


class _Response:
    status = 200

    def __init__(self, payload: bytes, *, final_url: str = URL) -> None:
        self._payload = payload
        self._final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit: int) -> bytes:
        return self._payload

    def geturl(self) -> str:
        return self._final_url


def test_ingress_gets_exact_loopback_canonical_contract_without_decimal_loss():
    seen = []

    def open_request(request, *, timeout):
        seen.append((request.full_url, request.method, timeout))
        return _Response(_snapshot().canonical_json().encode("utf-8"))

    source = CanonicalHttpPortfolioSnapshotSource(
        url=URL,
        timeout_seconds=3,
        opener=open_request,
    )
    observed = source.capture_snapshot()

    assert observed == _snapshot()
    assert seen == [(URL, "GET", 3.0)]


@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1:18761/v1/simulation/portfolio",
        "http://127.0.0.1:18761/v1/simulation/portfolio-snapshot?submit=1",
        "http://user:secret@127.0.0.1:18761/v1/simulation/portfolio-snapshot",
        "https://127.0.0.1:18761/v1/simulation/portfolio-snapshot",
        "http://example.com/v1/simulation/portfolio-snapshot",
    ),
)
def test_ingress_rejects_every_noncanonical_location(url):
    with pytest.raises(ValueError, match="exact loopback"):
        CanonicalHttpPortfolioSnapshotSource(url=url)


def test_ingress_rejects_redirect_or_final_url_drift():
    source = CanonicalHttpPortfolioSnapshotSource(
        url=URL,
        opener=lambda *_args, **_kwargs: _Response(
            _snapshot().canonical_json().encode("utf-8"),
            final_url="http://localhost:18761/v1/simulation/portfolio-snapshot",
        ),
    )
    with pytest.raises(SnapshotIngressError, match="redirect"):
        source.capture_snapshot()


def test_default_redirect_handler_refuses_before_building_a_followup_request():
    with pytest.raises(SnapshotIngressError, match="redirect"):
        _RejectRedirects().redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "http://example.com/steal",
        )


def test_m2_runtime_modules_have_no_order_or_broker_capability_imports():
    root = Path(__file__).resolve().parents[1]
    paths = tuple((root / "src" / "investment" / "m2").glob("*.py")) + (
        root / "src" / "investment" / "integration" / "runtime_snapshot_ingress.py",
        root / "src" / "services" / "single_brain_m2_readiness_service.py",
    )
    forbidden_import_parts = {
        "canary",
        "execution_mandate",
        "broker",
        "gmtrade",
    }
    forbidden_calls = {"submit", "retry", "cancel", "dispatch", "post"}
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
        assert not any(
            part in name.lower()
            for name in imports
            for part in forbidden_import_parts
        ), path
        called = {
            node.func.attr.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert called.isdisjoint(forbidden_calls), path
