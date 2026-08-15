"""Recurring DSA analysis-to-proposal handoff with no portfolio authority."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from src.config import Config
from src.investment.m2.identity import analysis_query_id, cycle_id as build_cycle_id, cycle_slot
from src.investment.m2.orchestration import DSAAnalysisCompletionRunner
from src.investment.m2.selection import select_m2_research_objects
from src.investment.integration.runtime_snapshot_ingress import (
    CanonicalHttpPortfolioSnapshotSource,
    PortfolioSnapshotSource,
)
from src.investment.proposal.builder import InvestmentProposalBuilder
from src.investment.proposal.transport import (
    AthenaProposalAcknowledgement,
    CanonicalHttpInvestmentProposalPublisher,
)
from src.storage import DatabaseManager


logger = logging.getLogger(__name__)


class ProposalHandoffBlocked(RuntimeError):
    """Required DSA proposal handoff input is absent or unsafe."""


@dataclass(frozen=True)
class ProposalHandoffRunResult:
    cycle_id: str | None
    status: str
    proposal_ids: tuple[str, ...] = ()
    acknowledgements: tuple[AthenaProposalAcknowledgement, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    researched_symbols: tuple[str, ...] = ()


class ProposalHandoffLoopService:
    """Run the real analysis path and stop at canonical proposal publication."""

    def __init__(
        self,
        *,
        config: Config,
        analysis_runner: DSAAnalysisCompletionRunner,
        publisher: CanonicalHttpInvestmentProposalPublisher,
        snapshot_source: PortfolioSnapshotSource,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._analysis_runner = analysis_runner
        self._publisher = publisher
        self._snapshot_source = snapshot_source
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_config(cls, config: Config) -> "ProposalHandoffLoopService":
        mode = str(getattr(config, "single_brain_execution_mode", "SHADOW") or "SHADOW").strip().upper()
        if mode != "PROPOSAL_HANDOFF":
            raise ProposalHandoffBlocked("Issue #9 proposal handoff mode is not enabled")
        if bool(getattr(config, "single_brain_simulation_execution_authorized", False)):
            raise ProposalHandoffBlocked("DSA execution authorization must remain OFF")
        url = str(getattr(config, "single_brain_proposal_url", "") or "").strip()
        snapshot_url = str(getattr(config, "single_brain_m2_snapshot_url", "") or "").strip()
        if not url or not snapshot_url:
            raise ProposalHandoffBlocked(
                "proposal endpoint and authoritative Athena snapshot endpoint are required"
            )
        db = DatabaseManager.get_instance()
        return cls(
            config=config,
            analysis_runner=DSAAnalysisCompletionRunner(
                config=config,
                db_manager=db,
                query_source="single_brain_proposal_handoff",
            ),
            publisher=CanonicalHttpInvestmentProposalPublisher(
                url=url,
                timeout_seconds=float(getattr(config, "single_brain_proposal_timeout_seconds", 5.0)),
            ),
            snapshot_source=CanonicalHttpPortfolioSnapshotSource(
                url=snapshot_url,
                timeout_seconds=float(
                    getattr(config, "single_brain_m2_snapshot_timeout_seconds", 5.0)
                ),
            ),
        )

    def run_cycle(self, *, scheduled_for: datetime | None = None) -> ProposalHandoffRunResult:
        if not bool(getattr(self._config, "single_brain_m2_enabled", False)):
            return ProposalHandoffRunResult(None, "DISABLED")
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            return ProposalHandoffRunResult(None, "FAILED_CLOSED", blocked_reasons=("proposal clock must be timezone-aware",))
        interval = int(getattr(self._config, "single_brain_m2_interval_minutes", 60))
        slot = cycle_slot(scheduled_for or now, interval_minutes=interval)
        cycle = build_cycle_id(account_id="dsa-proposal-authority", scheduled_for=slot)
        proposal_ids: list[str] = []
        acknowledgements: list[AthenaProposalAcknowledgement] = []
        blocked: list[str] = []
        try:
            scopes = select_m2_research_objects(
                config=self._config,
                snapshot=self._snapshot_source.capture_snapshot(),
            )
        except Exception as exc:
            return ProposalHandoffRunResult(
                cycle,
                "FAILED_CLOSED",
                blocked_reasons=(f"authoritative research selection failed: {exc}",),
            )
        researched = tuple(f"{scope['symbol']}:{scope['source']}" for scope in scopes)
        if not scopes:
            return ProposalHandoffRunResult(
                cycle,
                "FAILED_CLOSED",
                blocked_reasons=("M2 research-object selector returned an empty scope",),
            )
        for scope in scopes:
            symbol = scope["symbol"]
            logger.info(
                "Issue #9 research object selected: symbol=%s source=%s",
                symbol,
                scope["source"],
            )
            query_id = analysis_query_id(cycle=cycle, symbol=symbol)
            try:
                completion = self._analysis_runner.complete(
                    cycle_id=cycle,
                    symbol=symbol,
                    query_id=query_id,
                    current_time=slot,
                )
                # The durable report completion time keeps recovery canonical
                # without making a long-running analysis expire at handoff.
                proposal_time = completion.completed_at or now
                artifacts = InvestmentProposalBuilder(clock=lambda: proposal_time).build(
                    result=completion.result,
                    context_snapshot=completion.context_snapshot,
                    source_report_id=completion.source_report_id,
                    cycle_id=cycle,
                    trigger_source="single_brain_proposal_handoff",
                )
                acknowledgement = self._publisher.publish(artifacts.proposal)
                proposal_ids.append(artifacts.proposal.proposal_id)
                acknowledgements.append(acknowledgement)
                logger.info(
                    "Issue #9 proposal accepted: proposal_id=%s acknowledgement_id=%s "
                    "acknowledgement_state=%s lifecycle_state=%s deduplicated=%s",
                    acknowledgement.proposal_id,
                    acknowledgement.acknowledgement_id,
                    acknowledgement.acknowledgement_state,
                    acknowledgement.lifecycle_state,
                    acknowledgement.deduplicated,
                )
            except Exception as exc:
                blocked.append(f"{symbol}: {type(exc).__name__}: {exc}")
        status = "COMPLETED" if proposal_ids and not blocked else "PARTIAL" if proposal_ids else "FAILED_CLOSED"
        return ProposalHandoffRunResult(
            cycle_id=cycle,
            status=status,
            proposal_ids=tuple(proposal_ids),
            acknowledgements=tuple(acknowledgements),
            blocked_reasons=tuple(blocked),
            researched_symbols=researched,
        )
