"""Convert one completed DSA analysis into research and advisory proposal contracts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable

from src.analyzer import AnalysisResult
from src.core.trading_calendar import get_market_for_stock
from src.investment.contracts.base import canonical_json_bytes, decimal_to_json
from src.investment.contracts.candidate_provenance import CandidateProvenance
from src.investment.contracts.investment_proposal import InvestmentProposal
from src.investment.contracts.research_bundle import ModelProvenance, ResearchBundle
from src.investment.research.adapter import ResearchBundleAdapter
from src.investment.shadow_wiring import InvestmentShadowWiringService, ShadowWiringRejected
from src.schemas.decision_action import normalize_decision_action


class ProposalBuildRejected(ValueError):
    """Raised when a completed report cannot safely become a canonical proposal."""


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
        candidate_provenance: CandidateProvenance | None = None,
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
