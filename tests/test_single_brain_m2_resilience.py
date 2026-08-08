"""M2 restart, bounded-attempt, and authority failure proofs."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.m2.orchestration import M2ShadowLoopService
from src.investment.m2.repository import M2OperationalRepository
from src.services.decision_scorecard_service import DecisionScorecardService
from src.storage import DatabaseManager
from tests.test_investment_shadow_wiring_p1a import NOW, _policy, _snapshot
from tests.test_single_brain_m2_shadow_loop import (
    _AnalysisRunner,
    _PolicySource,
    _SnapshotSource,
    _config,
)


class _CloseFailOnceRepository:
    def __init__(self, real: M2OperationalRepository) -> None:
        self.real = real
        self.close_calls = 0

    def __getattr__(self, name):
        return getattr(self.real, name)

    def close_cycle(self, *, cycle_id: str) -> str:
        self.close_calls += 1
        if self.close_calls == 1:
            raise OSError("transient closeout write failure")
        return self.real.close_cycle(cycle_id=cycle_id)


class _ClaimFailRepository:
    def claim_cycle(self, **_kwargs):
        raise OSError("sqlite unavailable")


@pytest.fixture
def m2_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'm2-resilience.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _build_service(
    m2_db,
    *,
    snapshot=None,
    policy=None,
    repository=None,
    runner=None,
    store=None,
    clock=lambda: NOW,
):
    return M2ShadowLoopService(
        config=_config(),
        snapshot_source=_SnapshotSource(snapshot or _snapshot()),
        policy_source=_PolicySource(policy or _policy()),
        analysis_runner=runner or _AnalysisRunner(),
        lineage_store=store or DecisionScorecardService(db_manager=m2_db),
        repository=repository or M2OperationalRepository(m2_db),
        clock=clock,
    )


def test_restart_after_scorecard_before_cycle_closeout_does_not_reanalyze_or_rewrite(m2_db):
    real_repository = M2OperationalRepository(m2_db)
    failing_repository = _CloseFailOnceRepository(real_repository)
    first_runner = _AnalysisRunner()
    scorecards = DecisionScorecardService(db_manager=m2_db)
    first_service = _build_service(
        m2_db,
        repository=failing_repository,
        runner=first_runner,
        store=scorecards,
    )

    interrupted = first_service.run_cycle(scheduled_for=NOW)
    assert interrupted.status == "FAILED_CLOSED"
    assert len(interrupted.persisted_decision_ids) == 1
    decision_id = interrupted.persisted_decision_ids[0]
    original = scorecards.get(decision_id)["item"]

    second_runner = _AnalysisRunner()
    recovered = _build_service(
        m2_db,
        repository=real_repository,
        runner=second_runner,
        store=scorecards,
    ).run_cycle(scheduled_for=NOW + timedelta(minutes=1))

    assert recovered.status == "COMPLETED"
    assert recovered.duplicate_trigger is True
    assert recovered.persisted_decision_ids == (decision_id,)
    assert second_runner.calls == []
    assert scorecards.get(decision_id)["item"] == original


def test_cycle_claim_storage_failure_is_one_safe_attempt_with_no_analysis(m2_db):
    runner = _AnalysisRunner()
    service = _build_service(
        m2_db,
        repository=_ClaimFailRepository(),
        runner=runner,
    )

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "FAILED_CLOSED"
    assert "sqlite unavailable" in " ".join(result.blocked_reasons)
    assert runner.calls == []


@pytest.mark.parametrize(
    ("snapshot", "policy", "expected"),
    (
        (RuntimeError("Athena unavailable"), None, "Athena unavailable"),
        (
            PortfolioSnapshot.build(
                **{
                    **_snapshot().model_dump(exclude={"content_hash", "account_id"}),
                    "account_id": "another-account",
                }
            ),
            None,
            "account mismatch",
        ),
        (
            None,
            _policy(
                effective_from=NOW - timedelta(days=2),
                effective_until=NOW - timedelta(days=1),
            ),
            "not currently effective",
        ),
        (None, RuntimeError("RiskPolicy missing"), "RiskPolicy missing"),
    ),
)
def test_authority_and_policy_failures_produce_no_actionable_lineage(
    m2_db,
    snapshot,
    policy,
    expected,
):
    runner = _AnalysisRunner()
    service = _build_service(
        m2_db,
        snapshot=snapshot,
        policy=policy,
        runner=runner,
    )

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "FAILED_CLOSED"
    assert expected in " ".join(result.blocked_reasons)
    assert result.persisted_decision_ids == ()
    assert runner.calls == []


def test_recovered_persisted_symbol_is_not_processed_twice_in_same_cycle(m2_db):
    service = _build_service(m2_db)
    first = service.run_cycle(scheduled_for=NOW)

    repository = M2OperationalRepository(m2_db)
    # Simulate a process stopping after all symbol writes but before the durable
    # cycle state was observed by its caller.
    repository.fail_cycle(cycle_id=first.cycle_id, reason="synthetic restart boundary")
    second_runner = _AnalysisRunner()
    second = _build_service(m2_db, runner=second_runner).run_cycle(
        scheduled_for=NOW + timedelta(minutes=2)
    )

    assert second.status == "COMPLETED"
    assert second.persisted_decision_ids == first.persisted_decision_ids
    assert second_runner.calls == []
