"""Convert one completed DSA analysis into research and advisory proposal contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable

from src.analyzer import AnalysisResult
from src.core.trading_calendar import get_market_for_stock
from src.investment.contracts.base import canonical_json_bytes, decimal_to_json
from src.investment.contracts.candidate_provenance import CandidateProvenance
from src.investment.contracts.data_evidence import (
    DataEvidence,
    analysis_context_evidence,
    portfolio_snapshot_evidence,
)
from src.investment.contracts.investment_proposal import InvestmentProposal
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.contracts.research_bundle import ModelProvenance, ResearchBundle
from src.investment.contracts.research_trigger import ResearchTrigger
from src.investment.research.adapter import ResearchBundleAdapter
from src.investment.shadow_wiring import InvestmentShadowWiringService, ShadowWiringRejected
from src.schemas.decision_action import normalize_decision_action


class ProposalBuildRejected(ValueError):
    """Raised when a completed report cannot safely become a canonical proposal."""


_PERCENT_TARGET = re.compile(r"(?<![0-9])([0-9]+(?:\.[0-9]+)?)\s*%")
_TEN_TARGET = re.compile(r"(?<![0-9])([0-9]+(?:\.[0-9]+)?)\s*(?:成|成仓)")
_DECIMAL_TARGET = re.compile(r"(?<![0-9.])(0?\.[0-9]+)(?![0-9])")


def _structured_position_target(result: AnalysisResult) -> Decimal | None:
    """Read only an explicit numeric target from the existing DSA position strategy."""
    dashboard = getattr(result, "dashboard", None)
    if not isinstance(dashboard, Mapping):
        return None
    roots: list[Mapping[str, Any]] = [dashboard]
    nested_dashboard = dashboard.get("dashboard")
    if isinstance(nested_dashboard, Mapping):
        roots.append(nested_dashboard)
    raw_value: object | None = None
    for root in roots:
        battle_plan = root.get("battle_plan")
        if not isinstance(battle_plan, Mapping):
            continue
        position_strategy = battle_plan.get("position_strategy")
        if isinstance(position_strategy, Mapping) and "suggested_position" in position_strategy:
            raw_value = position_strategy.get("suggested_position")
            break
    if not isinstance(raw_value, str):
        return None
    text = raw_value.strip()
    matches: list[Decimal] = []
    for pattern, divisor in ((_PERCENT_TARGET, Decimal("100")), (_TEN_TARGET, Decimal("10"))):
        values = pattern.findall(text)
        if values:
            if len(values) != 1:
                return None
            matches.append(Decimal(values[0]) / divisor)
    if not matches:
        values = _DECIMAL_TARGET.findall(text)
        if len(values) == 1:
            matches.append(Decimal(values[0]))
    if len(matches) != 1 or not Decimal("0") < matches[0] <= Decimal("1"):
        return None
    return matches[0].quantize(Decimal("0.000001"), rounding=ROUND_DOWN)


@dataclass(frozen=True)
class InvestmentProposalArtifacts:
    research_bundle: ResearchBundle
    proposal: InvestmentProposal


class InvestmentProposalBuilder:
    """DSA authority boundary: research and advice only, never account sizing."""

    VALIDITY = timedelta(minutes=5)

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def build(
        self,
        *,
        result: AnalysisResult,
        context_snapshot: Mapping[str, Any],
        source_report_id: int,
        cycle_id: str,
        trigger_source: str,
        suggested_target_weight: Decimal | None = None,
        authoritative_snapshot: PortfolioSnapshot | None = None,
        candidate_provenance: CandidateProvenance | None = None,
        research_trigger: ResearchTrigger | dict[str, Any] | None = None,
        data_evidence: tuple[DataEvidence, ...] | None = None,
    ) -> InvestmentProposalArtifacts:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ProposalBuildRejected("proposal clock must be timezone-aware")
        if not isinstance(result, AnalysisResult) or not result.success:
            raise ProposalBuildRejected("a successful completed AnalysisResult is required")
        if not isinstance(source_report_id, int) or isinstance(source_report_id, bool) or source_report_id <= 0:
            raise ProposalBuildRejected("a persisted source report id is required")
        symbol = str(result.code or "").strip()
        market = str(get_market_for_stock(symbol) or "").strip().upper()
        if market != "CN":
            raise ProposalBuildRejected("proposal handoff is limited to CN equities")
        cycle = str(cycle_id or "").strip()
        if not cycle:
            raise ProposalBuildRejected("cycle_id is required")

        normalized = normalize_decision_action(getattr(result, "action", None))
        if normalized in {"buy", "add"}:
            action = "BUY"
        elif normalized == "avoid":
            action = "AVOID"
        elif normalized == "reduce":
            action = "REDUCE"
        elif normalized == "sell":
            action = "SELL"
        elif normalized in {"watch", "hold", "alert"}:
            action = "HOLD"
        else:
            raise ProposalBuildRejected("completed analysis action is unsupported or ambiguous")

        if action == "REDUCE":
            suggested_target_weight = self._reduce_target_weight(
                result=result,
                symbol=symbol,
                suggested_target_weight=suggested_target_weight,
                authoritative_snapshot=authoritative_snapshot,
            )

        entry_floor = entry_limit = stop_price = target_price = None
        expected_return = Decimal("0")
        if action == "BUY":
            try:
                entry_floor, entry_limit, stop_price, target_price = (
                    InvestmentShadowWiringService._price_plan(result)
                )
            except ShadowWiringRejected as exc:
                raise ProposalBuildRejected(str(exc)) from exc
            expected_return = ((target_price - entry_limit) / entry_limit).quantize(
                Decimal("0.000001"), rounding=ROUND_DOWN
            )

        identity_hash = hashlib.sha256(
            canonical_json_bytes(
                {"cycle_id": cycle, "source_report_id": source_report_id, "symbol": symbol}
            )
        ).hexdigest()
        if data_evidence is None:
            data_evidence = ()
            if research_trigger is not None:
                evidence_items = [analysis_context_evidence(
                    context_snapshot=context_snapshot,
                    source_report_id=source_report_id,
                    now=now,
                )]
                if authoritative_snapshot is not None:
                    evidence_items.insert(0, portfolio_snapshot_evidence(
                        snapshot=authoritative_snapshot,
                        now=now,
                    ))
                data_evidence = tuple(evidence_items)
        research = ResearchBundleAdapter.from_dsa_views(
            research_id=f"research-{identity_hash[:32]}",
            trace_id=cycle,
            created_at=now,
            producer="DSA_RESEARCH_AUTHORITY",
            symbol=symbol,
            market=market,
            as_of=now,
            horizon="swing",
            trigger_source=str(trigger_source or "proposal_handoff").strip(),
            candidate_provenance=candidate_provenance,
            research_trigger=(
                research_trigger
                if isinstance(research_trigger, ResearchTrigger)
                else ResearchTrigger.model_validate_json(json.dumps(research_trigger))
                if research_trigger is not None
                else None
            ),
            data_evidence=data_evidence,
            market_regime=InvestmentShadowWiringService._text(
                getattr(result, "trend_prediction", None), "No separate market-regime view."
            ),
            industry_view=InvestmentShadowWiringService._text(
                getattr(result, "sector_position", None), "No separate industry view."
            ),
            fundamental_view=InvestmentShadowWiringService._text(
                getattr(result, "fundamental_analysis", None), "No separate fundamental view."
            ),
            technical_view=InvestmentShadowWiringService._first_text(
                getattr(result, "technical_analysis", None),
                getattr(result, "trend_analysis", None),
                getattr(result, "ma_analysis", None),
                fallback="No separate technical view.",
            ),
            valuation_view=InvestmentShadowWiringService._text(
                InvestmentShadowWiringService._nested_text(
                    getattr(result, "fundamental_context", None), "valuation"
                ),
                "No separate valuation view.",
            ),
            intel_view=InvestmentShadowWiringService._first_text(
                getattr(result, "news_summary", None),
                getattr(result, "market_sentiment", None),
                getattr(result, "hot_topics", None),
                fallback="No separate intelligence view.",
            ),
            capital_flow_view=InvestmentShadowWiringService._text(
                getattr(result, "volume_analysis", None), "No separate capital-flow view."
            ),
            bull_case=InvestmentShadowWiringService._first_text(
                getattr(result, "company_highlights", None),
                getattr(result, "medium_term_outlook", None),
                getattr(result, "analysis_summary", None),
                fallback="No separate bull case.",
            ),
            base_case=InvestmentShadowWiringService._first_text(
                getattr(result, "analysis_summary", None),
                InvestmentShadowWiringService._core_conclusion(result),
                getattr(result, "key_points", None),
                fallback="Completed DSA analysis did not provide a base case.",
            ),
            bear_case=InvestmentShadowWiringService._text(
                getattr(result, "risk_warning", None), "No separate bear case."
            ),
            expected_return_minimum=expected_return,
            expected_return_maximum=expected_return,
            catalysts=InvestmentShadowWiringService._unique_texts(
                getattr(result, "company_highlights", None), getattr(result, "hot_topics", None)
            ),
            risk_factors=InvestmentShadowWiringService._unique_texts(
                getattr(result, "risk_warning", None),
                *InvestmentShadowWiringService._risk_alerts(result),
            ),
            invalidation_conditions=((
                f"Observed price falls below the DSA stop plan {decimal_to_json(stop_price)}."
                if stop_price is not None
                else "Require a new completed analysis before any entry."
            ),),
            evidence_refs=(
                f"dsa-analysis-history:{source_report_id}", f"dsa-analysis-cycle:{cycle}"
            ),
            data_quality=InvestmentShadowWiringService._data_quality(context_snapshot, result),
            confidence=InvestmentShadowWiringService._confidence(result),
            model_provenance=(ModelProvenance(
                model_name=InvestmentShadowWiringService._text(
                    getattr(result, "model_used", None), "DSA_COMPLETED_ANALYSIS"
                ),
                model_version="analysis-result-v1",
                provider="DSA",
                prompt_hash=None,
            ),),
            strategy_refs=("issue-9-dsa-authority",),
        )
        proposal = InvestmentProposal.build(
            proposal_id=f"proposal-{identity_hash[:32]}",
            research_id=research.research_id,
            research_content_hash=research.content_hash,
            cycle_id=cycle,
            trace_id=cycle,
            created_at=now,
            producer="DSA_INVESTMENT_PROPOSAL_AUTHORITY",
            source_report_id=source_report_id,
            source_report_ref=f"dsa-analysis-history:{source_report_id}",
            symbol=symbol,
            market="CN",
            action=action,
            candidate_provenance=candidate_provenance,
            research_trigger=research.research_trigger,
            data_evidence=research.data_evidence,
            confidence=research.confidence,
            expected_return=expected_return,
            suggested_target_weight=suggested_target_weight,
            ideal_entry=entry_floor,
            secondary_entry=entry_limit,
            stop_price=stop_price,
            target_price=target_price,
            thesis=research.base_case,
            risks=research.risk_factors or (research.bear_case,),
            invalidation_conditions=research.invalidation_conditions,
            valid_from=now,
            valid_until=now + self.VALIDITY,
            model_provenance=research.model_provenance,
        )
        return InvestmentProposalArtifacts(research, proposal)

    @staticmethod
    def _reduce_target_weight(
        *,
        result: AnalysisResult,
        symbol: str,
        suggested_target_weight: Decimal | None,
        authoritative_snapshot: PortfolioSnapshot | None,
    ) -> Decimal:
        """Resolve a REDUCE advisory target without giving DSA sizing authority."""
        target = suggested_target_weight
        if target is None:
            if authoritative_snapshot is None:
                raise ProposalBuildRejected(
                    "REDUCE advisory target requires an authoritative PortfolioSnapshot"
                )
            target = _structured_position_target(result)
            if target is None:
                raise ProposalBuildRejected(
                    "REDUCE advisory target is not deterministic in position_strategy"
                )
        try:
            target = Decimal(str(target))
        except (ArithmeticError, ValueError) as exc:
            raise ProposalBuildRejected("REDUCE advisory target is invalid") from exc
        if not Decimal("0") < target <= Decimal("1"):
            raise ProposalBuildRejected("REDUCE advisory target must be in (0, 1]")
        if authoritative_snapshot is None:
            return target
        if (
            authoritative_snapshot.authoritative is not True
            or authoritative_snapshot.read_only is not True
            or authoritative_snapshot.simulation_only is not True
            or authoritative_snapshot.reconciliation_status != "RECONCILED"
            or authoritative_snapshot.equity <= 0
        ):
            raise ProposalBuildRejected("authoritative PortfolioSnapshot is not usable")
        position = authoritative_snapshot.position_for(symbol=symbol, market="CN")
        if position is None or position.quantity <= 0:
            raise ProposalBuildRejected("REDUCE advisory requires an existing authoritative position")
        current_weight = position.market_value / authoritative_snapshot.equity
        if current_weight <= 0 or target >= current_weight:
            raise ProposalBuildRejected(
                "REDUCE advisory target must be lower than current authoritative weight"
            )
        return target
