"""Recurring DSA analysis-to-proposal handoff with no portfolio authority."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from src.config import Config
from src.investment.canonical_cycle import (
    CANONICAL_CYCLE_TASK,
    CanonicalCycleRepository,
    canonical_terminal_for_result,
)
from src.investment.m2.identity import analysis_query_id, cycle_id as build_cycle_id, cycle_slot
from src.investment.m2.orchestration import DSAAnalysisCompletionRunner
from src.investment.m2.natural_admission import CycleBudget, build_cycle_budget
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
    candidate_count: int = 0
    failed_count: int = 0
    deferred_count: int = 0
    candidate_outcomes: tuple[dict[str, object], ...] = ()
    canonical_cycle: dict[str, object] | None = None


class _NoopCanonicalCycleRepository:
    """Keep legacy direct unit invocations free of scheduler ledger writes."""

    def start_cycle(self, **_kwargs):
        return None

    def set_stage(self, **_kwargs):
        return None

    def set_current_work(self, **_kwargs):
        return None

    def update_identity_and_counts(self, **_kwargs):
        return None

    def record_lock(self, **_kwargs):
        return None

    def finish_cycle(self, **_kwargs):
        return None

    def get_cycle(self, _cycle_id):
        return None


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
        started_at: datetime | None = None,
        market_review_context: Mapping[str, object] | None = None,
        lock_acquired_at: datetime | None = None,
        require_market_review_context: bool = False,
        scheduler_task_name: str = CANONICAL_CYCLE_TASK,
    ) -> ProposalHandoffRunResult:
        if not bool(getattr(self._config, "single_brain_m2_enabled", False)):
            return ProposalHandoffRunResult(None, "DISABLED")
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            return ProposalHandoffRunResult(
                None,
                "FAILED_CLOSED",
                blocked_reasons=("proposal clock must be timezone-aware",),
            )
        cycle_started_at = started_at or now
        if (
            not isinstance(cycle_started_at, datetime)
            or cycle_started_at.tzinfo is None
            or cycle_started_at.utcoffset() is None
        ):
            return ProposalHandoffRunResult(
                None,
                "FAILED_CLOSED",
                blocked_reasons=("canonical cycle start must be timezone-aware",),
            )
        interval = int(getattr(self._config, "single_brain_m2_interval_minutes", 60))
        actual_scheduled_for = scheduled_for or now
        slot = cycle_slot(actual_scheduled_for, interval_minutes=interval)
        cycle = build_cycle_id(account_id="dsa-proposal-authority", scheduled_for=slot)
        budget = build_cycle_budget(
            started_at=cycle_started_at,
            scheduled_for=actual_scheduled_for,
            config=self._config,
        )
        canonical_enabled = (
            lock_acquired_at is not None
            or market_review_context is not None
            or require_market_review_context
        )
        if not canonical_enabled:
            return self._run_cycle_body(
                scheduled_for=scheduled_for,
                market_review_context=market_review_context,
                now=now,
                slot=slot,
                cycle=cycle,
                interval=interval,
                canonical=_NoopCanonicalCycleRepository(),
                require_market_review_context=require_market_review_context,
                budget=budget,
            )
        canonical = CanonicalCycleRepository()
        canonical.start_cycle(
            cycle_id=cycle,
            scheduler_task_name=scheduler_task_name,
            scheduled_for=actual_scheduled_for,
            cycle_slot=slot,
            source_runtime_identity="DSA:ProposalHandoffLoopService",
            now=cycle_started_at,
        )
        canonical.update_identity_and_counts(
            cycle_id=cycle,
            cycle_deadline=budget.deadline,
            candidate_reserve_seconds=int(budget.candidate_reserve_seconds),
        )
        canonical.set_stage(
            cycle_id=cycle,
            stage="SCHEDULER",
            state="SUCCEEDED",
            object_id=cycle,
            reason_code="CYCLE_STARTED",
            at=cycle_started_at,
        )
        if lock_acquired_at is None:
            canonical.set_stage(
                cycle_id=cycle,
                stage="LOCK",
                state="NOT_ENTERED",
                reason_code="LOCK_OWNERSHIP_CALLER",
                reason_detail="direct service invocation did not own the global scheduler lock",
                at=now,
            )
        else:
            canonical.record_lock(cycle_id=cycle, acquired_at=lock_acquired_at)
            canonical.set_stage(
                cycle_id=cycle,
                stage="LOCK",
                state="SUCCEEDED",
                reason_code="GLOBAL_ANALYSIS_LOCK_ACQUIRED",
                at=lock_acquired_at,
            )
        try:
            result = self._run_cycle_body(
                scheduled_for=scheduled_for,
                market_review_context=market_review_context,
                now=now,
                slot=slot,
                cycle=cycle,
                interval=interval,
                canonical=canonical,
                require_market_review_context=require_market_review_context,
                budget=budget,
            )
        except Exception as exc:
            canonical.finish_cycle(
                cycle_id=cycle,
                status="FAILED",
                terminal_reason_code="UNEXPECTED_EXCEPTION",
                terminal_reason_detail=exc,
            )
            raise

        terminal_status, terminal_reason = canonical_terminal_for_result(
            result_status=result.status,
            blocked_reasons=result.blocked_reasons,
        )
        if result.deferred_count:
            terminal_status, terminal_reason = "PARTIAL", "CYCLE_BUDGET_EXHAUSTED"
        canonical.update_identity_and_counts(
            cycle_id=cycle,
            candidate_count=result.candidate_count,
            proposal_count=len(result.proposal_ids),
            ack_count=len(result.acknowledgements),
            no_action_count=(
                1
                if result.status == "NO_ACTION"
                else sum(
                    item.lifecycle_state == "NO_ACTION"
                    for item in result.acknowledgements
                )
            ),
            blocked_count=len(result.blocked_reasons),
            failed_count=result.failed_count,
            deferred_count=result.deferred_count,
            research_trigger_ids=result.research_trigger_ids,
            proposal_ids=result.proposal_ids,
            acknowledgement_ids=tuple(
                item.acknowledgement_id for item in result.acknowledgements
            ),
            candidate_outcomes=result.candidate_outcomes,
        )
        canonical.finish_cycle(
            cycle_id=cycle,
            status=terminal_status,
            terminal_reason_code=terminal_reason,
            terminal_reason_detail="; ".join(result.blocked_reasons),
        )
        return ProposalHandoffRunResult(
            **{
                **result.__dict__,
                "canonical_cycle": canonical.get_cycle(cycle),
            }
        )

    def _run_cycle_body(
        self,
        *,
        scheduled_for: datetime | None = None,
        market_review_context: Mapping[str, object] | None = None,
        now: datetime,
        slot: datetime,
        cycle: str,
        interval: int,
        canonical: CanonicalCycleRepository,
        require_market_review_context: bool,
        budget: CycleBudget,
    ) -> ProposalHandoffRunResult:
        linkage_repository = MarketReviewLinkageRepository()
        resolved_market_context = (
            dict(market_review_context)
            if market_review_context is not None
            else linkage_repository.latest_market_context(
                trade_date=now.astimezone(timezone.utc).date(),
                as_of=now,
            )
        )
        if market_review_context is not None:
            try:
                linkage_repository.validate_context(resolved_market_context or {})
            except (TypeError, ValueError) as exc:
                for stage in ("MARKET_REVIEW", "MARKET_CONTEXT"):
                    canonical.set_stage(
                        cycle_id=cycle,
                        stage=stage,
                        state="BLOCKED",
                        reason_code="MARKET_CONTEXT_INVALID",
                        reason_detail=exc,
                        at=now,
                    )
                for stage in (
                    "RESEARCH_TRIGGER",
                    "CANDIDATE_EVALUATION",
                    "RESEARCH_BUNDLE",
                    "INVESTMENT_PROPOSAL",
                    "ATHENA_HANDOFF_ACK",
                ):
                    canonical.set_stage(
                        cycle_id=cycle,
                        stage=stage,
                        state="NOT_ENTERED",
                        reason_code="UPSTREAM_STAGE_FAILED",
                        at=now,
                    )
                return ProposalHandoffRunResult(
                    cycle,
                    "FAILED_CLOSED",
                    blocked_reasons=(f"market review identity linkage failed: {exc}",),
                )
        if resolved_market_context is None:
            for stage in ("MARKET_REVIEW", "MARKET_CONTEXT"):
                canonical.set_stage(
                    cycle_id=cycle,
                    stage=stage,
                    state="NOT_ENTERED",
                    reason_code="NO_PERSISTED_MARKET_CONTEXT",
                    reason_detail="no causal MarketContext was available at the cycle cutoff",
                    at=now,
                )
            if require_market_review_context:
                for stage in (
                    "RESEARCH_TRIGGER",
                    "CANDIDATE_EVALUATION",
                    "RESEARCH_BUNDLE",
                    "INVESTMENT_PROPOSAL",
                    "ATHENA_HANDOFF_ACK",
                ):
                    canonical.set_stage(
                        cycle_id=cycle,
                        stage=stage,
                        state="NOT_ENTERED",
                        reason_code="MARKET_CONTEXT_REQUIRED",
                        at=now,
                    )
                return ProposalHandoffRunResult(
                    cycle,
                    "FAILED_CLOSED",
                    blocked_reasons=(
                        "market review context is required for canonical proposal handoff",
                    ),
                )
        else:
            from src.services.dependency_health import (
                evaluate_dsa_research_admission,
                get_dependency_health_store,
            )

            health_store = get_dependency_health_store()
            health_store.record_result(
                "dsa-market-context",
                category="MARKET_CONTEXT",
                role="PRIMARY",
                success=True,
                reachable=True,
                usable=True,
                records=1,
                data_timestamp=str(resolved_market_context.get("as_of") or now.isoformat()),
                max_age_seconds=max(60, interval * 60),
                metadata={"reference": resolved_market_context.get("context_id")},
            )
            if bool(getattr(self._config, "single_brain_m2_readiness_gate_enabled", False)):
                health_snapshot = health_store.snapshot()
                admission = evaluate_dsa_research_admission(health_snapshot)
                if not admission.get("can_attempt"):
                    for stage in (
                        "RESEARCH_TRIGGER", "CANDIDATE_EVALUATION", "RESEARCH_BUNDLE",
                        "INVESTMENT_PROPOSAL", "ATHENA_HANDOFF_ACK",
                    ):
                        canonical.set_stage(
                            cycle_id=cycle,
                            stage=stage,
                            state="NOT_ENTERED",
                            reason_code="DSA_RESEARCH_ADMISSION_BLOCKED",
                            reason_detail="; ".join(admission.get("blocked_reasons") or ()),
                            at=now,
                        )
                    return ProposalHandoffRunResult(
                        cycle,
                        "FAILED_CLOSED",
                        blocked_reasons=(
                            "DSA research admission blocked: "
                            + "; ".join(admission.get("blocked_reasons") or ("UNKNOWN",)),
                        ),
                    )
            canonical.update_identity_and_counts(
                cycle_id=cycle,
                market_review_id=str(resolved_market_context["market_review_id"]),
                market_context_id=str(resolved_market_context["context_id"]),
            )
            canonical.set_stage(
                cycle_id=cycle,
                stage="MARKET_REVIEW",
                state="SUCCEEDED",
                object_id=str(resolved_market_context["market_review_id"]),
                parent_ref=str(resolved_market_context["source_task_id"]),
                reason_code="EXPLICIT_CYCLE_CONTEXT",
                at=now,
            )
            canonical.set_stage(
                cycle_id=cycle,
                stage="MARKET_CONTEXT",
                state="SUCCEEDED",
                object_id=str(resolved_market_context["context_id"]),
                parent_ref=str(resolved_market_context["market_review_id"]),
                reason_code="EXPLICIT_CYCLE_CONTEXT",
                at=now,
            )
        proposal_ids: list[str] = []
        acknowledgements: list[AthenaProposalAcknowledgement] = []
        blocked: list[str] = []
        candidate_outcomes: list[dict[str, object]] = []
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
            canonical.set_stage(
                cycle_id=cycle,
                stage="CANDIDATE_EVALUATION",
                state="FAILED",
                reason_code="RESEARCH_SELECTION_FAILED",
                reason_detail=exc,
                at=now,
            )
            for stage in (
                "RESEARCH_TRIGGER",
                "RESEARCH_BUNDLE",
                "INVESTMENT_PROPOSAL",
                "ATHENA_HANDOFF_ACK",
            ):
                canonical.set_stage(
                    cycle_id=cycle,
                    stage=stage,
                    state="NOT_ENTERED",
                    reason_code="UPSTREAM_STAGE_FAILED",
                    at=now,
                )
            return ProposalHandoffRunResult(
                cycle,
                "FAILED_CLOSED",
                blocked_reasons=(f"authoritative research selection failed: {exc}",),
            )
        researched = tuple(f"{scope['symbol']}:{scope['source']}" for scope in scopes)
        trigger_ids = tuple(
            str((scope.get("research_trigger") or {}).get("research_trigger_id") or "").strip()
            for scope in scopes
        )
        trigger_ids = tuple(value for value in trigger_ids if value)
        canonical.set_stage(
            cycle_id=cycle,
            stage="CANDIDATE_EVALUATION",
            state="SUCCEEDED" if scopes else "NO_ACTION",
            reason_code="CANDIDATE_SELECTION_COMPLETE" if scopes else "NO_CANDIDATES",
            reason_detail=(
                None if scopes else "no candidate satisfied strategy-evidence threshold"
            ),
            at=now,
        )
        canonical.set_stage(
            cycle_id=cycle,
            stage="RESEARCH_TRIGGER",
            state=(
                "SUCCEEDED"
                if scopes and len(trigger_ids) == len(scopes)
                else "NO_ACTION"
                if not scopes
                else "PARTIAL"
            ),
            object_ids=trigger_ids,
            reason_code=(
                "TRIGGERS_LINKED"
                if scopes and len(trigger_ids) == len(scopes)
                else "NO_CANDIDATES"
                if not scopes
                else "TRIGGER_LINKAGE_PARTIAL"
            ),
            at=now,
        )
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
            for stage in ("RESEARCH_BUNDLE", "INVESTMENT_PROPOSAL", "ATHENA_HANDOFF_ACK"):
                canonical.set_stage(
                    cycle_id=cycle,
                    stage=stage,
                    state="NO_ACTION",
                    reason_code="NO_CANDIDATES",
                    reason_detail="durable NO_ACTION outcome recorded",
                    at=now,
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
                candidate_count=0,
            )
        research_trigger_ids: list[str] = []
        deferred_count = 0
        for scope in scopes:
            symbol = scope["symbol"]
            current_scope = f"{symbol}:{scope.get('source') or 'UNKNOWN'}"
            budget_observed_at = self._clock()
            if not budget.admits_candidate(budget_observed_at):
                deferred_count += 1
                trigger = scope.get("research_trigger")
                candidate_outcomes.append({
                    "symbol": symbol,
                    "source": scope.get("source"),
                    "status": "DEFERRED_BUDGET",
                    "reason": "insufficient remaining cycle budget for configured timeout contract",
                    "research_trigger_id": (trigger or {}).get("research_trigger_id"),
                    "remaining_seconds": int(budget.remaining_seconds(budget_observed_at)),
                    "required_seconds": int(budget.candidate_reserve_seconds),
                })
                if self._trigger_coordinator is not None and trigger:
                    self._trigger_coordinator.mark_deferred_budget(
                        trigger=trigger, now=budget_observed_at
                    )
                canonical.set_current_work(
                    cycle_id=cycle,
                    stage="CANDIDATE_EVALUATION",
                    symbol_or_scope=current_scope,
                    work_state="DEFERRED",
                    at=budget_observed_at,
                )
                continue
            canonical.set_current_work(
                cycle_id=cycle,
                stage="CANDIDATE_EVALUATION",
                symbol_or_scope=current_scope,
                work_state="RUNNING",
                at=datetime.now(timezone.utc),
            )
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
                candidate_outcomes.append(
                    {
                        "symbol": symbol,
                        "source": scope["source"],
                        "status": "SUCCEEDED",
                        "source_report_id": completion.source_report_id,
                        "research_id": artifacts.research_bundle.research_id,
                        "proposal_id": artifacts.proposal.proposal_id,
                        "acknowledgement_id": acknowledgement.acknowledgement_id,
                    }
                )
                canonical.set_current_work(
                    cycle_id=cycle,
                    stage="CANDIDATE_EVALUATION",
                    symbol_or_scope=current_scope,
                    work_state="SUCCEEDED",
                    at=datetime.now(timezone.utc),
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
                candidate_outcomes.append(
                    {
                        "symbol": symbol,
                        "source": scope.get("source"),
                        "status": "FAILED",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "research_trigger_id": (
                            scope.get("research_trigger") or {}
                        ).get("research_trigger_id"),
                    }
                )
                canonical.set_current_work(
                    cycle_id=cycle,
                    stage="CANDIDATE_EVALUATION",
                    symbol_or_scope=current_scope,
                    work_state="FAILED",
                    at=datetime.now(timezone.utc),
                )
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
        status = (
            "PARTIAL"
            if deferred_count
            else "COMPLETED"
            if proposal_ids and not blocked
            else "PARTIAL"
            if proposal_ids
            else "FAILED_CLOSED"
        )
        research_ids = tuple(
            str(item["research_id"])
            for item in candidate_outcomes
            if item.get("research_id")
        )
        canonical.set_stage(
            cycle_id=cycle,
            stage="RESEARCH_BUNDLE",
            state=(
                "SUCCEEDED"
                if len(research_ids) == len(scopes)
                else "PARTIAL"
                if research_ids
                else "PARTIAL" if deferred_count else "FAILED"
            ),
            object_ids=research_ids,
            reason_code=(
                "RESEARCH_BUNDLES_COMPLETE"
                if len(research_ids) == len(scopes)
                else "RESEARCH_BUNDLES_PARTIAL"
                if research_ids
                else "CYCLE_BUDGET_EXHAUSTED" if deferred_count else "ALL_CANDIDATES_FAILED"
            ),
            at=now,
        )
        canonical.set_stage(
            cycle_id=cycle,
            stage="INVESTMENT_PROPOSAL",
            state=(
                "SUCCEEDED"
                if len(proposal_ids) == len(scopes)
                else "PARTIAL"
                if proposal_ids
                else "PARTIAL" if deferred_count else "FAILED"
            ),
            object_ids=proposal_ids,
            reason_code=(
                "PROPOSALS_COMPLETE"
                if len(proposal_ids) == len(scopes)
                else "PROPOSALS_PARTIAL"
                if proposal_ids
                else "CYCLE_BUDGET_EXHAUSTED" if deferred_count else "ALL_CANDIDATES_FAILED"
            ),
            at=now,
        )
        canonical.set_stage(
            cycle_id=cycle,
            stage="ATHENA_HANDOFF_ACK",
            state=(
                "SUCCEEDED"
                if len(acknowledgements) == len(scopes)
                else "PARTIAL"
                if acknowledgements
                else "PARTIAL" if deferred_count else "FAILED"
            ),
            object_ids=tuple(item.acknowledgement_id for item in acknowledgements),
            reason_code=(
                "ACKS_COMPLETE"
                if len(acknowledgements) == len(scopes)
                else "ACKS_PARTIAL"
                if acknowledgements
                else "CYCLE_BUDGET_EXHAUSTED" if deferred_count else "ALL_CANDIDATES_FAILED"
            ),
            at=now,
        )
        return ProposalHandoffRunResult(
            cycle_id=cycle,
            status=status,
            proposal_ids=tuple(proposal_ids),
            acknowledgements=tuple(acknowledgements),
            blocked_reasons=tuple(blocked),
            researched_symbols=researched,
            research_trigger_ids=tuple(research_trigger_ids),
            market_review_linkage=linkage,
            candidate_count=len(scopes),
            failed_count=len(blocked),
            deferred_count=deferred_count,
            candidate_outcomes=tuple(candidate_outcomes),
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
