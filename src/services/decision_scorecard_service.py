"""Write-once and read-only service for P1 Single Decision Scorecards."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from src.investment.scorecard import SingleDecisionScorecard
from src.repositories.decision_scorecard_repo import DecisionScorecardRepository
from src.storage import DatabaseManager

if TYPE_CHECKING:
    from src.investment.canary import InvestmentCanaryArtifacts
    from src.investment.m3.orchestration import M3ExecutionArtifacts
    from src.investment.shadow_wiring import InvestmentShadowArtifacts


class DecisionScorecardNotFoundError(ValueError):
    """The requested decision_id has no persisted scorecard."""


class DecisionScorecardService:
    """Persist observed lineage once and expose read-only retrieval."""

    def __init__(
        self,
        *,
        repository: DecisionScorecardRepository | None = None,
        db_manager: Optional[DatabaseManager] = None,
    ) -> None:
        self.repository = repository or DecisionScorecardRepository(db_manager)

    def persist_canary(
        self,
        artifacts: "InvestmentCanaryArtifacts",
    ) -> dict:
        scorecard = SingleDecisionScorecard.from_canary(artifacts)
        payload_json = scorecard.to_json()
        created = self.repository.create_if_absent(
            decision_id=scorecard.decision_id,
            trace_id=scorecard.investment_decision.trace_id,
            account_id=scorecard.investment_decision.account_id,
            symbol=scorecard.investment_decision.symbol,
            action=scorecard.investment_decision.action,
            payload_hash=scorecard.scorecard_hash,
            payload_json=payload_json,
        ).created
        return {"item": scorecard.to_payload(), "created": created}

    def persist_shadow(
        self,
        artifacts: "InvestmentShadowArtifacts",
    ) -> dict:
        scorecard = SingleDecisionScorecard.from_shadow(artifacts)
        payload_json = scorecard.to_json()
        created = self.repository.create_if_absent(
            decision_id=scorecard.decision_id,
            trace_id=scorecard.investment_decision.trace_id,
            account_id=scorecard.investment_decision.account_id,
            symbol=scorecard.investment_decision.symbol,
            action=scorecard.investment_decision.action,
            payload_hash=scorecard.scorecard_hash,
            payload_json=payload_json,
        ).created
        return {"item": scorecard.to_payload(), "created": created}

    def persist_m3(self, artifacts: "M3ExecutionArtifacts") -> dict:
        scorecard = SingleDecisionScorecard.from_m3(artifacts)
        payload_json = scorecard.to_json()
        created = self.repository.create_if_absent(
            decision_id=scorecard.decision_id,
            trace_id=scorecard.investment_decision.trace_id,
            account_id=scorecard.investment_decision.account_id,
            symbol=scorecard.investment_decision.symbol,
            action=scorecard.investment_decision.action,
            payload_hash=scorecard.scorecard_hash,
            payload_json=payload_json,
        ).created
        return {"item": scorecard.to_payload(), "created": created}

    def get(self, decision_id: str) -> dict:
        if not isinstance(decision_id, str) or not decision_id.strip():
            raise ValueError("decision_id is required")
        row = self.repository.get(decision_id)
        if row is None:
            raise DecisionScorecardNotFoundError(
                f"Decision scorecard not found: {decision_id}"
            )
        scorecard = SingleDecisionScorecard.from_json(row.payload_json)
        if (
            scorecard.decision_id != row.decision_id
            or scorecard.scorecard_hash != row.payload_hash
        ):
            raise ValueError("persisted decision scorecard metadata mismatch")
        return {"item": scorecard.to_payload()}
