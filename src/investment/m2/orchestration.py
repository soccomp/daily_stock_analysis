"""Recurring zero-authority M2 shadow loop built on the real DSA analysis path."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from data_provider.base import canonical_stock_code, normalize_stock_code

from src.analyzer import AnalysisResult
from src.config import Config
from src.core.trading_calendar import get_market_for_stock
from src.enums import ReportType
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.contracts.risk_policy import RiskPolicy
from src.investment.integration.runtime_snapshot_ingress import (
    CanonicalHttpPortfolioSnapshotSource,
    PortfolioSnapshotSource,
)
from src.investment.m2.identity import (
    analysis_query_id,
    cycle_id as build_cycle_id,
    cycle_slot,
    decision_id as build_decision_id,
    input_hash as build_input_hash,
)
from src.investment.m2.policy import CanonicalRiskPolicyLoader
from src.investment.m2.repository import M2InputConflictError, M2OperationalRepository
from src.investment.shadow_wiring import InvestmentShadowWiringService, ShadowWiringRejected
from src.services.history_service import HistoryService
from src.storage import DatabaseManager
from src.utils.data_processing import parse_json_field


logger = logging.getLogger(__name__)


class M2ShadowBlocked(RuntimeError):
    """A mandatory authority input is absent, invalid, or unsafe."""


class RiskPolicySource(Protocol):
    def load(self) -> RiskPolicy: ...


class ShadowLineageStore(Protocol):
    def persist_shadow(self, artifacts: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AnalysisCompletion:
    result: AnalysisResult
    context_snapshot: Mapping[str, Any]
    source_report_id: int
    recovered: bool


@dataclass(frozen=True)
class M2ShadowRunResult:
    cycle_id: str | None
    status: str
    persisted_decision_ids: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    duplicate_trigger: bool = False


class DSAAnalysisCompletionRunner:
    """Run or recover one persisted result through DSA's real analysis lifecycle."""

    def __init__(
        self,
        *,
        config: Config,
        db_manager: DatabaseManager | None = None,
        pipeline_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._db = db_manager or DatabaseManager.get_instance()
        self._history = HistoryService(db_manager=self._db)
        self._pipeline_factory = pipeline_factory or self._default_pipeline_factory

    def complete(
        self,
        *,
        cycle_id: str,
        symbol: str,
        query_id: str,
        current_time: datetime,
    ) -> AnalysisCompletion:
        existing = self._db.get_analysis_history(
            code=symbol,
            query_id=query_id,
            limit=1,
        )
        if existing:
            return self._completion_from_record(existing[0], recovered=True)

        pipeline = self._pipeline_factory(
            config=self._config,
            max_workers=1,
            query_id=query_id,
            trace_id=cycle_id,
            query_source="single_brain_m2_shadow",
            save_context_snapshot=True,
            investment_runtime_paths_disabled=True,
        )
        result = pipeline.process_single_stock(
            symbol,
            skip_analysis=False,
            single_stock_notify=False,
            report_type=ReportType.SIMPLE,
            analysis_query_id=query_id,
            current_time=current_time,
        )
        if not isinstance(result, AnalysisResult) or not result.success:
            raise M2ShadowBlocked("real DSA analysis did not complete successfully")
        records = self._db.get_analysis_history(
            code=symbol,
            query_id=query_id,
            limit=1,
        )
        if not records:
            raise M2ShadowBlocked("real DSA analysis completion was not persisted")
        completion = self._completion_from_record(records[0], recovered=False)
        # Use the persisted reconstruction so restart and first-run semantics match.
        return completion

    def _completion_from_record(self, record: Any, *, recovered: bool) -> AnalysisCompletion:
        raw_result = parse_json_field(record.raw_result)
        if not isinstance(raw_result, dict):
            raise M2ShadowBlocked("persisted DSA analysis result is invalid")
        result = self._history._rebuild_analysis_result(raw_result, record)
        if not isinstance(result, AnalysisResult) or not result.success:
            raise M2ShadowBlocked("persisted DSA analysis result cannot be reconstructed")
        context = parse_json_field(record.context_snapshot)
        if not isinstance(context, dict):
            raise M2ShadowBlocked("persisted DSA analysis lacks a context snapshot")
        return AnalysisCompletion(
            result=result,
            context_snapshot=context,
            source_report_id=int(record.id),
            recovered=recovered,
        )

    @staticmethod
    def _default_pipeline_factory(**kwargs: Any) -> Any:
        from src.core.pipeline import StockAnalysisPipeline

        return StockAnalysisPipeline(**kwargs)


class M2ShadowLoopService:
    """One bounded scheduler attempt; every unsafe state fails closed."""

    MAX_SNAPSHOT_AGE = timedelta(minutes=5)

    def __init__(
        self,
        *,
        config: Config,
        snapshot_source: PortfolioSnapshotSource,
        policy_source: RiskPolicySource,
        analysis_runner: DSAAnalysisCompletionRunner,
        lineage_store: ShadowLineageStore,
        repository: M2OperationalRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._snapshot_source = snapshot_source
        self._policy_source = policy_source
        self._analysis_runner = analysis_runner
        self._lineage_store = lineage_store
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_config(cls, config: Config) -> "M2ShadowLoopService":
        if not getattr(config, "single_brain_m2_snapshot_url", None):
            raise M2ShadowBlocked("M2 authoritative snapshot URL is not configured")
        if not getattr(config, "single_brain_m2_risk_policy_path", None):
            raise M2ShadowBlocked("M2 explicit RiskPolicy path is not configured")
        from src.services.decision_scorecard_service import DecisionScorecardService

        db = DatabaseManager.get_instance()
        return cls(
            config=config,
            snapshot_source=CanonicalHttpPortfolioSnapshotSource(
                url=config.single_brain_m2_snapshot_url,
                timeout_seconds=config.single_brain_m2_snapshot_timeout_seconds,
            ),
            policy_source=CanonicalRiskPolicyLoader(config.single_brain_m2_risk_policy_path),
            analysis_runner=DSAAnalysisCompletionRunner(config=config, db_manager=db),
            lineage_store=DecisionScorecardService(db_manager=db),
            repository=M2OperationalRepository(db),
        )

    def run_cycle(self, *, scheduled_for: datetime | None = None) -> M2ShadowRunResult:
        if not bool(getattr(self._config, "single_brain_m2_enabled", False)):
            return M2ShadowRunResult(cycle_id=None, status="DISABLED")
        now = self._aware_now()
        account_id = str(getattr(self._config, "single_brain_m2_account_id", "") or "").strip()
        if not account_id:
            return M2ShadowRunResult(cycle_id=None, status="FAILED_CLOSED", blocked_reasons=("M2 account_id is required",))
        interval = int(getattr(self._config, "single_brain_m2_interval_minutes", 60))
        slot = cycle_slot(scheduled_for or now, interval_minutes=interval)
        cycle = build_cycle_id(account_id=account_id, scheduled_for=slot)
        try:
            claim = self._repository.claim_cycle(
                cycle_id=cycle,
                account_id=account_id,
                scheduled_for=slot,
            )
        except Exception as exc:
            return M2ShadowRunResult(cycle_id=cycle, status="FAILED_CLOSED", blocked_reasons=(str(exc),))
        duplicate = not claim.created
        if claim.status == "COMPLETED":
            return M2ShadowRunResult(
                cycle_id=cycle,
                status="DEDUPLICATED",
                duplicate_trigger=True,
            )

        try:
            mirror = self._repository.load_authority_mirror(cycle)
            if mirror is None:
                snapshot = self._snapshot_source.capture_snapshot()
                policy = self._policy_source.load()
                symbols = self._select_symbols(snapshot)
            else:
                snapshot = PortfolioSnapshot.model_validate_json(mirror.snapshot_json)
                policy = RiskPolicy.model_validate_json(mirror.risk_policy_json)
                current_policy = self._policy_source.load()
                if (
                    current_policy.policy_id != policy.policy_id
                    or current_policy.policy_version != policy.policy_version
                    or current_policy.content_hash != policy.content_hash
                    or current_policy.canonical_json() != policy.canonical_json()
                ):
                    raise M2InputConflictError(
                        "explicit RiskPolicy changed inside one decision cycle"
                    )
                symbols = [dict(item) for item in mirror.symbols]
            self._validate_authority_inputs(
                snapshot=snapshot,
                policy=policy,
                account_id=account_id,
                now=now,
            )
            if not symbols:
                raise M2ShadowBlocked("M2 symbol scope is empty after validation")
            authority_hash = build_input_hash(
                snapshot_hash=snapshot.content_hash,
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_hash=policy.content_hash,
            )
            if mirror is not None and mirror.input_hash != authority_hash:
                raise M2InputConflictError("persisted M2 authority mirror hash mismatch")
            self._repository.bind_authority_inputs(
                cycle_id=cycle,
                input_hash=authority_hash,
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.content_hash,
                snapshot_json=snapshot.canonical_json(),
                snapshot_as_of=snapshot.as_of,
                reconciliation_status=snapshot.reconciliation_status,
                risk_policy_id=policy.policy_id,
                risk_policy_version=policy.policy_version,
                risk_policy_hash=policy.content_hash,
                risk_policy_json=policy.canonical_json(),
                symbols=symbols,
            )
        except Exception as exc:
            self._repository.fail_cycle(cycle_id=cycle, reason=str(exc))
            return M2ShadowRunResult(
                cycle_id=cycle,
                status="FAILED_CLOSED",
                blocked_reasons=(str(exc),),
                duplicate_trigger=duplicate,
            )

        persisted: list[str] = []
        blocked: list[str] = []
        for scope in symbols:
            symbol = scope["symbol"]
            query_id = analysis_query_id(cycle=cycle, symbol=symbol)
            try:
                symbol_claim = self._repository.claim_symbol(
                    cycle_id=cycle,
                    symbol=symbol,
                    source_kind=scope["source"],
                    analysis_query_id=query_id,
                )
                if symbol_claim.status == "PERSISTED" and symbol_claim.decision_id:
                    persisted.append(symbol_claim.decision_id)
                    continue
                completion = self._analysis_runner.complete(
                    cycle_id=cycle,
                    symbol=symbol,
                    query_id=query_id,
                    current_time=slot,
                )
                self._repository.mark_symbol_analyzed(
                    cycle_id=cycle,
                    symbol=symbol,
                    source_report_id=completion.source_report_id,
                )
                decision_now = self._aware_now()
                self._validate_authority_inputs(
                    snapshot=snapshot,
                    policy=policy,
                    account_id=account_id,
                    now=decision_now,
                )
                stable_decision_id = build_decision_id(
                    cycle=cycle,
                    symbol=symbol,
                    source_report_id=completion.source_report_id,
                    snapshot_hash=snapshot.content_hash,
                    policy_hash=policy.content_hash,
                )
                artifacts = InvestmentShadowWiringService(clock=lambda: decision_now).build_from_analysis(
                    result=completion.result,
                    context_snapshot=completion.context_snapshot,
                    source_report_id=completion.source_report_id,
                    trace_id=cycle,
                    trigger_source="single_brain_m2_shadow",
                    portfolio_snapshot=snapshot,
                    risk_policy=policy,
                    decision_cycle_id=cycle,
                    decision_id=stable_decision_id,
                    allow_nonpositive_return=True,
                )
                self._lineage_store.persist_shadow(artifacts)
                decision = artifacts.investment_decision
                self._repository.mark_symbol_persisted(
                    cycle_id=cycle,
                    symbol=symbol,
                    source_report_id=completion.source_report_id,
                    research_id=artifacts.research_bundle.research_id,
                    decision_id=decision.decision_id,
                    decision_action=decision.action,
                    rationale_summary=decision.rationale,
                )
                persisted.append(decision.decision_id)
            except (M2ShadowBlocked, ShadowWiringRejected, M2InputConflictError) as exc:
                reason = f"{symbol}: {exc}"
                blocked.append(reason)
                self._repository.mark_symbol_failed(
                    cycle_id=cycle,
                    symbol=symbol,
                    status="BLOCKED",
                    reason=str(exc),
                )
            except Exception as exc:  # one bounded attempt; later trigger may recover
                reason = f"{symbol}: {type(exc).__name__}: {exc}"
                blocked.append(reason)
                self._repository.mark_symbol_failed(
                    cycle_id=cycle,
                    symbol=symbol,
                    status="FAILED",
                    reason=f"{type(exc).__name__}: {exc}",
                )
                logger.exception("M2 shadow symbol failed closed: cycle=%s symbol=%s", cycle, symbol)

        try:
            status = self._repository.close_cycle(cycle_id=cycle)
        except Exception as exc:
            reason = f"cycle closeout failed: {type(exc).__name__}: {exc}"
            try:
                self._repository.fail_cycle(cycle_id=cycle, reason=reason)
            except Exception:
                logger.exception(
                    "M2 shadow cycle failure checkpoint could not be persisted: cycle=%s",
                    cycle,
                )
            logger.exception("M2 shadow cycle closeout failed: cycle=%s", cycle)
            return M2ShadowRunResult(
                cycle_id=cycle,
                status="FAILED_CLOSED",
                persisted_decision_ids=tuple(persisted),
                blocked_reasons=(*blocked, reason),
                duplicate_trigger=duplicate,
            )
        return M2ShadowRunResult(
            cycle_id=cycle,
            status=status,
            persisted_decision_ids=tuple(persisted),
            blocked_reasons=tuple(blocked),
            duplicate_trigger=duplicate,
        )

    def _validate_authority_inputs(
        self,
        *,
        snapshot: PortfolioSnapshot,
        policy: RiskPolicy,
        account_id: str,
        now: datetime,
    ) -> None:
        if not isinstance(snapshot, PortfolioSnapshot):
            raise M2ShadowBlocked("canonical PortfolioSnapshot is required")
        if (
            snapshot.authoritative is not True
            or snapshot.read_only is not True
            or snapshot.source != "ATHENA_RUNTIME"
        ):
            raise M2ShadowBlocked("PortfolioSnapshot authority semantics are invalid")
        if snapshot.account_id != account_id:
            raise M2ShadowBlocked("authoritative PortfolioSnapshot account mismatch")
        if snapshot.account_mode != "SIMULATION" or snapshot.simulation_only is not True:
            raise M2ShadowBlocked("M2 requires an Athena simulation-only account")
        if snapshot.reconciliation_status != "RECONCILED":
            raise M2ShadowBlocked("authoritative PortfolioSnapshot is not reconciled")
        if snapshot.as_of > now:
            raise M2ShadowBlocked("authoritative PortfolioSnapshot is future-dated")
        if now - snapshot.as_of > self.MAX_SNAPSHOT_AGE:
            raise M2ShadowBlocked("authoritative PortfolioSnapshot is stale")
        if snapshot.data_quality not in {"HIGH", "MEDIUM"}:
            raise M2ShadowBlocked("authoritative PortfolioSnapshot data quality is insufficient")
        if not isinstance(policy, RiskPolicy):
            raise M2ShadowBlocked("explicit canonical RiskPolicy is required")
        if not policy.applies_to(account_id):
            raise M2ShadowBlocked("RiskPolicy does not apply to the M2 account")
        if not policy.is_effective_at(now):
            raise M2ShadowBlocked("RiskPolicy is not currently effective")
        quality_rank = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
        if quality_rank[snapshot.data_quality] < quality_rank[policy.min_data_quality]:
            raise M2ShadowBlocked("PortfolioSnapshot is below RiskPolicy data quality")

    def _select_symbols(self, snapshot: PortfolioSnapshot) -> list[dict[str, str]]:
        max_symbols = min(50, max(1, int(getattr(self._config, "single_brain_m2_max_symbols", 10))))
        holdings_limit = min(50, max(0, int(getattr(self._config, "single_brain_m2_holdings_limit", 10))))
        holding_symbols: list[str] = []
        for position in snapshot.positions:
            if position.quantity <= 0 or str(position.market).upper() != "CN":
                continue
            normalized = self._cn_symbol(position.symbol)
            if normalized and normalized not in holding_symbols:
                holding_symbols.append(normalized)
            if len(holding_symbols) >= holdings_limit:
                break
        allowlist: list[str] = []
        for raw in getattr(self._config, "single_brain_m2_symbols", ()) or ():
            normalized = self._cn_symbol(raw)
            if normalized and normalized not in allowlist:
                allowlist.append(normalized)
        ordered = (holding_symbols + [item for item in allowlist if item not in holding_symbols])[:max_symbols]
        holding_set = set(holding_symbols)
        allowlist_set = set(allowlist)
        return [
            {
                "symbol": symbol,
                "source": (
                    "BOTH"
                    if symbol in holding_set and symbol in allowlist_set
                    else "HOLDING"
                    if symbol in holding_set
                    else "ALLOWLIST"
                ),
            }
            for symbol in ordered
        ]

    @staticmethod
    def _cn_symbol(value: Any) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            normalized = canonical_stock_code(normalize_stock_code(raw))
        except Exception:
            return None
        if str(get_market_for_stock(normalized) or "").upper() != "CN":
            return None
        return normalized

    def _aware_now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise M2ShadowBlocked("M2 clock must be timezone-aware")
        return now
