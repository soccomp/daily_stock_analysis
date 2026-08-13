"""M2 repeatedly researches real holdings without reduction execution authority."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.m2.orchestration import AnalysisCompletion, M2ShadowLoopService
from src.investment.m2.repository import M2OperationalRepository
from src.services.decision_scorecard_service import DecisionScorecardService
from src.storage import DatabaseManager
from tests.test_investment_shadow_wiring_p1a import NOW, _analysis_result, _policy, _snapshot
from tests.test_single_brain_m2_shadow_loop import _PolicySource, _SnapshotSource, _config


@pytest.fixture
def m2_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'm2-holdings.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _runtime_snapshot(*, suffix: str, as_of, revision: int, supersedes_id=None):
    base = _snapshot(as_of=as_of)
    return PortfolioSnapshot.build(
        **{
            **base.model_dump(
                exclude={
                    "content_hash",
                    "snapshot_id",
                    "trace_id",
                    "revision",
                    "broker_snapshot_ref",
                    "supersedes_id",
                }
            ),
            "snapshot_id": f"snapshot-m2-holdings-{suffix}",
            "trace_id": f"athena-runtime-holdings-{suffix}",
            "revision": revision,
            "supersedes_id": supersedes_id,
            "broker_snapshot_ref": f"athena-sim:m2-holdings-{suffix}",
        }
    )


class _ChangingHoldingResearch:
    def __init__(self) -> None:
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        result = _analysis_result()
        if len(self.calls) == 2:
            result.action = "watch"
            result.operation_advice = "观望"
            result.dashboard["battle_plan"]["sniper_points"]["take_profit"] = 90
            result.company_highlights = "品牌仍有长期价值，但短期催化剂已经消退。"
            result.risk_warning = "渠道库存恶化，需求转弱使原有论点失效。"
            result.analysis_summary = "证据转弱；在 BUY/ADD/HOLD 范围内不增加暴露。"
        return AnalysisCompletion(
            result=result,
            context_snapshot={"data_quality": {"level": "good"}},
            source_report_id=800 + len(self.calls),
            recovered=False,
        )


def _service(m2_db, *, snapshot, now, runner):
    config = _config()
    # 600519 is intentionally absent: it must enter through the observed holding.
    config.single_brain_m2_symbols = ["000001"]
    config.single_brain_m2_max_symbols = 1
    return M2ShadowLoopService(
        config=config,
        snapshot_source=_SnapshotSource(snapshot),
        policy_source=_PolicySource(_policy()),
        analysis_runner=runner,
        lineage_store=DecisionScorecardService(db_manager=m2_db),
        repository=M2OperationalRepository(m2_db),
        clock=lambda: now,
    )


def test_existing_holding_is_researched_again_and_weakening_thesis_stays_hold(m2_db):
    runner = _ChangingHoldingResearch()
    first_snapshot = _runtime_snapshot(
        suffix="a",
        as_of=NOW - timedelta(minutes=1),
        revision=10,
    )
    first = _service(
        m2_db,
        snapshot=first_snapshot,
        now=NOW,
        runner=runner,
    ).run_cycle(scheduled_for=NOW)

    later = NOW + timedelta(hours=1)
    second_snapshot = _runtime_snapshot(
        suffix="b",
        as_of=later - timedelta(minutes=1),
        revision=11,
        supersedes_id=first_snapshot.snapshot_id,
    )
    second = _service(
        m2_db,
        snapshot=second_snapshot,
        now=later,
        runner=runner,
    ).run_cycle(scheduled_for=later)

    assert first.status == second.status == "COMPLETED"
    assert len(runner.calls) == 2
    assert {call["symbol"] for call in runner.calls} == {"600519"}

    scorecards = DecisionScorecardService(db_manager=m2_db)
    first_item = scorecards.get(first.persisted_decision_ids[0])["item"]
    second_item = scorecards.get(second.persisted_decision_ids[0])["item"]
    assert first_item["investment_decision"]["action"] == "ADD"
    assert second_item["investment_decision"]["action"] == "HOLD"
    assert second_item["investment_decision"]["delta_quantity"] == 0
    assert (
        second_item["investment_decision"]["target_quantity"]
        == second_item["investment_decision"]["current_quantity"]
    )
    assert first_item["research_bundle"]["research_id"] != second_item["research_bundle"]["research_id"]
    assert first_item["research_bundle"]["content_hash"] != second_item["research_bundle"]["content_hash"]
    assert first_item["investment_decision"]["decision_id"] != second_item["investment_decision"]["decision_id"]
    assert any(
        "渠道库存恶化" in factor
        for factor in second_item["research_bundle"]["risk_factors"]
    )
    assert second_item["research_bundle"]["invalidation_conditions"]
    assert second_item["research_bundle"]["catalysts"]
    assert "weakening evidence" in second_item["investment_decision"]["rationale"]
    assert second_item["execution_mandate"] is None
    assert second_item["execution_results"] == []
    assert second_item["portfolio_snapshot_b"] is None
    assert second_item["execution_diagnostics"]["execution_authorization"] == "OFF"
    assert M2OperationalRepository(m2_db).readiness()["symbols"][0]["source"] == "HOLDING"
