"""Persistent, observational P1 Single Decision Scorecard."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, TYPE_CHECKING

from src.investment.contracts.base import canonical_json_bytes, canonicalize
from src.investment.contracts.execution_mandate import ExecutionMandate
from src.investment.contracts.execution_result import ExecutionResult
from src.investment.contracts.investment_decision import InvestmentDecision
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.contracts.research_bundle import ResearchBundle
from src.investment.contracts.risk_policy import RiskPolicy

if TYPE_CHECKING:
    from src.investment.canary import InvestmentCanaryArtifacts
    from src.investment.shadow_wiring import InvestmentShadowArtifacts


SCORECARD_SCHEMA_VERSION = "p1-scorecard-v1"
SHADOW_SCORECARD_MODE = "M2_SHADOW"
SHADOW_EXECUTION_AUTHORIZATION = "OFF"
SHADOW_EXECUTION_STATE = "NOT_AUTHORIZED"


def _without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate scorecard JSON key: {key}")
        payload[key] = value
    return payload


def _contract_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class SingleDecisionScorecard:
    """One read-only lineage. It owns no decision or execution methods."""

    scorecard_hash: str
    created_at: datetime
    source_report_id: int
    research_bundle: ResearchBundle
    portfolio_snapshot_a: PortfolioSnapshot
    risk_policy: RiskPolicy
    investment_decision: InvestmentDecision
    decision_signal: Mapping[str, Any]
    execution_mandate: ExecutionMandate | None
    execution_results: tuple[ExecutionResult, ...]
    portfolio_snapshot_b: PortfolioSnapshot | None
    execution_diagnostics: Mapping[str, Any]

    @property
    def decision_id(self) -> str:
        return self.investment_decision.decision_id

    @classmethod
    def from_canary(
        cls,
        artifacts: "InvestmentCanaryArtifacts",
    ) -> "SingleDecisionScorecard":
        result = artifacts.execution_result
        diagnostics = {
            "requested_quantity": None if result is None else result.requested_quantity,
            "submitted_quantity": None if result is None else result.submitted_quantity,
            "filled_quantity": None if result is None else result.filled_quantity,
            "remaining_quantity": None if result is None else result.remaining_quantity,
            "average_fill_price": None if result is None else result.average_fill_price,
            "fees": None if result is None else result.fees,
            "slippage_bps": None if result is None else result.slippage_bps,
            "execution_state": None if result is None else result.status,
            "reconciliation_state": (
                None if result is None else result.reconciliation_status
            ),
        }
        draft = cls(
            scorecard_hash="0" * 64,
            created_at=artifacts.investment_decision.created_at,
            source_report_id=artifacts.source_report_id,
            research_bundle=artifacts.research_bundle,
            portfolio_snapshot_a=artifacts.portfolio_snapshot_a,
            risk_policy=artifacts.risk_policy,
            investment_decision=artifacts.investment_decision,
            decision_signal=_freeze(canonicalize(artifacts.decision_signal)),
            execution_mandate=artifacts.execution_mandate,
            execution_results=(() if result is None else (result,)),
            portfolio_snapshot_b=artifacts.portfolio_snapshot_b,
            execution_diagnostics=_freeze(diagnostics),
        )
        draft._validate_lineage()
        return cls(
            **{
                **draft.__dict__,
                "scorecard_hash": hashlib.sha256(
                    canonical_json_bytes(draft._body())
                ).hexdigest(),
            }
        )

    @classmethod
    def from_shadow(
        cls,
        artifacts: "InvestmentShadowArtifacts",
    ) -> "SingleDecisionScorecard":
        """Capture a non-executable shadow lineage in the existing scorecard."""

        if (
            artifacts.shadow_only is not True
            or artifacts.execution_permitted is not False
            or artifacts.shadow_mandate is not None
        ):
            raise ValueError("shadow scorecard artifacts must be non-executable")

        snapshot = artifacts.portfolio_snapshot_a
        decision = artifacts.investment_decision
        diagnostics = {
            "mode": SHADOW_SCORECARD_MODE,
            "execution_authorization": SHADOW_EXECUTION_AUTHORIZATION,
            "execution_state": SHADOW_EXECUTION_STATE,
            "requested_quantity": None,
            "submitted_quantity": None,
            "filled_quantity": None,
            "remaining_quantity": None,
            "average_fill_price": None,
            "fees": None,
            "slippage_bps": None,
            "reconciliation_state": "NOT_APPLICABLE",
            "snapshot_freshness": {
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_hash": snapshot.content_hash,
                "as_of": snapshot.as_of,
                "validated_at": decision.created_at,
                "reconciliation_status": snapshot.reconciliation_status,
                "source": snapshot.source,
                "authoritative": snapshot.authoritative,
                "read_only": snapshot.read_only,
            },
        }
        draft = cls(
            scorecard_hash="0" * 64,
            created_at=decision.created_at,
            source_report_id=artifacts.source_report_id,
            research_bundle=artifacts.research_bundle,
            portfolio_snapshot_a=snapshot,
            risk_policy=artifacts.risk_policy,
            investment_decision=decision,
            decision_signal=_freeze(canonicalize(artifacts.decision_signal)),
            execution_mandate=None,
            execution_results=(),
            portfolio_snapshot_b=None,
            execution_diagnostics=_freeze(canonicalize(diagnostics)),
        )
        draft._validate_lineage()
        return cls(
            **{
                **draft.__dict__,
                "scorecard_hash": hashlib.sha256(
                    canonical_json_bytes(draft._body())
                ).hexdigest(),
            }
        )

    @classmethod
    def from_json(cls, value: str) -> "SingleDecisionScorecard":
        payload = json.loads(value, object_pairs_hook=_without_duplicate_keys)
        expected = {
            "schema_version",
            "scorecard_hash",
            "created_at",
            "source_report_id",
            "research_bundle",
            "portfolio_snapshot_a",
            "risk_policy",
            "investment_decision",
            "decision_signal",
            "execution_mandate",
            "execution_results",
            "portfolio_snapshot_b",
            "execution_diagnostics",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("scorecard fields mismatch")
        created_at = datetime.fromisoformat(
            str(payload["created_at"]).replace("Z", "+00:00")
        )
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("scorecard created_at must include a timezone")
        mandate_payload = payload["execution_mandate"]
        snapshot_b_payload = payload["portfolio_snapshot_b"]
        scorecard = cls(
            scorecard_hash=payload["scorecard_hash"],
            created_at=created_at,
            source_report_id=payload["source_report_id"],
            research_bundle=ResearchBundle.model_validate_json(
                _contract_json(payload["research_bundle"])
            ),
            portfolio_snapshot_a=PortfolioSnapshot.model_validate_json(
                _contract_json(payload["portfolio_snapshot_a"])
            ),
            risk_policy=RiskPolicy.model_validate_json(
                _contract_json(payload["risk_policy"])
            ),
            investment_decision=InvestmentDecision.model_validate_json(
                _contract_json(payload["investment_decision"])
            ),
            decision_signal=_freeze(payload["decision_signal"]),
            execution_mandate=(
                None
                if mandate_payload is None
                else ExecutionMandate.model_validate_json(
                    _contract_json(mandate_payload)
                )
            ),
            execution_results=tuple(
                ExecutionResult.model_validate_json(_contract_json(item))
                for item in payload["execution_results"]
            ),
            portfolio_snapshot_b=(
                None
                if snapshot_b_payload is None
                else PortfolioSnapshot.model_validate_json(
                    _contract_json(snapshot_b_payload)
                )
            ),
            execution_diagnostics=_freeze(payload["execution_diagnostics"]),
        )
        if (
            not isinstance(scorecard.scorecard_hash, str)
            or len(scorecard.scorecard_hash) != 64
            or scorecard.scorecard_hash
            != hashlib.sha256(canonical_json_bytes(scorecard._body())).hexdigest()
        ):
            raise ValueError("scorecard hash mismatch")
        scorecard._validate_lineage()
        return scorecard

    def to_payload(self) -> dict[str, Any]:
        return canonicalize(
            {
                **self._body(),
                "scorecard_hash": self.scorecard_hash,
            }
        )

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_payload()).decode("utf-8")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCORECARD_SCHEMA_VERSION,
            "created_at": self.created_at,
            "source_report_id": self.source_report_id,
            "research_bundle": self.research_bundle,
            "portfolio_snapshot_a": self.portfolio_snapshot_a,
            "risk_policy": self.risk_policy,
            "investment_decision": self.investment_decision,
            "decision_signal": self.decision_signal,
            "execution_mandate": self.execution_mandate,
            "execution_results": self.execution_results,
            "portfolio_snapshot_b": self.portfolio_snapshot_b,
            "execution_diagnostics": self.execution_diagnostics,
        }

    def _validate_lineage(self) -> None:
        decision = self.investment_decision
        if self.source_report_id <= 0:
            raise ValueError("scorecard source_report_id must be positive")
        if decision.research_ids != (self.research_bundle.research_id,):
            raise ValueError("scorecard research lineage mismatch")
        if (
            decision.portfolio_snapshot_id != self.portfolio_snapshot_a.snapshot_id
            or decision.portfolio_snapshot_hash
            != self.portfolio_snapshot_a.content_hash
        ):
            raise ValueError("scorecard Snapshot A lineage mismatch")
        if (
            decision.risk_policy_id != self.risk_policy.policy_id
            or decision.risk_policy_version != self.risk_policy.policy_version
        ):
            raise ValueError("scorecard RiskPolicy lineage mismatch")
        metadata = self.decision_signal.get("metadata")
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("investment_decision_id") != decision.decision_id
            or metadata.get("investment_decision_hash") != decision.content_hash
        ):
            raise ValueError("scorecard DecisionSignal lineage mismatch")

        if self.execution_diagnostics.get("mode") == SHADOW_SCORECARD_MODE:
            self._validate_shadow_lineage()
            return

        actionable = decision.action in {"BUY", "ADD"}
        if actionable:
            if (
                self.execution_mandate is None
                or len(self.execution_results) != 1
                or self.portfolio_snapshot_b is None
            ):
                raise ValueError("actionable scorecard requires mandate, result, and Snapshot B")
            self.execution_mandate.assert_matches_decision(decision)
            result = self.execution_results[0]
            if (
                result.decision_id != decision.decision_id
                or result.decision_hash != decision.content_hash
                or result.mandate_id != self.execution_mandate.mandate_id
                or result.mandate_hash != self.execution_mandate.content_hash
            ):
                raise ValueError("scorecard execution lineage mismatch")
            if (
                result.portfolio_snapshot_after_id
                != self.portfolio_snapshot_b.snapshot_id
                or result.portfolio_snapshot_after_hash
                != self.portfolio_snapshot_b.content_hash
            ):
                raise ValueError("scorecard Snapshot B lineage mismatch")
        elif (
            self.execution_mandate is not None
            or self.execution_results
            or self.portfolio_snapshot_b is not None
        ):
            raise ValueError("HOLD scorecard cannot contain execution artifacts")

    def _validate_shadow_lineage(self) -> None:
        if (
            self.execution_diagnostics.get("execution_authorization")
            != SHADOW_EXECUTION_AUTHORIZATION
            or self.execution_diagnostics.get("execution_state")
            != SHADOW_EXECUTION_STATE
        ):
            raise ValueError("shadow scorecard execution authorization mismatch")
        if (
            self.execution_mandate is not None
            or self.execution_results
            or self.portfolio_snapshot_b is not None
        ):
            raise ValueError("shadow scorecard cannot contain execution artifacts")
        metadata = self.decision_signal.get("metadata")
        if (
            self.decision_signal.get("shadow_only") is not True
            or self.decision_signal.get("execution_permitted") is not False
            or not isinstance(metadata, Mapping)
            or metadata.get("shadow_only") is not True
            or metadata.get("execution_permitted") is not False
        ):
            raise ValueError("shadow scorecard DecisionSignal is executable")

        snapshot = self.portfolio_snapshot_a
        expected_freshness = canonicalize(
            {
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_hash": snapshot.content_hash,
                "as_of": snapshot.as_of,
                "validated_at": self.investment_decision.created_at,
                "reconciliation_status": snapshot.reconciliation_status,
                "source": snapshot.source,
                "authoritative": snapshot.authoritative,
                "read_only": snapshot.read_only,
            }
        )
        if self.execution_diagnostics.get("snapshot_freshness") != expected_freshness:
            raise ValueError("shadow scorecard snapshot freshness lineage mismatch")
