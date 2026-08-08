"""P1B orchestration outside DSA Research and Decision internals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Callable

from src.analyzer import AnalysisResult
from src.investment.contracts.execution_mandate import ExecutionMandate
from src.investment.contracts.execution_result import ExecutionResult
from src.investment.contracts.investment_decision import InvestmentDecision
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.contracts.research_bundle import ResearchBundle
from src.investment.contracts.risk_policy import RiskPolicy
from src.investment.execution_projection.decision_signal import DecisionSignalProjector
from src.investment.execution_projection.mandate import ExecutionMandateProjector
from src.investment.integration.canary_transport import AthenaCanaryTransport
from src.investment.shadow_wiring import InvestmentShadowWiringService


@dataclass(frozen=True)
class InvestmentCanaryArtifacts:
    """One immutable canary lineage; HOLD has no mandate or execution result."""

    source_report_id: int
    research_bundle: ResearchBundle
    portfolio_snapshot_a: PortfolioSnapshot
    risk_policy: RiskPolicy
    investment_decision: InvestmentDecision
    decision_signal: Mapping[str, Any]
    execution_mandate: ExecutionMandate | None
    execution_result: ExecutionResult | None
    portfolio_snapshot_b: PortfolioSnapshot | None
    submitted_quantities: tuple[int, ...]


class InvestmentCanaryService:
    """Run one exact simulation mandate or return a non-actionable HOLD."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._decision_wiring = InvestmentShadowWiringService(clock=clock)

    def run_from_analysis(
        self,
        *,
        result: AnalysisResult,
        context_snapshot: Mapping[str, Any],
        source_report_id: int,
        trace_id: str,
        trigger_source: str,
        risk_policy: RiskPolicy,
        transport: AthenaCanaryTransport,
        account_id: str,
        allowed_symbols: frozenset[str],
    ) -> InvestmentCanaryArtifacts:
        symbol = str(result.code or "").strip()
        if not allowed_symbols or symbol not in allowed_symbols:
            raise ValueError("symbol is not in the P1 simulation canary allowlist")
        if not account_id.strip():
            raise ValueError("P1 simulation canary account_id is required")
        snapshot_a = transport.capture_snapshot()
        if snapshot_a.account_id != account_id:
            raise ValueError("Athena snapshot account does not match the canary account")
        if snapshot_a.account_mode != "SIMULATION" or snapshot_a.simulation_only is not True:
            raise ValueError("P1 canary requires authoritative simulation account truth")

        decision_artifacts = self._decision_wiring.build_from_analysis(
            result=result,
            context_snapshot=context_snapshot,
            source_report_id=source_report_id,
            trace_id=trace_id,
            trigger_source=trigger_source,
            portfolio_snapshot=snapshot_a,
            risk_policy=risk_policy,
        )
        decision = decision_artifacts.investment_decision
        signal = DecisionSignalProjector.project(decision)
        metadata = dict(signal.get("metadata") or {})
        metadata.update(
            {
                "p1_simulation_canary": True,
                "execution_permitted": decision.action in {"BUY", "ADD"},
                "source_report_id": source_report_id,
            }
        )
        signal.update(
            {
                "p1_simulation_canary": True,
                "execution_permitted": decision.action in {"BUY", "ADD"},
                "metadata": metadata,
            }
        )

        if decision.action == "HOLD":
            return InvestmentCanaryArtifacts(
                source_report_id=source_report_id,
                research_bundle=decision_artifacts.research_bundle,
                portfolio_snapshot_a=snapshot_a,
                risk_policy=risk_policy,
                investment_decision=decision,
                decision_signal=self._freeze(signal),
                execution_mandate=None,
                execution_result=None,
                portfolio_snapshot_b=None,
                submitted_quantities=(),
            )

        mandate = ExecutionMandateProjector.project(decision)
        observation = transport.execute(mandate, snapshot_a)
        execution_result = observation.execution_result
        snapshot_b = observation.portfolio_snapshot
        self._validate_execution(
            decision=decision,
            mandate=mandate,
            result=execution_result,
            snapshot_a=snapshot_a,
            snapshot_b=snapshot_b,
            submitted_quantities=observation.submitted_quantities,
        )
        return InvestmentCanaryArtifacts(
            source_report_id=source_report_id,
            research_bundle=decision_artifacts.research_bundle,
            portfolio_snapshot_a=snapshot_a,
            risk_policy=risk_policy,
            investment_decision=decision,
            decision_signal=self._freeze(signal),
            execution_mandate=mandate,
            execution_result=execution_result,
            portfolio_snapshot_b=snapshot_b,
            submitted_quantities=observation.submitted_quantities,
        )

    @staticmethod
    def _validate_execution(
        *,
        decision: InvestmentDecision,
        mandate: ExecutionMandate,
        result: ExecutionResult,
        snapshot_a: PortfolioSnapshot,
        snapshot_b: PortfolioSnapshot,
        submitted_quantities: tuple[int, ...],
    ) -> None:
        mandate.assert_matches_decision(decision)
        if result.decision_id != decision.decision_id:
            raise ValueError("execution result decision lineage mismatch")
        if result.decision_hash != decision.content_hash:
            raise ValueError("execution result decision hash mismatch")
        if result.mandate_id != mandate.mandate_id:
            raise ValueError("execution result mandate lineage mismatch")
        if result.submitted_quantity not in (0, decision.delta_quantity):
            raise ValueError("Athena changed the Brain quantity")
        if any(quantity != decision.delta_quantity for quantity in submitted_quantities):
            raise ValueError("Athena broker diagnostics contain a resized quantity")
        if snapshot_b.account_id != snapshot_a.account_id:
            raise ValueError("post-execution snapshot account mismatch")
        if not (snapshot_b.authoritative and snapshot_b.read_only and snapshot_b.simulation_only):
            raise ValueError("post-execution snapshot is not authoritative simulation truth")
        position_a = snapshot_a.position_for(symbol=decision.symbol, market=decision.market)
        position_b = snapshot_b.position_for(symbol=decision.symbol, market=decision.market)
        quantity_a = 0 if position_a is None else position_a.quantity
        quantity_b = 0 if position_b is None else position_b.quantity
        if quantity_b != quantity_a + result.filled_quantity:
            raise ValueError("observed Snapshot B does not match the reported fill")

    @staticmethod
    def _freeze(value: Any) -> Any:
        if isinstance(value, Mapping):
            return MappingProxyType(
                {
                    key: InvestmentCanaryService._freeze(item)
                    for key, item in value.items()
                }
            )
        if isinstance(value, list):
            return tuple(InvestmentCanaryService._freeze(item) for item in value)
        if isinstance(value, tuple):
            return tuple(InvestmentCanaryService._freeze(item) for item in value)
        return value
