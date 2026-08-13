"""Deterministic 20-cycle M2 shadow burn-in with no wall-clock sleeps."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot, Position
from src.investment.m2.orchestration import AnalysisCompletion, M2ShadowLoopService
from src.investment.m2.repository import M2OperationalRepository
from src.investment.scorecard import SingleDecisionScorecard
from src.services.decision_scorecard_service import DecisionScorecardService
from src.storage import (
    DatabaseManager,
    SingleBrainM2CycleRecord,
    SingleDecisionScorecardRecord,
)
from tests.test_investment_shadow_wiring_p1a import NOW, _analysis_result, _policy, _snapshot
from tests.test_single_brain_m2_shadow_loop import _PolicySource, _SnapshotSource, _config


@pytest.fixture
def burnin_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'm2-burnin.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _position(symbol: str, quantity: int, *, as_of) -> Position:
    market_value = Decimal(quantity) * Decimal("100.00")
    return Position(
        symbol=symbol,
        market="CN",
        quantity=quantity,
        available_quantity=quantity,
        avg_cost=Decimal("90.00"),
        last_price=Decimal("100.00"),
        market_value=market_value,
        unrealized_pnl=Decimal(quantity) * Decimal("10.00"),
        price_as_of=as_of,
        price_source="ATHENA_MYQUANT_SIMULATION_RUNTIME",
    )


def _burnin_snapshot(index: int, *, now) -> PortfolioSnapshot:
    as_of = now - timedelta(minutes=1)
    base = _snapshot(as_of=as_of)
    holding_quantity = 100 + (index % 4) * 100
    review_quantity = 200 + (index % 2) * 100
    available_cash = Decimal("700000.00") - Decimal(index * 1000)
    return PortfolioSnapshot.build(
        **{
            **base.model_dump(
                exclude={
                    "content_hash",
                    "snapshot_id",
                    "trace_id",
                    "revision",
                    "supersedes_id",
                    "broker_snapshot_ref",
                    "cash",
                    "available_cash",
                    "positions",
                    "unrealized_pnl",
                }
            ),
            "snapshot_id": f"snapshot-m2-burnin-{index:02d}",
            "trace_id": f"athena-runtime-burnin-{index:02d}",
            "revision": index,
            "supersedes_id": (
                None if index == 0 else f"snapshot-m2-burnin-{index - 1:02d}"
            ),
            "broker_snapshot_ref": f"athena-sim:burnin:{index:02d}",
            "cash": available_cash,
            "available_cash": available_cash,
            "positions": (
                _position("600519", holding_quantity, as_of=as_of),
                _position("000002", review_quantity, as_of=as_of),
            ),
            "unrealized_pnl": Decimal(holding_quantity + review_quantity)
            * Decimal("10.00"),
        }
    )


class _BurninAnalysisRunner:
    def __init__(self) -> None:
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        symbol = kwargs["symbol"]
        sequence = len(self.calls)
        result = _analysis_result()
        result.code = symbol
        result.name = f"M2 burn-in {symbol}"
        result.analysis_summary = f"Cycle evidence revision {sequence} for {symbol}."
        result.company_highlights = f"Observed catalyst revision {sequence}."
        if symbol == "000002":
            result.action = "watch"
            result.operation_advice = "观望"
            result.dashboard["battle_plan"]["sniper_points"]["take_profit"] = 90
            result.risk_warning = (
                f"Holding thesis weakening at evidence revision {sequence}; do not add."
            )
        return AnalysisCompletion(
            result=result,
            context_snapshot={"data_quality": {"level": "good"}},
            source_report_id=10000 + sequence,
            recovered=False,
        )


def _burnin_service(db, *, snapshot, now, runner, enabled=True):
    config = _config(enabled=enabled)
    config.single_brain_m2_symbols = ["600519", "000001", "000002", "000001"]
    config.single_brain_m2_max_symbols = 3
    config.single_brain_m2_holdings_limit = 3
    config.single_brain_m2_interval_minutes = 10
    return M2ShadowLoopService(
        config=config,
        snapshot_source=_SnapshotSource(snapshot),
        policy_source=_PolicySource(_policy()),
        analysis_runner=runner,
        lineage_store=DecisionScorecardService(db_manager=db),
        repository=M2OperationalRepository(db),
        clock=lambda: now,
    )


def test_twenty_cycle_three_symbol_shadow_burnin_is_unique_recoverable_and_nonexecuting(
    burnin_db,
):
    runner = _BurninAnalysisRunner()
    completed = []
    duplicate_calls_before = None

    for index in range(20):
        now = NOW + timedelta(minutes=10 * index)
        snapshot = _burnin_snapshot(index, now=now)
        service = _burnin_service(
            burnin_db,
            snapshot=snapshot,
            now=now,
            runner=runner,
        )
        result = service.run_cycle(scheduled_for=now)
        assert result.status == "COMPLETED"
        assert len(result.persisted_decision_ids) == 3
        completed.append(result)

        if index == 7:
            duplicate_calls_before = len(runner.calls)
            duplicate = _burnin_service(
                burnin_db,
                snapshot=snapshot,
                now=now,
                runner=runner,
            ).run_cycle(scheduled_for=now + timedelta(minutes=1))
            assert duplicate.status == "DEDUPLICATED"
            assert duplicate.duplicate_trigger is True
            assert len(runner.calls) == duplicate_calls_before

    assert duplicate_calls_before is not None
    assert len(runner.calls) == 60
    assert len({result.cycle_id for result in completed}) == 20

    # Two additional logical cycles prove explicit dependency failure without
    # contaminating the 20 successful decision cycles.
    unavailable_now = NOW + timedelta(minutes=200)
    unavailable = _burnin_service(
        burnin_db,
        snapshot=RuntimeError("Athena runtime unavailable"),
        now=unavailable_now,
        runner=runner,
    ).run_cycle(scheduled_for=unavailable_now)
    stale_now = NOW + timedelta(minutes=210)
    stale = _burnin_service(
        burnin_db,
        snapshot=_burnin_snapshot(21, now=stale_now - timedelta(minutes=10)),
        now=stale_now,
        runner=runner,
    ).run_cycle(scheduled_for=stale_now)
    assert unavailable.status == stale.status == "FAILED_CLOSED"
    assert "unavailable" in " ".join(unavailable.blocked_reasons).lower()
    assert "stale" in " ".join(stale.blocked_reasons).lower()
    assert len(runner.calls) == 60

    with burnin_db.get_session() as session:
        rows = list(
            session.execute(
                select(SingleDecisionScorecardRecord).order_by(
                    SingleDecisionScorecardRecord.decision_id
                )
            ).scalars()
        )
        cycles = list(session.execute(select(SingleBrainM2CycleRecord)).scalars())

    assert len(rows) == 60
    assert len({row.decision_id for row in rows}) == 60
    assert len(cycles) == 22
    scorecards = [SingleDecisionScorecard.from_json(row.payload_json) for row in rows]
    assert {item.investment_decision.action for item in scorecards} >= {
        "BUY",
        "ADD",
        "HOLD",
    }
    assert len({item.investment_decision.decision_cycle_id for item in scorecards}) == 20
    assert len({item.portfolio_snapshot_a.content_hash for item in scorecards}) == 20
    assert {item.portfolio_snapshot_a.revision for item in scorecards} == set(range(20))
    assert all(item.portfolio_snapshot_a.source == "ATHENA_RUNTIME" for item in scorecards)
    assert all(item.portfolio_snapshot_a.authoritative for item in scorecards)
    assert all(item.portfolio_snapshot_a.read_only for item in scorecards)
    assert all(item.execution_mandate is None for item in scorecards)
    assert all(item.execution_results == () for item in scorecards)
    assert all(item.portfolio_snapshot_b is None for item in scorecards)
    assert all(
        item.execution_diagnostics["execution_authorization"] == "OFF"
        and item.execution_diagnostics["execution_state"] == "NOT_AUTHORIZED"
        for item in scorecards
    )

    readiness = M2OperationalRepository(burnin_db).readiness()
    assert readiness["latest_cycle"]["status"] == "FAILED_CLOSED"
    assert readiness["latest_completed_cycle"]["decision_cycle_id"] == completed[-1].cycle_id
    assert len(readiness["symbols"]) == 3
    assert {item["action"] for item in readiness["symbols"]} >= {"BUY", "ADD", "HOLD"}


def test_burnin_feature_off_still_performs_zero_work(burnin_db):
    runner = _BurninAnalysisRunner()
    source = _SnapshotSource(_burnin_snapshot(0, now=NOW))
    service = _burnin_service(
        burnin_db,
        snapshot=source.snapshot,
        now=NOW,
        runner=runner,
        enabled=False,
    )
    # Replace the internally created source so its call count is directly observable.
    service._snapshot_source = source

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "DISABLED"
    assert source.calls == 0
    assert runner.calls == []
    assert M2OperationalRepository(burnin_db).readiness()["latest_cycle"] is None
