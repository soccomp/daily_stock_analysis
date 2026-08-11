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
from tests.test_single_brain_m2_shadow_loop import (
    _AnalysisRunner,
    _PolicySource,
    _config,
)


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
):
    return M2ShadowLoopService(
        config=_config(),
        snapshot_source=source,
        policy_source=_PolicySource(_policy()),
        analysis_runner=runner or _AnalysisRunner(),
        lineage_store=lineage_store or DecisionScorecardService(db_manager=db),
        repository=M2OperationalRepository(db),
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
