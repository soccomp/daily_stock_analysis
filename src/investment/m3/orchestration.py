"""Brain-owned M3 decision dispatch with durable no-retry recovery.

NON_CANONICAL / LEGACY / EXPERIMENTAL: this is the former DSA-direct-execution
bypass (DSA -> trading spine).  The canonical investment path is DSA proposal ->
Athena Investment Authority -> Athena execution.  Issue #9 retired M3 as a
production path; it is retained for audit/history only.  Do NOT treat it as the
production main line (see ``src.investment.m3.PATH_CLASSIFICATION``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from src.investment.contracts.execution_mandate import ExecutionMandate
from src.investment.contracts.execution_result import ExecutionResult
from src.investment.contracts.investment_decision import InvestmentDecision
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.contracts.research_bundle import ResearchBundle
from src.investment.contracts.risk_policy import RiskPolicy
from src.investment.execution_projection.decision_signal import DecisionSignalProjector
from src.investment.execution_projection.mandate import ExecutionMandateProjector
from src.investment.integration.execution_transport import (
    AthenaExecutionObservation,
    ExecutionTransportUncertain,
)
from src.investment.m2.repository import M2OperationalRepository
from src.investment.m3.repository import (
    M3DecisionLineage,
    M3ExecutionCheckpoint,
    M3ExecutionRepository,
)
from src.investment.shadow_wiring import InvestmentShadowArtifacts


class M3ExecutionBlocked(RuntimeError):
    """An execution-mode invariant is absent or contradictory."""


class ExecutionTransport(Protocol):
    def execute(
        self,
        mandate: ExecutionMandate,
        snapshot: PortfolioSnapshot,
    ) -> AthenaExecutionObservation: ...

    def reconcile(
        self,
        *,
        mandate: ExecutionMandate,
    ) -> AthenaExecutionObservation: ...


class M3ScorecardStore(Protocol):
    def persist_m3(self, artifacts: "M3ExecutionArtifacts") -> dict[str, Any]: ...


@dataclass(frozen=True)
class M3ExecutionArtifacts:
    source_report_id: int
    research_bundle: ResearchBundle
    portfolio_snapshot_a: PortfolioSnapshot
    risk_policy: RiskPolicy
    investment_decision: InvestmentDecision
    decision_signal: Mapping[str, Any]
    execution_mandate: ExecutionMandate | None
    execution_results: tuple[ExecutionResult, ...]
    portfolio_snapshot_b: PortfolioSnapshot | None


@dataclass(frozen=True)
class M3ProcessResult:
    status: str
    decision_id: str


@dataclass(frozen=True)
class M3RecoveryResult:
    pending_decision_ids: tuple[str, ...]
    completed_decision_ids: tuple[str, ...]


class M3SimulationExecutionCoordinator:
    """Submit once or reconcile; it never creates or changes a Brain decision."""

    def __init__(
        self,
        *,
        transport: ExecutionTransport,
        repository: M3ExecutionRepository,
        scorecard_store: M3ScorecardStore,
        m2_repository: M2OperationalRepository,
        allowed_symbols: frozenset[str],
    ) -> None:
        if not allowed_symbols:
            raise ValueError("M3 execution allowlist is required")
        self._transport = transport
        self._repository = repository
        self._scorecard_store = scorecard_store
        self._m2_repository = m2_repository
        self._allowed_symbols = allowed_symbols

    def process(self, artifacts: InvestmentShadowArtifacts) -> M3ProcessResult:
        decision = artifacts.investment_decision
        if decision.action not in {"BUY", "ADD", "HOLD"}:
            raise M3ExecutionBlocked("M3 permits BUY, ADD, or HOLD only")
        if decision.market != "CN":
            raise M3ExecutionBlocked("M3 permits canonical CN equities only")
        lineage = self._lineage(artifacts)
        if decision.action == "HOLD":
            self._scorecard_store.persist_m3(self._artifacts(lineage, None, (), None))
            self._mark_persisted(lineage)
            return M3ProcessResult("PERSISTED", decision.decision_id)
        if decision.symbol not in self._allowed_symbols:
            raise M3ExecutionBlocked("decision symbol is not in the M3 execution allowlist")
        mandate = ExecutionMandateProjector.project(decision)
        checkpoint = self._repository.prepare(lineage=lineage, mandate=mandate)
        if checkpoint.status == "COMPLETED":
            self._finalize(checkpoint)
            return M3ProcessResult("PERSISTED", decision.decision_id)
        if checkpoint.status == "PREPARED" and self._repository.claim_dispatch(
            decision.decision_id
        ):
            try:
                observation = self._transport.execute(
                    mandate,
                    lineage.portfolio_snapshot_a,
                )
            except Exception as exc:  # submission outcome may already be unknown
                self._repository.record_uncertain(
                    decision_id=decision.decision_id,
                    reason=str(exc),
                )
                return M3ProcessResult(
                    "PENDING_RECONCILIATION",
                    decision.decision_id,
                )
        else:
            try:
                observation = self._transport.reconcile(mandate=mandate)
            except Exception as exc:  # reconciliation remains the only safe next step
                self._repository.record_uncertain(
                    decision_id=decision.decision_id,
                    reason=str(exc),
                )
                return M3ProcessResult(
                    "PENDING_RECONCILIATION",
                    decision.decision_id,
                )
        self._validate_observation(checkpoint, observation)
        checkpoint = self._repository.record_observation(
            decision_id=decision.decision_id,
            result=observation.execution_result,
            snapshot_b=observation.portfolio_snapshot,
        )
        if checkpoint.status != "COMPLETED":
            return M3ProcessResult("PENDING_RECONCILIATION", decision.decision_id)
        self._finalize(checkpoint)
        return M3ProcessResult("PERSISTED", decision.decision_id)

    def recover_pending(self) -> M3RecoveryResult:
        pending: list[str] = []
        completed: list[str] = []
        completed_cycles: set[str] = set()
        for checkpoint in self._repository.pending():
            try:
                observation = self._transport.reconcile(mandate=checkpoint.mandate)
                self._validate_observation(checkpoint, observation)
                checkpoint = self._repository.record_observation(
                    decision_id=checkpoint.decision_id,
                    result=observation.execution_result,
                    snapshot_b=observation.portfolio_snapshot,
                )
            except (ExecutionTransportUncertain, ValueError) as exc:
                self._repository.record_uncertain(
                    decision_id=checkpoint.decision_id,
                    reason=str(exc),
                )
                pending.append(checkpoint.decision_id)
                continue
            if checkpoint.status == "COMPLETED":
                self._finalize(checkpoint)
                completed.append(checkpoint.decision_id)
                completed_cycles.add(checkpoint.cycle_id)
            else:
                pending.append(checkpoint.decision_id)
        remaining_cycles = {
            checkpoint.cycle_id for checkpoint in self._repository.pending()
        }
        for cycle_id in sorted(completed_cycles - remaining_cycles):
            self._m2_repository.close_cycle(cycle_id=cycle_id)
        return M3RecoveryResult(tuple(pending), tuple(completed))

    def _finalize(
        self,
        checkpoint: M3ExecutionCheckpoint,
    ) -> None:
        if checkpoint.portfolio_snapshot_b is None or not checkpoint.results:
            raise ValueError("completed M3 execution lacks factual result or Snapshot B")
        self._scorecard_store.persist_m3(
            self._artifacts(
                checkpoint.lineage,
                checkpoint.mandate,
                checkpoint.results,
                checkpoint.portfolio_snapshot_b,
            )
        )
        self._mark_persisted(checkpoint.lineage)

    def _mark_persisted(self, lineage: M3DecisionLineage) -> None:
        decision = lineage.investment_decision
        self._m2_repository.mark_symbol_persisted(
            cycle_id=decision.decision_cycle_id,
            symbol=decision.symbol,
            source_report_id=lineage.source_report_id,
            research_id=lineage.research_bundle.research_id,
            decision_id=decision.decision_id,
            decision_action=decision.action,
            rationale_summary=decision.rationale,
        )

    @staticmethod
    def _lineage(artifacts: InvestmentShadowArtifacts) -> M3DecisionLineage:
        decision = artifacts.investment_decision
        signal = DecisionSignalProjector.project(decision)
        metadata = dict(signal.get("metadata") or {})
        actionable = decision.action in {"BUY", "ADD"}
        metadata.update({
            "single_brain_m3": True,
            "shadow_only": False,
            "execution_permitted": actionable,
            "source_report_id": artifacts.source_report_id,
        })
        signal.update({
            "single_brain_m3": True,
            "shadow_only": False,
            "execution_permitted": actionable,
            "metadata": metadata,
        })
        return M3DecisionLineage(
            source_report_id=artifacts.source_report_id,
            research_bundle=artifacts.research_bundle,
            portfolio_snapshot_a=artifacts.portfolio_snapshot_a,
            risk_policy=artifacts.risk_policy,
            investment_decision=decision,
            decision_signal=signal,
        )

    @staticmethod
    def _artifacts(
        lineage: M3DecisionLineage,
        mandate: ExecutionMandate | None,
        results: tuple[ExecutionResult, ...],
        snapshot_b: PortfolioSnapshot | None,
    ) -> M3ExecutionArtifacts:
        return M3ExecutionArtifacts(
            source_report_id=lineage.source_report_id,
            research_bundle=lineage.research_bundle,
            portfolio_snapshot_a=lineage.portfolio_snapshot_a,
            risk_policy=lineage.risk_policy,
            investment_decision=lineage.investment_decision,
            decision_signal=lineage.decision_signal,
            execution_mandate=mandate,
            execution_results=results,
            portfolio_snapshot_b=snapshot_b,
        )

    @staticmethod
    def _validate_observation(
        checkpoint: M3ExecutionCheckpoint,
        observation: AthenaExecutionObservation,
    ) -> None:
        result = observation.execution_result
        snapshot = observation.portfolio_snapshot
        mandate = checkpoint.mandate
        if result.submitted_quantity not in {0, mandate.quantity}:
            raise ValueError("Athena changed the Brain quantity")
        if any(quantity != mandate.quantity for quantity in observation.submitted_quantities):
            raise ValueError("broker submitted a resized quantity")
        if (
            snapshot.account_id != mandate.account_id
            or snapshot.authoritative is not True
            or snapshot.read_only is not True
            or snapshot.simulation_only is not True
            or snapshot.source != "ATHENA_RUNTIME"
            or snapshot.account_mode != "SIMULATION"
        ):
            raise ValueError("Snapshot B authority is invalid")
