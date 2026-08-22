"""Recurring DSA analysis-to-proposal handoff with no portfolio authority."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from src.config import Config
from src.investment.m2.identity import analysis_query_id, cycle_id as build_cycle_id, cycle_slot
from src.investment.m2.orchestration import DSAAnalysisCompletionRunner
from src.investment.m2.screening_candidates import (
    DatabaseScreeningCandidateSource,
    ScreeningCandidateSource,
)
from src.investment.m2.research_trigger import ResearchTriggerCoordinator
from src.investment.contracts.candidate_provenance import CandidateProvenance
from src.investment.integration.runtime_snapshot_ingress import (
    CanonicalHttpPortfolioSnapshotSource,
    PortfolioSnapshotSource,
)
from src.investment.proposal.builder import InvestmentProposalBuilder
from src.investment.proposal.transport import (
    AthenaProposalAcknowledgement,
    CanonicalHttpInvestmentProposalPublisher,
)
from src.repositories.market_review_outcome_repo import MarketReviewOutcomeRepository
from src.repositories.market_review_linkage_repo import (
    MarketReviewLinkageConflictError,
    MarketReviewLinkageRepository,
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
    no_action_outcome: dict[str, object] | None = None
    research_trigger_ids: tuple[str, ...] = ()
    market_review_linkage: dict[str, object] | None = None


class ProposalHandoffLoopService:
    """Run the real analysis path and stop at canonical proposal publication."""

    def __init__(
        self,
        *,
        config: Config,
        analysis_runner: DSAAnalysisCompletionRunner,
        publisher: CanonicalHttpInvestmentProposalPublisher,
        snapshot_source: PortfolioSnapshotSource,
        screening_candidate_source: ScreeningCandidateSource | None = None,
        trigger_coordinator: ResearchTriggerCoordinator | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._analysis_runner = analysis_runner
        self._publisher = publisher
        self._snapshot_source = snapshot_source
        self._screening_candidate_source = screening_candidate_source
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._trigger_coordinator = trigger_coordinator

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
        screening_candidate_source = (
            DatabaseScreeningCandidateSource(db)
            if bool(getattr(config, "single_brain_m2_screening_enabled", False))
            else None
        )
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
            screening_candidate_source=screening_candidate_source,
            trigger_coordinator=ResearchTriggerCoordinator(
                db,
                screening_candidate_source=screening_candidate_source,
            ),
        )

    def run_cycle(
        self,
        *,
        scheduled_for: datetime | None = None,
        market_review_context: Mapping[str, object] | None = None,
    ) -> ProposalHandoffRunResult:
        if not bool(getattr(self._config, "single_brain_m2_enabled", False)):
            return ProposalHandoffRunResult(None, "DISABLED")
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            return ProposalHandoffRunResult(None, "FAILED_CLOSED", blocked_reasons=("proposal clock must be timezone-aware",))
        interval = int(getattr(self._config, "single_brain_m2_interval_minutes", 60))
        slot = cycle_slot(scheduled_for or now, interval_minutes=interval)
        cycle = build_cycle_id(account_id="dsa-proposal-authority", scheduled_for=slot)
        linkage_repository = MarketReviewLinkageRepository()
        resolved_market_context = (
            dict(market_review_context)
            if market_review_context is not None
            else linkage_repository.latest_market_context(
                trade_date=now.astimezone(timezone.utc).date()
            )
        )
        if market_review_context is not None:
            try:
                linkage_repository.validate_context(resolved_market_context or {})
            except (TypeError, ValueError) as exc:
                return ProposalHandoffRunResult(
                    cycle,
                    "FAILED_CLOSED",
                    blocked_reasons=(f"market review identity linkage failed: {exc}",),
                )
        proposal_ids: list[str] = []
        acknowledgements: list[AthenaProposalAcknowledgement] = []
        blocked: list[str] = []
        try:
            authoritative_snapshot = self._snapshot_source.capture_snapshot()
            screening_candidates = self._load_screening_candidates()
            if self._trigger_coordinator is None:
                from src.investment.m2.selection import select_m2_research_objects
                scopes = select_m2_research_objects(
                    config=self._config,
                    snapshot=authoritative_snapshot,
                    screening_candidates=screening_candidates,
                )
            else:
                scopes = self._trigger_coordinator.plan(
                    config=self._config,
                    snapshot=authoritative_snapshot,
                    screening_candidates=screening_candidates,
                    cycle_id=cycle,
                    now=now,
                )
        except Exception as exc:
            return ProposalHandoffRunResult(
                cycle,
                "FAILED_CLOSED",
                blocked_reasons=(f"authoritative research selection failed: {exc}",),
            )
        researched = tuple(f"{scope['symbol']}:{scope['source']}" for scope in scopes)
        if not scopes:
            no_action = MarketReviewOutcomeRepository().persist_no_action(
                source_task_id=cycle,
                trade_date=now.astimezone(timezone.utc).date(),
                reason="no candidate satisfied strategy-evidence threshold",
            )
            linkage = None
            if resolved_market_context is not None:
                try:
                    linkage = linkage_repository.persist_linkage(
                        market_review_context=resolved_market_context,
                        proposal_cycle_id=cycle,
                        candidate_count=0,
                        outcome_id=str(no_action["outcome_id"]),
                        linked_at=slot,
                    )
                except (TypeError, ValueError, MarketReviewLinkageConflictError) as exc:
                    return ProposalHandoffRunResult(
                        cycle,
                        "FAILED_CLOSED",
                        blocked_reasons=(f"market review identity linkage failed: {exc}",),
                        no_action_outcome=no_action,
                    )
            return ProposalHandoffRunResult(
                cycle,
                "NO_ACTION",
                blocked_reasons=(
                    "candidate_count=0; outcome=NO_ACTION; "
                    "reason=no candidate satisfied strategy-evidence threshold",
                ),
                no_action_outcome=no_action,
                market_review_linkage=linkage,
            )
        research_trigger_ids: list[str] = []
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
                candidate_provenance = _candidate_provenance(scope)
                artifacts = InvestmentProposalBuilder(clock=lambda: proposal_time).build(
                    result=completion.result,
                    context_snapshot=completion.context_snapshot,
                    source_report_id=completion.source_report_id,
                    cycle_id=cycle,
                    trigger_source="single_brain_proposal_handoff",
                    authoritative_snapshot=authoritative_snapshot,
                    candidate_provenance=candidate_provenance,
                    research_trigger=scope.get("research_trigger"),
                )
                acknowledgement = self._publisher.publish(artifacts.proposal)
                proposal_ids.append(artifacts.proposal.proposal_id)
                acknowledgements.append(acknowledgement)
                trigger_id = str(
                    (scope.get("research_trigger") or {}).get("research_trigger_id") or ""
                ).strip()
                if trigger_id:
                    research_trigger_ids.append(trigger_id)
                if self._trigger_coordinator is not None and scope.get("research_trigger"):
                    self._trigger_coordinator.mark_success(
                        trigger=scope["research_trigger"],
                        research_id=artifacts.research_bundle.research_id,
                        proposal_id=artifacts.proposal.proposal_id,
                        reviewed_at=proposal_time,
                        interval_minutes=interval,
                    )
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
                if self._trigger_coordinator is not None and scope.get("research_trigger"):
                    try:
                        self._trigger_coordinator.mark_failure(
                            trigger=scope["research_trigger"], now=now
                        )
                    except Exception:
                        logger.exception("PALLAS-004 trigger failure checkpoint failed")
        linkage = None
        if resolved_market_context is not None and proposal_ids and not blocked:
            try:
                linkage = linkage_repository.persist_linkage(
                    market_review_context=resolved_market_context,
                    proposal_cycle_id=cycle,
                    candidate_count=len(proposal_ids),
                    research_trigger_ids=tuple(research_trigger_ids),
                    proposal_ids=tuple(proposal_ids),
                    acknowledgement_ids=tuple(
                        item.acknowledgement_id for item in acknowledgements
                    ),
                    linked_at=slot,
                )
            except (TypeError, ValueError, MarketReviewLinkageConflictError) as exc:
                blocked.append(f"market review identity linkage failed: {exc}")
        status = "COMPLETED" if proposal_ids and not blocked else "PARTIAL" if proposal_ids else "FAILED_CLOSED"
        return ProposalHandoffRunResult(
            cycle_id=cycle,
            status=status,
            proposal_ids=tuple(proposal_ids),
            acknowledgements=tuple(acknowledgements),
            blocked_reasons=tuple(blocked),
            researched_symbols=researched,
            research_trigger_ids=tuple(research_trigger_ids),
            market_review_linkage=linkage,
        )

    def _load_screening_candidates(self) -> list[dict[str, object]]:
        if self._screening_candidate_source is None:
            return []
        max_candidates = min(
            50,
            max(1, int(getattr(self._config, "single_brain_m2_screening_max_candidates", 3))),
        )
        max_age_hours = max(
            1,
            int(getattr(self._config, "single_brain_m2_screening_max_age_hours", 72)),
        )
        try:
            candidates = self._screening_candidate_source.latest(
                max_candidates=max_candidates,
                max_age=timedelta(hours=max_age_hours),
            )
        except Exception as exc:  # screening is best-effort; holdings still run
            logger.warning(
                "Proposal handoff screening candidate source failed; "
                "falling back to holdings/allowlist: %s",
                exc,
            )
            return []
        return [candidate.as_scope() for candidate in candidates]


def _candidate_provenance(scope: dict[str, object]) -> CandidateProvenance:
    source = str(scope.get("source") or "").strip().upper()
    if source == "SCREENING":
        selected_at = datetime.fromisoformat(str(scope["selected_at"]))
        if selected_at.tzinfo is None or selected_at.utcoffset() is None:
            raise ProposalHandoffBlocked("screening candidate selected_at must be timezone-aware")
        return CandidateProvenance(
            candidate_source="SCREENING",
            screening_run_id=str(scope.get("screening_run_id") or ""),
            screening_strategy=str(scope.get("strategy") or ""),
            screening_rank=scope.get("rank"),
            screening_score=(
                None
                if scope.get("screening_score") is None
                else Decimal(str(scope["screening_score"]))
            ),
            screening_selected_at=selected_at,
        )
    if source in {"HOLDING", "BOTH"}:
        return CandidateProvenance(candidate_source="HOLDING")
    if source in {"ALLOWLIST", "MANUAL_SYMBOL_OVERRIDE"}:
        return CandidateProvenance(candidate_source="MANUAL_SYMBOL_OVERRIDE")
    if source in {"MATERIAL_EVENT", "DEFENSIVE_RISK"}:
        return CandidateProvenance(candidate_source="EXTERNAL_EVENT")
    raise ProposalHandoffBlocked(f"unsupported research candidate source: {source or 'missing'}")
