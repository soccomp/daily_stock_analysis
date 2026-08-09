from datetime import timedelta
from decimal import Decimal
import pytest

from src.config import Config
from src.investment.contracts.execution_result import ExecutionResult, SafetyCheck
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot, Position
from src.investment.integration.execution_transport import (
    AthenaExecutionObservation,
    ExecutionTransportUncertain,
)
from src.investment.execution_projection.mandate import ExecutionMandateProjector
from src.investment.m3.orchestration import (
    M3ExecutionBlocked,
    M3SimulationExecutionCoordinator,
)
from src.investment.m3.repository import M3ExecutionRepository
from src.investment.m2.orchestration import DSAAnalysisCompletionRunner, M2ShadowLoopService
from src.investment.m2.repository import M2OperationalRepository
from src.investment.shadow_wiring import InvestmentShadowWiringService
from src.services.decision_scorecard_service import DecisionScorecardService
from src.storage import DatabaseManager
from tests.test_investment_shadow_wiring_p1a import (
    NOW,
    _analysis_result,
    _policy,
    _snapshot,
)
from tests.test_investment_canary_p1 import _hold_snapshot
from tests.test_single_brain_m2_shadow_loop import _PolicySource, _SnapshotSource, _config


class _M2Facts:
    def __init__(self):
        self.persisted = []
        self.closed = []

    def mark_symbol_persisted(self, **kwargs):
        self.persisted.append(kwargs)

    def close_cycle(self, *, cycle_id):
        self.closed.append(cycle_id)


def _artifacts(*, snapshot=None):
    return InvestmentShadowWiringService(clock=lambda: NOW).build_from_analysis(
        result=_analysis_result(),
        context_snapshot={"data_quality": {"level": "good"}},
        source_report_id=42,
        trace_id="cycle:m3:test",
        trigger_source="single_brain_m3_simulation_execution",
        portfolio_snapshot=snapshot or _snapshot(),
        risk_policy=_policy(),
        decision_cycle_id="cycle:m3:test",
        decision_id="decision:m3:test",
        allow_nonpositive_return=True,
    )


def _snapshot_b(snapshot_a, *, filled_quantity=200):
    position = snapshot_a.positions[0]
    quantity = position.quantity + filled_quantity
    return PortfolioSnapshot.build(
        snapshot_id="snapshot:m3:b",
        trace_id=snapshot_a.trace_id,
        created_at=NOW,
        producer="ATHENA_SINGLE_BRAIN_M3_SIMULATION",
        supersedes_id=snapshot_a.snapshot_id,
        account_id=snapshot_a.account_id,
        broker=snapshot_a.broker,
        account_mode="SIMULATION",
        as_of=NOW,
        revision=snapshot_a.revision + 1,
        currency="CNY",
        equity=snapshot_a.equity,
        cash=snapshot_a.cash - Decimal("100.00") * filled_quantity,
        available_cash=snapshot_a.available_cash - Decimal("100.00") * filled_quantity,
        reserved_cash=Decimal("0.00"),
        positions=(
            Position(
                symbol=position.symbol,
                market=position.market,
                quantity=quantity,
                available_quantity=quantity,
                avg_cost=position.avg_cost,
                last_price=position.last_price,
                market_value=position.last_price * quantity,
                unrealized_pnl=position.unrealized_pnl,
                price_as_of=NOW,
                price_source=position.price_source,
            ),
        ),
        active_orders=(),
        realized_pnl=snapshot_a.realized_pnl,
        unrealized_pnl=snapshot_a.unrealized_pnl,
        reconciliation_status="RECONCILED",
        data_quality="HIGH",
        limitations=(),
        broker_snapshot_ref="athena-sim:m3-snapshot-b",
    )


