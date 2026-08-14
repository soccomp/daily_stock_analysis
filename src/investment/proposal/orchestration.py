"""Recurring DSA analysis-to-proposal handoff with no portfolio authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from src.config import Config
from src.investment.m2.identity import analysis_query_id, cycle_id as build_cycle_id, cycle_slot
from src.investment.m2.orchestration import DSAAnalysisCompletionRunner
from src.investment.proposal.builder import InvestmentProposalBuilder
from src.investment.proposal.transport import CanonicalHttpInvestmentProposalPublisher
from src.storage import DatabaseManager


class ProposalHandoffBlocked(RuntimeError):
    """Required DSA proposal handoff input is absent or unsafe."""


@dataclass(frozen=True)
class ProposalHandoffRunResult:
    cycle_id: str | None
    status: str
    proposal_ids: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()


class ProposalHandoffLoopService:
    """Run the real analysis path and stop at canonical proposal publication."""

    def __init__(
        self,
        *,
        config: Config,
        analysis_runner: DSAAnalysisCompletionRunner,
        publisher: CanonicalHttpInvestmentProposalPublisher,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._analysis_runner = analysis_runner
        self._publisher = publisher
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_config(cls, config: Config) -> "ProposalHandoffLoopService":
        mode = str(getattr(config, "single_brain_execution_mode", "SHADOW") or "SHADOW").strip().upper()
        if mode != "PROPOSAL_HANDOFF":
            raise ProposalHandoffBlocked("Issue #9 proposal handoff mode is not enabled")
        if bool(getattr(config, "single_brain_simulation_execution_authorized", False)):
            raise ProposalHandoffBlocked("DSA execution authorization must remain OFF")
        url = str(getattr(config, "single_brain_proposal_url", "") or "").strip()
        symbols = cls._symbols(config)
        if not url or not symbols:
            raise ProposalHandoffBlocked("proposal endpoint and DSA symbol scope are required")
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
        blocked: list[str] = []
        for symbol in self._symbols(self._config):
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
                if acknowledgement.get("status") not in {"NO_ACTION", "ALLOCATED", "BLOCKED"}:
                    raise ProposalHandoffBlocked("Athena proposal state is invalid")
                proposal_ids.append(artifacts.proposal.proposal_id)
            except Exception as exc:
                blocked.append(f"{symbol}: {type(exc).__name__}: {exc}")
        status = "COMPLETED" if proposal_ids and not blocked else "PARTIAL" if proposal_ids else "FAILED_CLOSED"
        return ProposalHandoffRunResult(cycle, status, tuple(proposal_ids), tuple(blocked))

    @staticmethod
    def _symbols(config: Config) -> tuple[str, ...]:
        values = getattr(config, "single_brain_proposal_symbols", ()) or ()
        result = tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        if any(len(symbol) != 6 or not symbol.isdigit() for symbol in result):
            raise ProposalHandoffBlocked("DSA proposal symbols must be six digits")
        return result
