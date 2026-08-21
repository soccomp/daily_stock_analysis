"""PALLAS-008 external discovery ingress stays on the DSA coordinator path."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.v1.endpoints import single_brain_m2
from src.analyzer import AnalysisResult
from src.investment.contracts.research_trigger import ResearchTrigger
from src.investment.m2.research_trigger import ResearchTriggerCoordinator
from src.investment.m2.orchestration import AnalysisCompletion
from src.investment.proposal.orchestration import ProposalHandoffLoopService
from src.investment.proposal.transport import AthenaProposalAcknowledgement
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.storage import DatabaseManager


NOW = datetime(2026, 8, 22, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def trigger_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'pallas-008-ingress.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _trigger():
    return ResearchTrigger.build(
        research_trigger_id="research-trigger-pallas-008-ingress",
        trigger_type="MANUAL_OWNER_REVIEW",
        trigger_source="athena:pallas-008-autonomous-investing",
        symbol="600002",
        market="CN",
        priority=6,
        created_at=NOW,
        source_event_time=NOW,
        effective_at=NOW,
        scheduled_for=NOW,
        dedup_key="PALLAS-008:MANUAL_OWNER_REVIEW:2026-08-22:600002",
        policy_version="pallas-004-research-trigger-v1",
        evidence_refs=("market-candidate:600002", "market-reference:benchmark:P008"),
    )


def test_pallas008_ingress_uses_canonical_coordinator_ledger(trigger_db):
    coordinator = ResearchTriggerCoordinator(trigger_db)
    first = coordinator.enqueue(_trigger())
    duplicate = coordinator.enqueue(_trigger())

    assert (first.status, first.created) == ("FIRED", True)
    assert (duplicate.status, duplicate.created) == ("DEDUPLICATED", False)
    assert duplicate.duplicate_count == 1
    assert [item.research_trigger_id for item in coordinator.ledger.pending(now=NOW)] == [
        "research-trigger-pallas-008-ingress"
    ]


def test_pallas008_http_ingress_delegates_to_the_same_coordinator(monkeypatch, trigger_db):
    monkeypatch.setattr(single_brain_m2.DatabaseManager, "get_instance", lambda: trigger_db)
    monkeypatch.delenv("PALLAS_DSA_RESEARCH_TRIGGER_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_AUTH_ENABLED", raising=False)

    response = single_brain_m2.enqueue_research_trigger(_trigger().model_dump(mode="json"))

    assert response.status == "ACCEPTED"
    assert response.enqueue_status == "FIRED"
    assert response.research_trigger_id == "research-trigger-pallas-008-ingress"
    assert ResearchTriggerCoordinator(trigger_db).ledger.get(response.research_trigger_id) is not None


def test_pallas008_http_ingress_exercises_the_real_route_and_coordinator(monkeypatch, trigger_db):
    monkeypatch.setattr(single_brain_m2.DatabaseManager, "get_instance", lambda: trigger_db)
    monkeypatch.delenv("PALLAS_DSA_RESEARCH_TRIGGER_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_AUTH_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(single_brain_m2.router, prefix="/api/v1/single-brain/m2")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/single-brain/m2/research-triggers",
            json=_trigger().model_dump(mode="json"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ACCEPTED"
    assert payload["enqueue_status"] == "FIRED"
    assert payload["research_trigger_id"] == "research-trigger-pallas-008-ingress"
    assert ResearchTriggerCoordinator(trigger_db).ledger.get(payload["research_trigger_id"]) is not None


def test_enqueued_trigger_enters_the_existing_research_and_proposal_builder_path(trigger_db):
    trigger = _trigger()
    coordinator = ResearchTriggerCoordinator(trigger_db)
    assert coordinator.enqueue(trigger).status == "FIRED"

    class Runner:
        def complete(self, **kwargs):
            result = AnalysisResult(
                code=kwargs["symbol"], name="Pallas candidate", sentiment_score=76,
                trend_prediction="中期上行趋势", operation_advice="买入",
                decision_type="buy", confidence_level="高", action="buy",
                technical_analysis="技术面改善。", fundamental_analysis="基本面稳健。",
                analysis_summary="研究结论支持观察性建议。", risk_warning="需求转弱。",
                model_used="test/pallas-008-dsa-model",
                dashboard={"battle_plan": {"sniper_points": {
                    "ideal_buy": 95, "secondary_buy": 100,
                    "stop_loss": 80, "take_profit": 140,
                }}},
            )
            return AnalysisCompletion(result, {}, 11, False, NOW)

    class SnapshotSource:
        def capture_snapshot(self):
            return PortfolioSnapshot.build(
                snapshot_id="pallas-008-empty-snapshot",
                trace_id="pallas-008-snapshot-trace",
                created_at=NOW,
                producer="ATHENA_SIMULATION_RECONCILIATION",
                account_id="simulation-account-1",
                broker="ATHENA_DECIMAL_SIM",
                account_mode="SIMULATION",
                as_of=NOW,
                revision=1,
                currency="CNY",
                equity=Decimal("1000000"),
                cash=Decimal("1000000"),
                available_cash=Decimal("1000000"),
                reserved_cash=Decimal("0"),
                positions=(),
                active_orders=(),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                reconciliation_status="RECONCILED",
                data_quality="HIGH",
                limitations=(),
                broker_snapshot_ref="pallas-008:empty-snapshot",
            )

    class Publisher:
        def __init__(self):
            self.proposals = []

        def publish(self, proposal):
            self.proposals.append(proposal)
            return AthenaProposalAcknowledgement(
                proposal_id=proposal.proposal_id,
                proposal_hash=proposal.content_hash,
                acknowledgement_id=f"athena-ack-{proposal.content_hash[:32]}",
                acknowledgement_state="ACCEPTED",
                lifecycle_state="NO_ACTION",
                deduplicated=False,
            )

    publisher = Publisher()
    result = ProposalHandoffLoopService(
        config=SimpleNamespace(
            single_brain_m2_enabled=True,
            single_brain_m2_interval_minutes=60,
            single_brain_m2_symbols=(),
            single_brain_m2_max_symbols=1,
            single_brain_m2_holdings_limit=1,
        ),
        analysis_runner=Runner(),
        publisher=publisher,
        snapshot_source=SnapshotSource(),
        trigger_coordinator=coordinator,
        clock=lambda: NOW,
    ).run_cycle(scheduled_for=NOW)

    assert result.status == "COMPLETED"
    assert len(publisher.proposals) == 1
    proposal = publisher.proposals[0]
    assert proposal.symbol == trigger.symbol
    assert proposal.research_trigger is not None
    assert proposal.research_trigger.research_trigger_id == trigger.research_trigger_id
    assert result.acknowledgements[0].acknowledgement_state == "ACCEPTED"
    assert coordinator.ledger.pending(now=NOW) == ()
