import json
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
from src.investment.proposal.transport import (
    AthenaProposalAcknowledgement,
    CanonicalHttpInvestmentProposalPublisher,
)
from tests.test_investment_shadow_wiring_p1a import _snapshot


NOW = datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc)


def _ack(proposal, lifecycle_state, *, deduplicated=False):
    return AthenaProposalAcknowledgement(
        proposal_id=proposal.proposal_id,
        proposal_hash=proposal.content_hash,
        acknowledgement_id=f"athena-ack-{proposal.content_hash[:32]}",
        acknowledgement_state="ACCEPTED",
        lifecycle_state=lifecycle_state,
        deduplicated=deduplicated,
    )


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
        def complete(self, **kwargs):
            result = _result("hold")
            result.code = kwargs["symbol"]
            return AnalysisCompletion(result, {}, 11, False, NOW)

    class SnapshotSource:
        def capture_snapshot(self):
            return _snapshot()

    class Publisher:
        def __init__(self):
            self.proposals = []

        def publish(self, proposal):
            self.proposals.append(proposal)
            return _ack(proposal, "NO_ACTION", deduplicated=len(self.proposals) > 2)

    publisher = Publisher()
    service = ProposalHandoffLoopService(
        config=SimpleNamespace(
            single_brain_m2_enabled=True,
            single_brain_m2_interval_minutes=60,
            single_brain_m2_symbols=("000001", "600519", "000001"),
            single_brain_m2_max_symbols=2,
            single_brain_m2_holdings_limit=1,
        ),
        analysis_runner=Runner(), publisher=publisher,
        snapshot_source=SnapshotSource(), clock=lambda: NOW,
    )
    first = service.run_cycle(scheduled_for=NOW)
    second = service.run_cycle(scheduled_for=NOW)
    assert first.status == second.status == "COMPLETED"
    assert first.proposal_ids == second.proposal_ids
    assert all(item.acknowledgement_state == "ACCEPTED" for item in first.acknowledgements)
    assert all(item.lifecycle_state == "NO_ACTION" for item in first.acknowledgements)
    assert first.researched_symbols == second.researched_symbols == (
        "600519:BOTH", "000001:ALLOWLIST",
    )
    assert publisher.proposals[0].canonical_json() == publisher.proposals[2].canonical_json()
    assert publisher.proposals[1].canonical_json() == publisher.proposals[3].canonical_json()
    assert all(item.execution_permitted is False for item in publisher.proposals)


@pytest.mark.parametrize(
    "lifecycle_state",
    (
        "ACCEPTED",
        "NO_ACTION",
        "ALLOCATED",
        "BLOCKED",
        "BLOCKED_PRE_SUBMISSION",
        "PENDING_RECONCILIATION",
        "REJECTED",
        "FILLED",
    ),
)
def test_all_athena_lifecycle_states_are_successful_handoffs(lifecycle_state):
    class Runner:
        def complete(self, **kwargs):
            result = _result("hold")
            result.code = kwargs["symbol"]
            return AnalysisCompletion(result, {}, 12, False, NOW)

    class SnapshotSource:
        def capture_snapshot(self):
            return _snapshot()

    class Publisher:
        def publish(self, proposal):
            return _ack(proposal, lifecycle_state)

    result = ProposalHandoffLoopService(
        config=SimpleNamespace(
            single_brain_m2_enabled=True,
            single_brain_m2_interval_minutes=60,
            single_brain_m2_symbols=("600519",),
            single_brain_m2_max_symbols=1,
            single_brain_m2_holdings_limit=1,
        ),
        analysis_runner=Runner(),
        publisher=Publisher(),
        snapshot_source=SnapshotSource(),
        clock=lambda: NOW,
    ).run_cycle(scheduled_for=NOW)

    assert result.status == "COMPLETED"
    assert len(result.proposal_ids) == 1
    assert result.acknowledgements[0].acknowledgement_state == "ACCEPTED"
    assert result.acknowledgements[0].lifecycle_state == lifecycle_state
    assert result.blocked_reasons == ()


def test_post_timeout_recovers_durable_ack_by_read_only_lookup_without_repost():
    proposal = InvestmentProposalBuilder(clock=lambda: NOW).build(
        result=_result("hold"),
        context_snapshot={},
        source_report_id=13,
        cycle_id="cycle-timeout",
        trigger_source="test",
    ).proposal
    calls = []

    class Response:
        status = 200

        def __init__(self, url, payload):
            self._url = url
            self._payload = json.dumps(payload).encode()

        def geturl(self):
            return self._url

        def read(self, _size):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def opener(request, timeout):
        calls.append((request.get_method(), request.full_url, timeout))
        if request.get_method() == "POST":
            raise TimeoutError("client did not receive the durable ACK")
        return Response(
            request.full_url,
            {
                "status": "ACCEPTED",
                "acknowledgement_id": f"athena-ack-{proposal.content_hash[:32]}",
                "acknowledgement_state": "ACCEPTED",
                "proposal_id": proposal.proposal_id,
                "proposal_hash": proposal.content_hash,
                "lifecycle_state": "PENDING_RECONCILIATION",
                "deduplicated": True,
            },
        )

    acknowledgement = CanonicalHttpInvestmentProposalPublisher(
        url="http://127.0.0.1:8088/api/investment-proposals",
        opener=opener,
    ).publish(proposal)

    assert acknowledgement.lifecycle_state == "PENDING_RECONCILIATION"
    assert [method for method, _, _ in calls] == ["POST", "GET"]
