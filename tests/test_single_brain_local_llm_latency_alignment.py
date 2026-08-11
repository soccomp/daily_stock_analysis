"""Final authoritative Snapshot A refresh after slow Research completion."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot, Position
from src.investment.m2.orchestration import M2ShadowLoopService
from src.investment.m2.repository import M2OperationalRepository
from src.investment.m3.orchestration import M3SimulationExecutionCoordinator
from src.investment.m3.repository import M3ExecutionRepository
from src.investment.shadow_wiring import (
    InvestmentShadowWiringService,
    ShadowWiringRejected,
)
from src.services.decision_scorecard_service import DecisionScorecardService
from src.storage import DatabaseManager, SingleDecisionScorecardRecord
from tests.test_investment_shadow_wiring_p1a import (
    NOW,
    _analysis_result,
    _policy,
    _snapshot,
)
from tests.test_investment_canary_p1 import _hold_snapshot
from tests.test_single_brain_m2_shadow_loop import (
    _AnalysisRunner,
    _PolicySource,
    _config,
)
from tests.test_single_brain_m3_simulation_execution import _Transport


class _SequencedSnapshotSource:
    def __init__(self, *observations, events=None):
        self._observations = list(observations)
        self._events = events
        self.last_response_received_at = None
        self.calls = 0

    def capture_snapshot(self):
        self.calls += 1
        if self._events is not None:
            self._events.append(f"snapshot_capture_{self.calls}")
        if not self._observations:
            raise AssertionError("unexpected authoritative snapshot capture")
        observed, received_at = self._observations.pop(0)
        self.last_response_received_at = received_at
        if isinstance(observed, Exception):
            raise observed
        return observed


class _ExecutionProbe:
    def __init__(self) -> None:
        self.process_calls = []

    def recover_pending(self):
        return SimpleNamespace(pending_decision_ids=())

    def process(self, artifacts):
        self.process_calls.append(artifacts)
        raise AssertionError("unsafe decision reached execution coordinator")


class _PersistedCheckpointFailOnceRepository:
    def __init__(self, real: M2OperationalRepository) -> None:
        self._real = real
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self._real, name)

    def mark_symbol_persisted(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise OSError("checkpoint unavailable after scorecard commit")
        return self._real.mark_symbol_persisted(**kwargs)


class _NoExecutionTransport:
    def __init__(self) -> None:
        self.execute_calls = []
        self.reconcile_calls = []

    def execute(self, mandate, snapshot):
        self.execute_calls.append((mandate, snapshot))
        raise AssertionError("HOLD recovery must not submit")

    def reconcile(self, *, mandate):
        self.reconcile_calls.append(mandate)
        raise AssertionError("HOLD recovery must not reconcile")


class _CoordinatorProbe:
    def __init__(self, real) -> None:
        self._real = real
        self.process_calls = []

    def process(self, artifacts):
        self.process_calls.append(artifacts)
        return self._real.process(artifacts)

    def recover_pending(self):
        return self._real.recover_pending()


class _OrderedAnalysisRunner(_AnalysisRunner):
    def __init__(self, events) -> None:
        super().__init__()
        self._events = events

    def complete(self, **kwargs):
        completion = super().complete(**kwargs)
        self._events.append("research_completed")
        return completion


class _OrderedScorecardStore:
    def __init__(self, real, events) -> None:
        self._real = real
        self._events = events

    def persist_shadow(self, artifacts):
        self._events.append("decision_persisted")
        return self._real.persist_shadow(artifacts)

    def get(self, decision_id):
        return self._real.get(decision_id)


@pytest.fixture
def latency_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'latency-alignment.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _refreshed_snapshot(
    initial: PortfolioSnapshot,
    *,
    as_of,
    revision: int,
    quantity: int = 300,
    available_cash: Decimal = Decimal("400000.00"),
) -> PortfolioSnapshot:
    initial_position = initial.positions[0]
    position = Position(
        symbol=initial_position.symbol,
        market=initial_position.market,
        quantity=quantity,
        available_quantity=quantity,
        avg_cost=initial_position.avg_cost,
        last_price=initial_position.last_price,
        market_value=initial_position.last_price * quantity,
        unrealized_pnl=(initial_position.last_price - initial_position.avg_cost)
        * quantity,
        price_as_of=as_of,
        price_source=initial_position.price_source,
    )
    return PortfolioSnapshot.build(
        **{
            **initial.model_dump(
                exclude={
                    "content_hash",
                    "snapshot_id",
                    "trace_id",
                    "created_at",
                    "as_of",
                    "revision",
                    "supersedes_id",
                    "broker_snapshot_ref",
                    "cash",
                    "available_cash",
                    "positions",
                    "unrealized_pnl",
                }
            ),
            "snapshot_id": f"snapshot-latency-refresh-{revision}",
            "trace_id": f"athena-latency-refresh-{revision}",
            "created_at": as_of,
            "as_of": as_of,
            "revision": revision,
            "supersedes_id": initial.snapshot_id,
            "broker_snapshot_ref": f"athena-sim:latency-refresh:{revision}",
            "cash": available_cash,
            "available_cash": available_cash,
            "positions": (position,),
            "unrealized_pnl": position.unrealized_pnl,
        }
    )


def _service(
    db,
    *,
    source,
    runner=None,
    execution_coordinator=None,
    clock=lambda: NOW,
    lineage_store=None,
    repository=None,
):
    return M2ShadowLoopService(
        config=_config(),
        snapshot_source=source,
        policy_source=_PolicySource(_policy()),
        analysis_runner=runner or _AnalysisRunner(),
        lineage_store=lineage_store or DecisionScorecardService(db_manager=db),
        repository=repository or M2OperationalRepository(db),
        execution_coordinator=execution_coordinator,
        clock=clock,
    )


def test_slow_research_uses_fresh_final_snapshot_for_decision_lineage(latency_db):
    events = []
    initial = _snapshot(as_of=NOW - timedelta(minutes=1))
    decision_time = NOW + timedelta(minutes=6)
    refreshed = _refreshed_snapshot(
        initial,
        as_of=decision_time,
        revision=initial.revision + 1,
    )
    source = _SequencedSnapshotSource(
        (initial, NOW),
        (refreshed, decision_time),
        events=events,
    )
    scorecards = DecisionScorecardService(db_manager=latency_db)

    result = _service(
        latency_db,
        source=source,
        runner=_OrderedAnalysisRunner(events),
        clock=lambda: decision_time,
        lineage_store=_OrderedScorecardStore(scorecards, events),
    ).run_cycle(scheduled_for=NOW)

    assert result.status == "COMPLETED"
    assert source.calls == 2
    item = DecisionScorecardService(db_manager=latency_db).get(
        result.persisted_decision_ids[0]
    )["item"]
    decision = item["investment_decision"]
    assert decision["portfolio_snapshot_id"] == refreshed.snapshot_id
    assert decision["portfolio_snapshot_hash"] == refreshed.content_hash
    assert item["portfolio_snapshot_a"]["revision"] == refreshed.revision
    assert item["portfolio_snapshot_a"]["content_hash"] == refreshed.content_hash
    assert item["portfolio_snapshot_a"]["content_hash"] != initial.content_hash
    assert events == [
        "snapshot_capture_1",
        "research_completed",
        "snapshot_capture_2",
        "decision_persisted",
    ]


@pytest.mark.parametrize(
    ("final_observation", "expected_reason"),
    (
        (
            _snapshot(as_of=NOW - timedelta(minutes=1)),
            "stale",
        ),
        (
            RuntimeError("final authoritative snapshot unavailable"),
            "unavailable",
        ),
    ),
)
def test_stale_or_unavailable_final_refresh_fails_closed_before_execution(
    latency_db,
    final_observation,
    expected_reason,
):
    decision_time = NOW + timedelta(minutes=6)
    source = _SequencedSnapshotSource(
        (_snapshot(as_of=NOW - timedelta(minutes=1)), NOW),
        (final_observation, decision_time),
    )
    execution = _ExecutionProbe()

    result = _service(
        latency_db,
        source=source,
        execution_coordinator=execution,
    ).run_cycle(scheduled_for=NOW)

    assert result.status == "FAILED_CLOSED"
    assert expected_reason in " ".join(result.blocked_reasons).lower()
    assert result.persisted_decision_ids == ()
    assert execution.process_calls == []


def test_changed_account_truth_during_research_drives_sizing_and_snapshot_a(latency_db):
    initial = _snapshot(as_of=NOW - timedelta(minutes=1))
    decision_time = NOW + timedelta(minutes=2)
    refreshed = _refreshed_snapshot(
        initial,
        as_of=decision_time,
        revision=initial.revision + 1,
        quantity=400,
        available_cash=Decimal("350000.00"),
    )
    source = _SequencedSnapshotSource(
        (initial, NOW),
        (refreshed, decision_time),
    )

    result = _service(
        latency_db,
        source=source,
        clock=lambda: decision_time,
    ).run_cycle(scheduled_for=NOW)

    item = DecisionScorecardService(db_manager=latency_db).get(
        result.persisted_decision_ids[0]
    )["item"]
    decision = item["investment_decision"]
    assert decision["current_quantity"] == 400
    assert decision["target_quantity"] == 500
    assert decision["delta_quantity"] == 100
    assert decision["portfolio_snapshot_hash"] == refreshed.content_hash
    assert item["portfolio_snapshot_a"]["available_cash"] == "350000.00"


def test_duplicate_cycle_does_not_refresh_or_duplicate_decision_or_scorecard(latency_db):
    initial = _snapshot(as_of=NOW - timedelta(minutes=1))
    refreshed = _refreshed_snapshot(
        initial,
        as_of=NOW,
        revision=initial.revision + 1,
    )
    source = _SequencedSnapshotSource((initial, NOW), (refreshed, NOW))
    runner = _AnalysisRunner()
    service = _service(latency_db, source=source, runner=runner)

    first = service.run_cycle(scheduled_for=NOW)
    duplicate = service.run_cycle(scheduled_for=NOW + timedelta(minutes=10))

    assert first.status == "COMPLETED"
    assert duplicate.status == "DEDUPLICATED"
    assert source.calls == 2
    assert len(runner.calls) == 1
    assert duplicate.persisted_decision_ids == ()
    with latency_db.get_session() as session:
        scorecard_count = session.execute(
            select(func.count(SingleDecisionScorecardRecord.id))
        ).scalar_one()
    assert scorecard_count == 1


def test_recovery_after_scorecard_commit_keeps_reserved_decision_identity(latency_db):
    initial = _snapshot(as_of=NOW - timedelta(minutes=1))
    first_final = _refreshed_snapshot(
        initial,
        as_of=NOW,
        revision=initial.revision + 1,
    )
    retry_time = NOW + timedelta(minutes=2)
    retry_final = _refreshed_snapshot(
        first_final,
        as_of=retry_time,
        revision=first_final.revision + 1,
    )
    source = _SequencedSnapshotSource(
        (initial, NOW),
        (first_final, NOW),
        (retry_final, retry_time),
    )
    real_repository = M2OperationalRepository(latency_db)
    repository = _PersistedCheckpointFailOnceRepository(real_repository)
    scorecards = DecisionScorecardService(db_manager=latency_db)
    service = _service(
        latency_db,
        source=source,
        repository=repository,
        lineage_store=scorecards,
        clock=lambda: retry_time,
    )

    interrupted = service.run_cycle(scheduled_for=NOW)
    with latency_db.get_session() as session:
        first_row = session.execute(select(SingleDecisionScorecardRecord)).scalar_one()
    original = scorecards.get(first_row.decision_id)["item"]
    recovered = service.run_cycle(scheduled_for=NOW + timedelta(minutes=10))

    assert interrupted.status == "FAILED_CLOSED"
    assert recovered.status == "COMPLETED"
    assert recovered.persisted_decision_ids == (first_row.decision_id,)
    assert source.calls == 3
    assert retry_final.content_hash != first_final.content_hash
    assert original["portfolio_snapshot_a"]["content_hash"] == first_final.content_hash
    assert original["execution_mandate"] is None
    assert scorecards.get(first_row.decision_id)["item"] == original
    with latency_db.get_session() as session:
        assert session.execute(
            select(func.count(SingleDecisionScorecardRecord.id))
        ).scalar_one() == 1


def test_m3_hold_recovery_does_not_repeat_brain_or_coordinator(latency_db):
    initial = _hold_snapshot()
    first_final = _refreshed_snapshot(
        initial,
        as_of=NOW,
        revision=initial.revision + 1,
        quantity=initial.positions[0].quantity,
        available_cash=initial.available_cash,
    )
    retry_time = NOW + timedelta(minutes=2)
    retry_final = _refreshed_snapshot(
        first_final,
        as_of=retry_time,
        revision=first_final.revision + 1,
        quantity=initial.positions[0].quantity,
        available_cash=initial.available_cash,
    )
    source = _SequencedSnapshotSource(
        (initial, NOW),
        (first_final, NOW),
        (retry_final, retry_time),
    )
    real_repository = M2OperationalRepository(latency_db)
    repository = _PersistedCheckpointFailOnceRepository(real_repository)
    scorecards = DecisionScorecardService(db_manager=latency_db)
    transport = _NoExecutionTransport()
    coordinator = _CoordinatorProbe(
        M3SimulationExecutionCoordinator(
            transport=transport,
            repository=M3ExecutionRepository(latency_db),
            scorecard_store=scorecards,
            m2_repository=repository,
            allowed_symbols=frozenset({"600519"}),
        )
    )
    service = _service(
        latency_db,
        source=source,
        repository=repository,
        lineage_store=scorecards,
        execution_coordinator=coordinator,
        clock=lambda: retry_time,
    )

    interrupted = service.run_cycle(scheduled_for=NOW)
    with latency_db.get_session() as session:
        first_row = session.execute(select(SingleDecisionScorecardRecord)).scalar_one()
    recovered = service.run_cycle(scheduled_for=NOW + timedelta(minutes=10))

    assert interrupted.status == "FAILED_CLOSED"
    assert recovered.status == "COMPLETED"
    assert recovered.persisted_decision_ids == (first_row.decision_id,)
    assert source.calls == 3
    assert len(coordinator.process_calls) == 1
    assert transport.execute_calls == transport.reconcile_calls == []
    item = scorecards.get(first_row.decision_id)["item"]
    assert item["investment_decision"]["action"] == "HOLD"
    assert item["portfolio_snapshot_a"]["content_hash"] == first_final.content_hash
    assert item["execution_mandate"] is None
    assert item["execution_results"] == []
    assert item["portfolio_snapshot_b"] is None
    with latency_db.get_session() as session:
        assert session.execute(
            select(func.count(SingleDecisionScorecardRecord.id))
        ).scalar_one() == 1


def test_m3_filled_recovery_does_not_create_second_mandate_or_submission(latency_db):
    initial = _snapshot(as_of=NOW - timedelta(minutes=1))
    first_final = _refreshed_snapshot(
        initial,
        as_of=NOW,
        revision=initial.revision + 1,
    )
    retry_time = NOW + timedelta(minutes=2)
    retry_final = _refreshed_snapshot(
        first_final,
        as_of=retry_time,
        revision=first_final.revision + 2,
        quantity=500,
        available_cash=Decimal("380000.00"),
    )
    source = _SequencedSnapshotSource(
        (initial, NOW),
        (first_final, NOW),
        (retry_final, retry_time),
    )
    real_repository = M2OperationalRepository(latency_db)
    repository = _PersistedCheckpointFailOnceRepository(real_repository)
    scorecards = DecisionScorecardService(db_manager=latency_db)
    transport = _Transport()
    coordinator = _CoordinatorProbe(
        M3SimulationExecutionCoordinator(
            transport=transport,
            repository=M3ExecutionRepository(latency_db),
            scorecard_store=scorecards,
            m2_repository=repository,
            allowed_symbols=frozenset({"600519"}),
        )
    )
    service = _service(
        latency_db,
        source=source,
        repository=repository,
        lineage_store=scorecards,
        execution_coordinator=coordinator,
        clock=lambda: retry_time,
    )

    interrupted = service.run_cycle(scheduled_for=NOW)
    with latency_db.get_session() as session:
        first_row = session.execute(select(SingleDecisionScorecardRecord)).scalar_one()
    recovered = service.run_cycle(scheduled_for=NOW + timedelta(minutes=10))

    assert interrupted.status == "FAILED_CLOSED"
    assert recovered.status == "COMPLETED"
    assert recovered.persisted_decision_ids == (first_row.decision_id,)
    assert source.calls == 3
    assert len(coordinator.process_calls) == 1
    assert len(transport.execute_calls) == 1
    assert transport.reconcile_calls == []
    mandate = transport.execute_calls[0][0]
    item = scorecards.get(first_row.decision_id)["item"]
    assert mandate.decision_id == first_row.decision_id
    assert mandate.quantity == item["investment_decision"]["delta_quantity"] == 200
    assert item["execution_mandate"]["mandate_id"] == mandate.mandate_id
    assert len(item["execution_results"]) == 1
    assert item["portfolio_snapshot_b"] is not None
    with latency_db.get_session() as session:
        assert session.execute(
            select(func.count(SingleDecisionScorecardRecord.id))
        ).scalar_one() == 1


def test_shadow_wiring_still_rejects_snapshot_older_than_five_minutes():
    assert InvestmentShadowWiringService.MAX_SNAPSHOT_AGE == timedelta(minutes=5)
    with pytest.raises(ShadowWiringRejected, match="snapshot is stale"):
        InvestmentShadowWiringService(clock=lambda: NOW).build_from_analysis(
            result=_analysis_result(),
            context_snapshot={"data_quality": {"level": "good"}},
            source_report_id=42,
            trace_id="cycle:latency:stale",
            trigger_source="single_brain_m2_shadow",
            portfolio_snapshot=_snapshot(as_of=NOW - timedelta(seconds=301)),
            risk_policy=_policy(),
        )
