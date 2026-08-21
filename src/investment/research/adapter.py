"""Explicit DSA research adapter with no allocation or execution authority."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.investment.contracts.candidate_provenance import CandidateProvenance
from src.investment.contracts.data_evidence import DataEvidence
from src.investment.contracts.research_trigger import ResearchTrigger
from src.investment.contracts.research_bundle import (
    ExpectedReturnRange,
    ModelProvenance,
    ResearchBundle,
)


class ResearchBundleAdapter:
    """Combine already-produced DSA views without inventing an action or quantity."""

    @staticmethod
    def from_dsa_views(
        *,
        research_id: str,
        trace_id: str,
        created_at: datetime,
        producer: str,
        symbol: str,
        market: str,
        as_of: datetime,
        horizon: str,
        trigger_source: str,
        market_regime: str,
        industry_view: str,
        fundamental_view: str,
        technical_view: str,
        valuation_view: str,
        intel_view: str,
        capital_flow_view: str,
        bull_case: str,
        base_case: str,
        bear_case: str,
        expected_return_minimum: Decimal,
        expected_return_maximum: Decimal,
        catalysts: tuple[str, ...],
        risk_factors: tuple[str, ...],
        invalidation_conditions: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        data_quality: str,
        confidence: Decimal,
        model_provenance: tuple[ModelProvenance, ...],
        strategy_refs: tuple[str, ...] = (),
        candidate_provenance: CandidateProvenance | None = None,
        research_trigger: ResearchTrigger | None = None,
        data_evidence: tuple[DataEvidence, ...] = (),
        supersedes_id: str | None = None,
    ) -> ResearchBundle:
        return ResearchBundle.build(
            research_id=research_id,
            trace_id=trace_id,
            created_at=created_at,
            producer=producer,
            supersedes_id=supersedes_id,
            symbol=symbol,
            market=market.upper(),
            as_of=as_of,
            horizon=horizon,
            trigger_source=trigger_source,
            candidate_provenance=candidate_provenance,
            research_trigger=research_trigger,
            data_evidence=data_evidence,
            market_regime=market_regime,
            industry_view=industry_view,
            fundamental_view=fundamental_view,
            technical_view=technical_view,
            valuation_view=valuation_view,
            intel_view=intel_view,
            capital_flow_view=capital_flow_view,
            bull_case=bull_case,
            base_case=base_case,
            bear_case=bear_case,
            expected_return_range=ExpectedReturnRange(
                minimum=expected_return_minimum,
                maximum=expected_return_maximum,
            ),
            catalysts=catalysts,
            risk_factors=risk_factors,
            invalidation_conditions=invalidation_conditions,
            evidence_refs=evidence_refs,
            data_quality=data_quality,
            confidence=confidence,
            model_provenance=model_provenance,
            strategy_refs=strategy_refs,
        )
