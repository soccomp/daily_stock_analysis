"""Canonical JSON transport for the local Athena simulation canary."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, TextIO

from src.investment.contracts.execution_mandate import ExecutionMandate
from src.investment.contracts.execution_result import ExecutionResult
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot


def _without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate canary response key: {key}")
        payload[key] = value
    return payload


def _wire(contract: Any) -> dict[str, Any]:
    return json.loads(contract.canonical_json(), object_pairs_hook=_without_duplicate_keys)


def _contract_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(frozen=True)
class CanaryExecutionObservation:
    """One Athena response; no method can submit or retry it."""

    execution_result: ExecutionResult
    portfolio_snapshot: PortfolioSnapshot
    submitted_quantities: tuple[int, ...]


class AthenaCanaryTransport(Protocol):
    """The only DSA orchestration surface allowed to reach Athena in P1."""

    def capture_snapshot(self) -> PortfolioSnapshot:
        ...

    def execute(
        self,
        mandate: ExecutionMandate,
        snapshot: PortfolioSnapshot,
    ) -> CanaryExecutionObservation:
        ...


class LocalAthenaCanaryTransport:
    """One bounded local subprocess session speaking canonical JSON lines."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        cwd: str | Path,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("a fixed non-empty Athena canary command is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        self._process = subprocess.Popen(
            list(command),
            cwd=Path(cwd),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()

    @classmethod
    def for_athena_worktree(
        cls,
        *,
        athena_root: str | Path,
        journal_path: str | Path,
        account_id: str,
        symbol: str,
        allowed_symbols: Sequence[str],
        cash: Decimal,
        position_quantity: int,
        avg_cost: Decimal,
        last_price: Decimal,
        now: datetime | None = None,
        timeout_seconds: float = 30.0,
    ) -> "LocalAthenaCanaryTransport":
        root = Path(athena_root).resolve()
        journal = Path(journal_path).resolve()
        if not (root / "src" / "trading_spine" / "canary.py").is_file():
            raise ValueError("Athena P1 canary module is unavailable")
        if not allowed_symbols:
            raise ValueError("a non-empty canary symbol allowlist is required")
        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("canary timestamp must include a timezone")
        command = [
            sys.executable,
            "-m",
            "src.trading_spine.canary",
            "--account-id",
            account_id,
            "--symbol",
            symbol,
            "--cash",
            format(cash, "f"),
            "--position-quantity",
            str(position_quantity),
            "--avg-cost",
            format(avg_cost, "f"),
            "--last-price",
            format(last_price, "f"),
            "--journal-path",
            str(journal),
            "--now",
            timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        ]
        for allowed_symbol in allowed_symbols:
            command.extend(("--allow-symbol", allowed_symbol))
        return cls(
            command=command,
            cwd=root,
            timeout_seconds=timeout_seconds,
        )

    def capture_snapshot(self) -> PortfolioSnapshot:
        response = self._request({"operation": "CAPTURE"})
        if set(response) != {"ok", "snapshot"}:
            raise ValueError("Athena CAPTURE response fields mismatch")
        return PortfolioSnapshot.model_validate_json(
            _contract_json(response["snapshot"])
        )

    def execute(
        self,
        mandate: ExecutionMandate,
        snapshot: PortfolioSnapshot,
    ) -> CanaryExecutionObservation:
        if not isinstance(mandate, ExecutionMandate):
            raise TypeError("a canonical ExecutionMandate is required")
        if not isinstance(snapshot, PortfolioSnapshot):
            raise TypeError("a canonical PortfolioSnapshot is required")
        response = self._request(
            {
                "operation": "EXECUTE",
                "mandate": _wire(mandate),
                "snapshot": _wire(snapshot),
            }
        )
        return self._observation(response, mandate=mandate)

    def reconcile(self, mandate_id: str) -> CanaryExecutionObservation:
        """Explicit reconciliation only; callers must never invoke it as retry."""

        if not isinstance(mandate_id, str) or not mandate_id.strip():
            raise ValueError("mandate_id is required")
        response = self._request(
            {"operation": "RECONCILE", "mandate_id": mandate_id}
        )
        return self._observation(response, mandate=None)

    def close(self) -> None:
        process = self._process
        if process.poll() is not None:
            return
        try:
            self._request({"operation": "CLOSE"})
        except Exception:
            process.terminate()
        finally:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def __enter__(self) -> "LocalAthenaCanaryTransport":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def _request(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if process.poll() is not None:
                raise RuntimeError(self._process_error("Athena canary exited"))
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("Athena canary pipes are unavailable")
            process.stdin.write(_contract_json(payload) + "\n")
            process.stdin.flush()
            line = self._readline(process.stdout)
            if not line:
                raise RuntimeError(self._process_error("Athena canary returned EOF"))
            response = json.loads(line, object_pairs_hook=_without_duplicate_keys)
            if not isinstance(response, dict):
                raise ValueError("Athena canary response must be an object")
            if response.get("ok") is not True:
                reason = response.get("reason") or "ATHENA_CANARY_REJECTED"
                raise RuntimeError(str(reason))
            return response

    def _readline(self, stream: TextIO) -> str:
        result: queue.Queue[object] = queue.Queue(maxsize=1)

        def read() -> None:
            try:
                result.put(stream.readline())
            except BaseException as error:
                result.put(error)

        threading.Thread(target=read, daemon=True).start()
        try:
            value = result.get(timeout=self._timeout_seconds)
        except queue.Empty as error:
            self._process.terminate()
            raise TimeoutError("Athena canary response timed out") from error
        if isinstance(value, BaseException):
            raise RuntimeError("Athena canary response failed") from value
        return str(value)

    def _observation(
        self,
        response: Mapping[str, Any],
        *,
        mandate: ExecutionMandate | None,
    ) -> CanaryExecutionObservation:
        expected = {"ok", "result", "snapshot", "submitted_quantities"}
        if set(response) != expected:
            raise ValueError("Athena EXECUTE response fields mismatch")
        result = ExecutionResult.model_validate_json(
            _contract_json(response["result"])
        )
        snapshot = PortfolioSnapshot.model_validate_json(
            _contract_json(response["snapshot"])
        )
        quantities = response["submitted_quantities"]
        if (
            not isinstance(quantities, list)
            or any(not isinstance(item, int) or isinstance(item, bool) for item in quantities)
        ):
            raise ValueError("Athena submission diagnostics are invalid")
        if mandate is not None:
            if result.mandate_id != mandate.mandate_id:
                raise ValueError("Athena result mandate lineage mismatch")
            if result.mandate_hash != mandate.content_hash:
                raise ValueError("Athena result mandate hash mismatch")
            if result.decision_id != mandate.decision_id:
                raise ValueError("Athena result decision lineage mismatch")
            if result.submitted_quantity not in (0, mandate.quantity):
                raise ValueError("Athena changed the Brain quantity")
        if (
            result.portfolio_snapshot_after_id != snapshot.snapshot_id
            or result.portfolio_snapshot_after_hash != snapshot.content_hash
        ):
            raise ValueError("Athena result does not bind its observed snapshot")
        return CanaryExecutionObservation(result, snapshot, tuple(quantities))

    def _process_error(self, prefix: str) -> str:
        stderr = ""
        if self._process.stderr is not None and self._process.poll() is not None:
            stderr = self._process.stderr.read().strip()
        return f"{prefix}: {stderr}" if stderr else prefix
