"""Write-once and read-only service for P1 Single Decision Scorecards."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Optional, TYPE_CHECKING

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

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        symbol: str | None = None,
        action: str | None = None,
        mode: str | None = None,
        source_report_id: int | None = None,
    ) -> dict:
        """List validated immutable scorecards without creating new state."""

        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")
        normalized_symbol = symbol.strip().upper() if symbol else None
        normalized_action = action.strip().upper() if action else None
        normalized_mode = mode.strip().upper() if mode else None
        rows = self.repository.list_ordered(
            symbol=normalized_symbol,
            action=normalized_action,
        )
        summaries: list[tuple[datetime, str, dict[str, Any]]] = []
        for row in rows:
            try:
                scorecard = SingleDecisionScorecard.from_json(row.payload_json)
                if (
                    scorecard.decision_id != row.decision_id
                    or scorecard.scorecard_hash != row.payload_hash
                ):
                    raise ValueError("persisted decision scorecard metadata mismatch")
            except Exception as exc:
                # Historical rows are immutable evidence.  A schema/version or
                # hash incompatibility must be visible to the operator, but it
                # must not make one bad row turn the whole read-only list into
                # HTTP 500 or be silently rewritten as current.
                summaries.append(
                    (row.created_at, row.decision_id, self._invalid_summary(row, exc))
                )
                continue
            if source_report_id is not None and scorecard.source_report_id != source_report_id:
                continue
            diagnostics = scorecard.execution_diagnostics
            scorecard_mode = diagnostics.get("mode")
            if normalized_mode is not None and scorecard_mode != normalized_mode:
                continue
            summaries.append(
                (scorecard.created_at, scorecard.decision_id, self._summary(scorecard))
            )

        summaries.sort(key=lambda item: (item[0], item[1]), reverse=True)
        total = len(summaries)
        start = (page - 1) * page_size
        return {
            "items": [item[2] for item in summaries[start : start + page_size]],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def _summary(scorecard: SingleDecisionScorecard) -> dict[str, Any]:
        decision = scorecard.investment_decision
        diagnostics = scorecard.execution_diagnostics
        latest_result = scorecard.execution_results[-1] if scorecard.execution_results else None

        def observed(name: str) -> Any:
            value = getattr(latest_result, name) if latest_result is not None else None
            return value if value is not None else diagnostics.get(name)

        return {
            "decision_id": decision.decision_id,
            "created_at": scorecard.to_payload()["created_at"],
            "source_report_id": scorecard.source_report_id,
            "account_id": decision.account_id,
            "symbol": decision.symbol,
            "market": decision.market,
            "action": decision.action,
            "current_quantity": decision.current_quantity,
            "target_quantity": decision.target_quantity,
            "delta_quantity": decision.delta_quantity,
            "confidence": str(decision.confidence),
            "rationale": decision.rationale,
            "mode": diagnostics.get("mode"),
            "execution_status": observed("execution_state") if latest_result is None else latest_result.status,
            "reconciliation_status": (
                observed("reconciliation_state")
                if latest_result is None
                else latest_result.reconciliation_status
            ),
            "requested_quantity": observed("requested_quantity"),
            "submitted_quantity": observed("submitted_quantity"),
            "filled_quantity": observed("filled_quantity"),
            "remaining_quantity": observed("remaining_quantity"),
            "average_fill_price": (
                None
                if observed("average_fill_price") is None
                else str(observed("average_fill_price"))
            ),
            "block_reason": None if latest_result is None else latest_result.block_reason,
            "broker_reason": None if latest_result is None else latest_result.broker_reason,
            "snapshot_b_available": scorecard.portfolio_snapshot_b is not None,
            "integrity_status": "VALID",
            "integrity_error": None,
        }

    @staticmethod
    def _invalid_summary(row: Any, error: Exception) -> dict[str, Any]:
        """Project an unverifiable immutable row without claiming validity."""
        message = str(error)[:240] or error.__class__.__name__
        try:
            payload = json.loads(row.payload_json)
        except Exception:
            payload = {}
        schema_version = payload.get("schema_version") if isinstance(payload, dict) else None
        status = (
            "LEGACY_UNVERIFIABLE"
            if schema_version != "p1-scorecard-v1"
            else "INTEGRITY_MISMATCH"
        )
        created_at = getattr(row, "created_at", None)
        return {
            "decision_id": row.decision_id,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
            "source_report_id": 0,
            "account_id": "UNKNOWN",
            "symbol": row.symbol,
            "market": "UNKNOWN",
            "action": row.action,
            "current_quantity": 0,
            "target_quantity": 0,
            "delta_quantity": 0,
            "confidence": "UNKNOWN",
            "rationale": "Historical scorecard requires compatibility review",
            "mode": None,
            "execution_status": None,
            "reconciliation_status": None,
            "requested_quantity": None,
            "submitted_quantity": None,
            "filled_quantity": None,
            "remaining_quantity": None,
            "average_fill_price": None,
            "block_reason": None,
            "broker_reason": None,
            "snapshot_b_available": False,
            "integrity_status": status,
            "integrity_error": message,
        }
