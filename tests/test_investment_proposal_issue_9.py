from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.analyzer import AnalysisResult
from src.investment.contracts.investment_proposal import InvestmentProposal
from src.investment.proposal.builder import InvestmentProposalBuilder
from src.investment.m2.orchestration import AnalysisCompletion
from src.investment.proposal.orchestration import ProposalHandoffLoopService


NOW = datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc)


def _result(action="buy"):
    return AnalysisResult(
        code="600519", name="贵州茅台", sentiment_score=76,
        trend_prediction="中期上行趋势", operation_advice="买入",
        decision_type="buy", confidence_level="高", action=action,
        technical_analysis="技术面改善。", fundamental_analysis="基本面稳健。",
        analysis_summary="研究结论支持观察性建议。", risk_warning="需求转弱。",
        model_used="test/dsa-model",
        dashboard={"battle_plan": {"sniper_points": {
            "ideal_buy": 95, "secondary_buy": 100,
            "stop_loss": 80, "take_profit": 130,
        }}},
    )


def test_buy_proposal_is_canonical_advice_without_allocation_or_execution_fields():
    artifacts = InvestmentProposalBuilder(clock=lambda: NOW).build(
        result=_result(), context_snapshot={}, source_report_id=9,
        cycle_id="cycle-issue-9", trigger_source="test",
        suggested_target_weight=Decimal("0.080000"),
    )
    proposal = artifacts.proposal
    assert InvestmentProposal.model_validate_json(proposal.canonical_json()) == proposal
    assert proposal.action == "BUY"
    assert proposal.suggested_target_weight == Decimal("0.080000")
    forbidden = ("quantity", "cash", "exposure", "risk_policy", "mandate", "broker", "fill")
    assert not any(token in InvestmentProposal.model_fields for token in forbidden)
    assert proposal.advisory_only is True
    assert proposal.final_allocation_permitted is False
    assert proposal.execution_permitted is False


def test_hold_proposal_has_no_price_plan_and_tampering_breaks_hash():
    proposal = InvestmentProposalBuilder(clock=lambda: NOW).build(
        result=_result("hold"), context_snapshot={}, source_report_id=10,
        cycle_id="cycle-hold", trigger_source="test",
    ).proposal
    assert proposal.action == "HOLD"
    assert proposal.secondary_entry is None
    payload = proposal.model_dump(mode="python")
    payload["thesis"] = "tampered"
    with pytest.raises(ValidationError, match="content_hash"):
        InvestmentProposal.model_validate(payload)


def test_normal_recurring_path_stops_at_deterministic_proposal_handoff():
    class Runner:
        def complete(self, **_kwargs):
            return AnalysisCompletion(_result("hold"), {}, 11, False, NOW)

    class Publisher:
        def __init__(self):
            self.proposals = []

        def publish(self, proposal):
            self.proposals.append(proposal)
            return {"status": "NO_ACTION", "proposal_id": proposal.proposal_id}

    publisher = Publisher()
    service = ProposalHandoffLoopService(
        config=SimpleNamespace(
            single_brain_m2_enabled=True,
            single_brain_m2_interval_minutes=60,
            single_brain_proposal_symbols=("600519",),
        ),
        analysis_runner=Runner(), publisher=publisher, clock=lambda: NOW,
    )
    first = service.run_cycle(scheduled_for=NOW)
    second = service.run_cycle(scheduled_for=NOW)
    assert first.status == second.status == "COMPLETED"
    assert first.proposal_ids == second.proposal_ids
    assert publisher.proposals[0].canonical_json() == publisher.proposals[1].canonical_json()
    assert publisher.proposals[0].execution_permitted is False