def _filled_observation(mandate, snapshot_b, *, supersedes_id=None):
    result = ExecutionResult.build(
        result_id=("result:m3:filled" if supersedes_id is None else "result:m3:reconciled"),
        trace_id=mandate.trace_id,
        created_at=NOW,
        producer="ATHENA_SINGLE_BRAIN_M3_SIMULATION",
        supersedes_id=supersedes_id,
        mandate_id=mandate.mandate_id,
        mandate_hash=mandate.content_hash,
        decision_id=mandate.decision_id,
        decision_hash=mandate.decision_hash,
        attempt_no=1,
        account_id=mandate.account_id,
        symbol=mandate.symbol,
        status="FILLED",
        requested_quantity=mandate.quantity,
        submitted_quantity=mandate.quantity,
        filled_quantity=mandate.quantity,
        remaining_quantity=0,
        requested_limit_price=mandate.limit_price,
        average_fill_price=mandate.limit_price,
        fees=Decimal("0.00"),
        slippage_bps=Decimal("0.00"),
        broker_order_id="broker-order-m3-1",
        correlation_id="correlation-m3-1",
        safety_checks=(SafetyCheck(check="EXACT_QUANTITY", status="PASSED"),),
        submitted_at=NOW,
        last_update_at=NOW,
        completed_at=NOW,
        broker_evidence_ref="athena-sim:order-evidence",
        reconciliation_status="RECONCILED",
        portfolio_snapshot_after_id=snapshot_b.snapshot_id,
        portfolio_snapshot_after_hash=snapshot_b.content_hash,
    )
    return AthenaExecutionObservation(result, snapshot_b, (mandate.quantity,))


class _Transport:
    def __init__(self, *, uncertain_once=False):
        self.execute_calls = []
        self.reconcile_calls = []
        self.uncertain_once = uncertain_once
        self.previous_result_id = None

    def execute(self, mandate, snapshot):
        self.execute_calls.append((mandate, snapshot))
        if self.uncertain_once:
            self.uncertain_once = False
            raise ExecutionTransportUncertain("response lost after one dispatch")
        return _filled_observation(mandate, _snapshot_b(snapshot))

    def reconcile(self, *, mandate):
        self.reconcile_calls.append(mandate)
        return _filled_observation(
            mandate,
            _snapshot_b(_snapshot()),
            supersedes_id=self.previous_result_id,
        )


@pytest.fixture
def m3_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'm3.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _coordinator(m3_db, transport):
    return M3SimulationExecutionCoordinator(
        transport=transport,
        repository=M3ExecutionRepository(m3_db),
        scorecard_store=DecisionScorecardService(db_manager=m3_db),
        m2_repository=_M2Facts(),
        allowed_symbols=frozenset({"600519"}),
    )


def test_m3_exact_quantity_closes_full_lineage_and_deduplicates_dispatch(m3_db):
    artifacts = _artifacts()
    transport = _Transport()
    coordinator = _coordinator(m3_db, transport)

    first = coordinator.process(artifacts)
    duplicate = coordinator.process(artifacts)

    assert first.status == duplicate.status == "PERSISTED"
    assert len(transport.execute_calls) == 1
    assert transport.reconcile_calls == []
    mandate = transport.execute_calls[0][0]
    assert mandate.quantity == artifacts.investment_decision.delta_quantity == 200
    checkpoint = M3ExecutionRepository(m3_db).get(first.decision_id)
    assert checkpoint.dispatch_attempt_count == 1
    assert checkpoint.status == "COMPLETED"
    scorecard = DecisionScorecardService(db_manager=m3_db).get(first.decision_id)["item"]
    assert scorecard["execution_mandate"]["quantity"] == 200
    assert scorecard["execution_results"][-1]["submitted_quantity"] == 200
    assert scorecard["portfolio_snapshot_b"]["positions"][0]["quantity"] == 500
    assert scorecard["execution_diagnostics"]["mode"] == "SIMULATION_EXECUTION"
    assert scorecard["decision_signal"]["execution_permitted"] is True


def test_m3_uncertain_never_resubmits_and_restart_path_reconciles_only(m3_db):
    artifacts = _artifacts()
    transport = _Transport(uncertain_once=True)
    coordinator = _coordinator(m3_db, transport)

    pending = coordinator.process(artifacts)
    recovered = coordinator.process(artifacts)

    assert pending.status == "PENDING_RECONCILIATION"
    assert recovered.status == "PERSISTED"
    assert len(transport.execute_calls) == 1
    assert len(transport.reconcile_calls) == 1
    checkpoint = M3ExecutionRepository(m3_db).get(recovered.decision_id)
    assert checkpoint.dispatch_attempt_count == 1
    assert checkpoint.status == "COMPLETED"


def test_m3_dispatch_claim_is_atomic_and_single_attempt(m3_db):
    artifacts = _artifacts()
    transport = _Transport()
    coordinator = _coordinator(m3_db, transport)
    lineage = coordinator._lineage(artifacts)
    mandate = ExecutionMandateProjector.project(artifacts.investment_decision)
    repository = M3ExecutionRepository(m3_db)
    repository.prepare(lineage=lineage, mandate=mandate)

    assert repository.claim_dispatch(artifacts.investment_decision.decision_id) is True
    assert repository.claim_dispatch(artifacts.investment_decision.decision_id) is False
    assert repository.get(artifacts.investment_decision.decision_id).dispatch_attempt_count == 1


