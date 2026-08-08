"""Explicit local RiskPolicy input for the M2 Brain loop."""

from __future__ import annotations

from pathlib import Path

from src.investment.contracts.risk_policy import RiskPolicy


class RiskPolicyLoadError(RuntimeError):
    """An explicit canonical policy was unavailable or invalid."""


class CanonicalRiskPolicyLoader:
    MAX_POLICY_BYTES = 1024 * 1024

    def __init__(self, path: str) -> None:
        raw = str(path or "").strip()
        if not raw:
            raise ValueError("M2 RiskPolicy path is required")
        self._path = Path(raw).expanduser()

    def load(self) -> RiskPolicy:
        try:
            if not self._path.is_file():
                raise RiskPolicyLoadError("explicit RiskPolicy file is unavailable")
            size = self._path.stat().st_size
            if size <= 0 or size > self.MAX_POLICY_BYTES:
                raise RiskPolicyLoadError("explicit RiskPolicy file has an invalid size")
            payload = self._path.read_bytes()
            return RiskPolicy.model_validate_json(payload)
        except RiskPolicyLoadError:
            raise
        except Exception as exc:
            raise RiskPolicyLoadError("explicit canonical RiskPolicy is invalid") from exc
