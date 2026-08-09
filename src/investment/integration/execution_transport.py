"""No-retry loopback transport for Athena canonical simulation execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.investment.contracts.base import canonical_json_bytes
from src.investment.contracts.execution_mandate import ExecutionMandate
from src.investment.contracts.execution_result import ExecutionResult
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot


class ExecutionTransportUncertain(RuntimeError):
    """A dispatched request has no trustworthy canonical response; never retry it."""


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ExecutionTransportUncertain("execution endpoint redirect is forbidden")


def _without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate execution response key: {key}")
        result[key] = value
    return result


def _contract_json(payload: Any) -> str:
    return canonical_json_bytes(payload).decode("utf-8")


@dataclass(frozen=True)
class AthenaExecutionObservation:
    execution_result: ExecutionResult
    portfolio_snapshot: PortfolioSnapshot
    submitted_quantities: tuple[int, ...]


class CanonicalHttpAthenaExecutionTransport:
    """One POST attempt per mandate; reconciliation is a separate operation."""

    EXECUTE_PATH = "/v1/trading-spine/execute"
    RECONCILE_PATH = "/v1/trading-spine/reconcile"
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024

    def __init__(
        self,
        *,
        url: str,
        timeout_seconds: float = 5.0,
        opener: Callable[..., object] | None = None,
    ) -> None:
        parsed = urlsplit(str(url or "").strip())
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path != self.EXECUTE_PATH
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("M3 execution must use the exact loopback Trading Spine endpoint")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("M3 execution timeout must be in (0, 30]")
        self._execute_url = parsed.geturl()
        self._reconcile_url = urlunsplit(
            (parsed.scheme, parsed.netloc, self.RECONCILE_PATH, "", "")
        )
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener or build_opener(_RejectRedirects()).open

    def execute(
        self,
        mandate: ExecutionMandate,
        snapshot: PortfolioSnapshot,
    ) -> AthenaExecutionObservation:
        if not isinstance(mandate, ExecutionMandate):
            raise TypeError("canonical ExecutionMandate is required")
        if not isinstance(snapshot, PortfolioSnapshot):
            raise TypeError("canonical PortfolioSnapshot is required")
        payload = {
            "mandate": json.loads(mandate.canonical_json()),
            "snapshot": json.loads(snapshot.canonical_json()),
        }
        return self._observation(self._post(self._execute_url, payload), mandate)

    def reconcile(
        self,
        *,
        mandate: ExecutionMandate,
    ) -> AthenaExecutionObservation:
        if not isinstance(mandate, ExecutionMandate):
            raise TypeError("canonical ExecutionMandate is required")
        payload = {"mandate_id": mandate.mandate_id}
        return self._observation(self._post(self._reconcile_url, payload), mandate)

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = canonical_json_bytes(payload)
        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                final_url = str(getattr(response, "geturl", lambda: url)())
                if final_url != url:
                    raise ExecutionTransportUncertain(
                        "execution endpoint redirect is forbidden"
                    )
                if int(getattr(response, "status", 200)) != 200:
                    raise ExecutionTransportUncertain(
                        "execution endpoint did not return HTTP 200"
                    )
                raw = response.read(self.MAX_RESPONSE_BYTES + 1)
        except ExecutionTransportUncertain:
            raise
        except Exception as exc:
            raise ExecutionTransportUncertain(
                "execution response is unavailable; reconciliation is required"
            ) from exc
        if len(raw) > self.MAX_RESPONSE_BYTES:
            raise ExecutionTransportUncertain("execution response exceeds size limit")
        try:
            response_payload = json.loads(raw, object_pairs_hook=_without_duplicate_keys)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExecutionTransportUncertain("execution response is not canonical JSON") from exc
        if not isinstance(response_payload, dict):
            raise ExecutionTransportUncertain("execution response must be an object")
        return response_payload

    @staticmethod
    def _observation(
        response: dict[str, Any],
        mandate: ExecutionMandate,
    ) -> AthenaExecutionObservation:
        if set(response) != {"status", "result", "snapshot", "submitted_quantities"}:
            raise ExecutionTransportUncertain("execution response fields mismatch")
        if response["status"] != "OK":
            raise ExecutionTransportUncertain("execution response is not authoritative")
        try:
            result = ExecutionResult.model_validate_json(
                _contract_json(response["result"])
            )
            snapshot = PortfolioSnapshot.model_validate_json(
                _contract_json(response["snapshot"])
            )
        except Exception as exc:
            raise ExecutionTransportUncertain("execution contracts are invalid") from exc
        quantities = response["submitted_quantities"]
        if not isinstance(quantities, list) or any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in quantities
        ):
            raise ExecutionTransportUncertain("submission diagnostics are invalid")
        if (
            result.mandate_id != mandate.mandate_id
            or result.mandate_hash != mandate.content_hash
            or result.decision_id != mandate.decision_id
            or result.decision_hash != mandate.decision_hash
        ):
            raise ExecutionTransportUncertain("execution lineage mismatch")
        if result.submitted_quantity not in {0, mandate.quantity}:
            raise ExecutionTransportUncertain("Athena changed the Brain quantity")
        if any(value != mandate.quantity for value in quantities):
            raise ExecutionTransportUncertain("broker submission quantity mismatch")
        if (
            result.portfolio_snapshot_after_id != snapshot.snapshot_id
            or result.portfolio_snapshot_after_hash != snapshot.content_hash
        ):
            raise ExecutionTransportUncertain("ExecutionResult Snapshot B mismatch")
        return AthenaExecutionObservation(result, snapshot, tuple(quantities))