def test_m3_feature_defaults_fail_closed():
    config = Config()
    assert config.single_brain_execution_mode == "SHADOW"
    assert config.single_brain_simulation_execution_authorized is False
    assert config.single_brain_m3_execution_url is None
    assert config.single_brain_m3_execution_symbols == []


def test_m3_hold_persists_one_scorecard_without_mandate_or_transport(m3_db):
    artifacts = _artifacts(snapshot=_hold_snapshot())
    assert artifacts.investment_decision.action == "HOLD"
    transport = _Transport()
    coordinator = _coordinator(m3_db, transport)

    result = coordinator.process(artifacts)

    assert result.status == "PERSISTED"
    assert transport.execute_calls == transport.reconcile_calls == []
    scorecard = DecisionScorecardService(db_manager=m3_db).get(result.decision_id)["item"]
    assert scorecard["execution_mandate"] is None
    assert scorecard["execution_results"] == []
    assert scorecard["portfolio_snapshot_b"] is None
    assert scorecard["decision_signal"]["execution_permitted"] is False


def test_m3_non_allowlisted_decision_produces_no_dispatch(m3_db):
    artifacts = _artifacts()
    transport = _Transport()
    coordinator = M3SimulationExecutionCoordinator(
        transport=transport,
        repository=M3ExecutionRepository(m3_db),
        scorecard_store=DecisionScorecardService(db_manager=m3_db),
        m2_repository=_M2Facts(),
        allowed_symbols=frozenset({"000001"}),
    )

    with pytest.raises(M3ExecutionBlocked, match="allowlist"):
        coordinator.process(artifacts)

    assert transport.execute_calls == transport.reconcile_calls == []


def test_real_persisted_analysis_completion_runs_one_m3_cycle_and_deduplicates(m3_db):
    pipeline_calls = []

    class _Pipeline:
        def process_single_stock(self, symbol, **kwargs):
            pipeline_calls.append((symbol, kwargs))
            result = _analysis_result()
            m3_db.save_analysis_history(
                result=result,
                query_id=kwargs["analysis_query_id"],
                report_type="simple",
                news_content="observed news",
                context_snapshot={"data_quality": {"level": "good"}},
                save_snapshot=True,
            )
            return result

    config = _config()
    config.single_brain_execution_mode = "SIMULATION_EXECUTION"
    config.single_brain_simulation_execution_authorized = True
    transport = _Transport()
    repository = M2OperationalRepository(m3_db)
    coordinator = M3SimulationExecutionCoordinator(
        transport=transport,
        repository=M3ExecutionRepository(m3_db),
        scorecard_store=DecisionScorecardService(db_manager=m3_db),
        m2_repository=repository,
        allowed_symbols=frozenset({"600519"}),
    )
    service = M2ShadowLoopService(
        config=config,
        snapshot_source=_SnapshotSource(_snapshot(), response_received_at=NOW),
        policy_source=_PolicySource(_policy()),
        analysis_runner=DSAAnalysisCompletionRunner(
            config=config,
            db_manager=m3_db,
            pipeline_factory=lambda **_kwargs: _Pipeline(),
            query_source="single_brain_m3_simulation_execution",
        ),
        lineage_store=DecisionScorecardService(db_manager=m3_db),
        repository=repository,
        execution_coordinator=coordinator,
        clock=lambda: NOW,
    )

    first = service.run_cycle(scheduled_for=NOW)
    duplicate = service.run_cycle(scheduled_for=NOW + timedelta(minutes=10))

    assert first.status == "COMPLETED"
    assert duplicate.status == "DEDUPLICATED"
    assert len(pipeline_calls) == 1
    assert len(transport.execute_calls) == 1
    assert transport.execute_calls[0][0].quantity == 200
    assert len(first.persisted_decision_ids) == 1
    scorecard = DecisionScorecardService(db_manager=m3_db).get(
        first.persisted_decision_ids[0]
    )["item"]
    assert scorecard["research_bundle"]["trigger_source"] == (
        "single_brain_m3_simulation_execution"
    )
    assert scorecard["execution_diagnostics"]["execution_authorization"] == "ON"
