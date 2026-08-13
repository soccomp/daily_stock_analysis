"""M2 recurring shadow loop, dedupe, holdings, and recovery proofs."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.config import Config
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.m2.orchestration import (
    AnalysisCompletion,
    DSAAnalysisCompletionRunner,
    M2ShadowLoopService,
)
from src.investment.m2.identity import input_hash as build_input_hash
from src.investment.m2.repository import M2InputConflictError, M2OperationalRepository
from src.services.decision_scorecard_service import DecisionScorecardService
from src.storage import DatabaseManager
from tests.test_investment_shadow_wiring_p1a import (
    NOW,
    _analysis_result,
    _policy,
    _snapshot,
)


class _SnapshotSource:
    def __init__(self, snapshot, *, response_received_at=None, transport_elapsed_ms=None):
        self.snapshot = snapshot
        self.last_response_received_at = response_received_at
        self.last_transport_elapsed_ms = transport_elapsed_ms
        self.calls = 0

    def capture_snapshot(self):
        self.calls += 1
        snapshot = (
            self.snapshot[min(self.calls - 1, len(self.snapshot) - 1)]
            if isinstance(self.snapshot, list)
            else self.snapshot
        )
        if isinstance(snapshot, Exception):
            raise snapshot
        return snapshot


class _PolicySource:
    def __init__(self, policy):
        self.policy = policy
        self.calls = 0

    def load(self):
        self.calls += 1
        if isinstance(self.policy, Exception):
            raise self.policy
        return self.policy


class _AnalysisRunner:
    def __init__(self, *, weakening=False):
        self.calls = []
        self.weakening = weakening

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        result = _analysis_result()
        if self.weakening:
            result.dashboard["battle_plan"]["sniper_points"]["take_profit"] = 90
            result.risk_warning = "渠道库存恶化，既有研究论点正在失效。"
            result.analysis_summary = "研究证据转弱，当前不增加资本暴露。"
        return AnalysisCompletion(
            result=result,
            context_snapshot={"data_quality": {"level": "good"}},
            source_report_id=43,
            recovered=False,
        )


class _FailOnceStore:
    def __init__(self, real):
        self.real = real
        self.calls = 0

    def persist_shadow(self, artifacts):
        self.calls += 1
        if self.calls == 1:
            raise OSError("temporary sqlite failure")
        return self.real.persist_shadow(artifacts)

    def get(self, decision_id):
        return self.real.get(decision_id)


@pytest.fixture
def m2_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'm2.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _config(*, enabled=True):
    config = Config()
    config.single_brain_m2_enabled = enabled
    config.single_brain_m2_account_id = "simulation-account-1"
    config.single_brain_m2_symbols = ["600519", "600519"]
    config.single_brain_m2_max_symbols = 3
    config.single_brain_m2_holdings_limit = 3
    config.single_brain_m2_interval_minutes = 60
    return config


def _service(
    m2_db,
    *,
    enabled=True,
    snapshot=None,
    response_received_at=None,
    transport_elapsed_ms=None,
    runner=None,
    store=None,
    clock=None,
):
    snapshot_source = _SnapshotSource(
        snapshot or _snapshot(),
        response_received_at=response_received_at,
        transport_elapsed_ms=transport_elapsed_ms,
    )
    policy_source = _PolicySource(_policy())
    runner = runner or _AnalysisRunner()
    real_store = DecisionScorecardService(db_manager=m2_db)
    service = M2ShadowLoopService(
        config=_config(enabled=enabled),
        snapshot_source=snapshot_source,
        policy_source=policy_source,
        analysis_runner=runner,
        lineage_store=store or real_store,
        repository=M2OperationalRepository(m2_db),
        clock=clock or (lambda: NOW),
    )
    return service, snapshot_source, policy_source, runner, real_store


def test_default_off_performs_no_observation_analysis_or_persistence(m2_db):
    service, snapshots, policies, runner, _store = _service(m2_db, enabled=False)

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "DISABLED"
    assert snapshots.calls == policies.calls == 0
    assert runner.calls == []
    assert M2OperationalRepository(m2_db).readiness()["latest_cycle"] is None


def test_analysis_runner_uses_real_history_completion_and_recovers_it(m2_db):
    factory_calls = []
    process_calls = []

    class _Pipeline:
        def process_single_stock(self, symbol, **kwargs):
            process_calls.append((symbol, kwargs))
            result = _analysis_result()
            source_id = m2_db.save_analysis_history(
                result=result,
                query_id=kwargs["analysis_query_id"],
                report_type="simple",
                news_content="observed news",
                context_snapshot={"data_quality": {"level": "good"}},
                save_snapshot=True,
            )
            assert source_id > 0
            return result

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return _Pipeline()

    runner = DSAAnalysisCompletionRunner(
        config=_config(),
        db_manager=m2_db,
        pipeline_factory=factory,
    )
    first = runner.complete(
        cycle_id="m2-cycle-analysis-proof",
        symbol="600519",
        query_id="m2-analysis-proof",
        current_time=NOW,
    )
    second = runner.complete(
        cycle_id="m2-cycle-analysis-proof",
        symbol="600519",
        query_id="m2-analysis-proof",
        current_time=NOW,
    )

    assert len(factory_calls) == len(process_calls) == 1
    assert factory_calls[0]["investment_runtime_paths_disabled"] is True
    assert factory_calls[0]["save_context_snapshot"] is True
    assert first.source_report_id == second.source_report_id
    assert first.recovered is False
    assert second.recovered is True


def test_one_cycle_persists_stable_lineage_and_duplicate_trigger_is_noop(m2_db):
    service, snapshots, policies, runner, scorecards = _service(m2_db)

    first = service.run_cycle(scheduled_for=NOW)
    second = service.run_cycle(scheduled_for=NOW + timedelta(minutes=10))

    assert first.status == "COMPLETED"
    assert len(first.persisted_decision_ids) == 1
    assert second.status == "DEDUPLICATED"
    assert snapshots.calls == 2
    assert policies.calls == 1
    assert len(runner.calls) == 1
    payload = scorecards.get(first.persisted_decision_ids[0])["item"]
    assert payload["investment_decision"]["decision_cycle_id"] == first.cycle_id
    assert payload["investment_decision"]["decision_id"] == first.persisted_decision_ids[0]
    assert payload["execution_mandate"] is None
    assert payload["execution_results"] == []
    readiness = M2OperationalRepository(m2_db).readiness()
    assert readiness["symbols"][0]["source"] == "BOTH"
    assert readiness["latest_cycle"]["duplicate_trigger_count"] == 1


def test_response_receipt_time_replaces_pre_request_clock_and_dedupe_is_unchanged(m2_db):
    pre_request = NOW - timedelta(seconds=2)
    producer_observation = NOW + timedelta(milliseconds=60)
    clock_values = iter(
        (pre_request, NOW + timedelta(seconds=1), NOW + timedelta(minutes=10))
    )
    service, snapshots, _policies, runner, scorecards = _service(
        m2_db,
        snapshot=_snapshot(as_of=producer_observation),
        response_received_at=NOW,
        clock=lambda: next(clock_values),
    )

    first = service.run_cycle(scheduled_for=NOW)
    duplicate = service.run_cycle(scheduled_for=NOW + timedelta(minutes=10))

    assert first.status == "COMPLETED"
    assert duplicate.status == "DEDUPLICATED"
    assert snapshots.calls == 2
    assert len(runner.calls) == 1
    assert scorecards.get(first.persisted_decision_ids[0])["item"][
        "portfolio_snapshot_a"
    ]["as_of"] == "2026-08-08T02:00:00.060000Z"


@pytest.mark.parametrize(
    "producer_offset",
    (
        timedelta(milliseconds=60),
        timedelta(microseconds=999_999),
        timedelta(seconds=1),
    ),
)
def test_bounded_cross_host_snapshot_clock_skew_is_accepted(
    m2_db,
    producer_offset,
):
    service, _snapshots, _policies, runner, _store = _service(
        m2_db,
        snapshot=_snapshot(as_of=NOW + producer_offset),
        response_received_at=NOW,
        clock=lambda: NOW,
    )

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "COMPLETED"
    assert len(runner.calls) == 1


def test_ingress_accepted_final_snapshot_skew_reaches_one_deterministic_decision(m2_db):
    initial = _snapshot(as_of=NOW)
    final = _snapshot(as_of=NOW + timedelta(milliseconds=93))
    canonical_json = final.canonical_json()
    content_hash = final.content_hash
    service, _snapshots, _policies, runner, scorecards = _service(
        m2_db,
        snapshot=[initial, final],
        response_received_at=NOW,
        clock=lambda: NOW,
    )

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "COMPLETED"
    assert len(runner.calls) == len(result.persisted_decision_ids) == 1
    item = scorecards.get(result.persisted_decision_ids[0])["item"]
    assert item["portfolio_snapshot_a"]["content_hash"] == content_hash
    assert item["execution_mandate"] is None
    assert final.canonical_json() == canonical_json
    assert final.content_hash == content_hash


def test_230ms_snapshot_skew_is_accepted_and_persisted_as_sanitized_evidence(m2_db):
    clock_values = iter((NOW, NOW + timedelta(seconds=1)))
    service, _snapshots, _policies, runner, _store = _service(
        m2_db,
        snapshot=_snapshot(as_of=NOW + timedelta(milliseconds=230)),
        response_received_at=NOW,
        transport_elapsed_ms=23.5,
        clock=lambda: next(clock_values),
    )

    result = service.run_cycle(scheduled_for=NOW)
    evidence = M2OperationalRepository(m2_db).readiness()["snapshot_clock_diagnostics"]

    assert result.status == "COMPLETED"
    assert len(runner.calls) == 1
    assert [item["future_offset_ms"] for item in evidence] == ["230", "230"]
    assert [item["transport_elapsed_ms"] for item in evidence] == ["23.5", "23.5"]
    assert [item["validation_result"] for item in evidence] == ["accepted", "accepted"]


def test_snapshot_beyond_cross_host_clock_skew_budget_fails_closed(m2_db):
    service, _snapshots, _policies, runner, _store = _service(
        m2_db,
        snapshot=_snapshot(as_of=NOW + timedelta(seconds=1, microseconds=1)),
        response_received_at=NOW,
        clock=lambda: NOW,
    )

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "FAILED_CLOSED"
    assert "future-dated" in " ".join(result.blocked_reasons)
    assert runner.calls == []


def test_future_dated_snapshot_persists_exact_sanitized_clock_evidence(m2_db):
    offset = timedelta(seconds=1, microseconds=1)
    service, _snapshots, _policies, runner, _store = _service(
        m2_db,
        snapshot=_snapshot(as_of=NOW + offset),
        response_received_at=NOW,
        clock=lambda: NOW,
    )

    result = service.run_cycle(scheduled_for=NOW)
    evidence = M2OperationalRepository(m2_db).readiness()["snapshot_clock_diagnostics"]

    assert result.status == "FAILED_CLOSED"
    assert runner.calls == []
    assert len(evidence) == 1
    assert evidence[0] == {
        "cycle_id": result.cycle_id,
        "stage": "initial",
        "snapshot_revision": 1,
        "as_of": "2026-08-08T02:00:01.000001Z",
        "created_at": "2026-08-08T02:00:01.000001Z",
        "last_response_received_at": "2026-08-08T02:00:00Z",
        "future_offset_ms": "1000.001",
        "transport_elapsed_ms": None,
        "validation_result": "future-dated",
    }


def test_post_research_final_refresh_persists_future_dated_evidence(m2_db):
    initial = _snapshot(as_of=NOW)
    final = _snapshot(as_of=NOW + timedelta(seconds=1, microseconds=1))
    service, _snapshots, _policies, runner, _store = _service(
        m2_db,
        snapshot=[initial, final],
        response_received_at=NOW,
        clock=lambda: NOW,
    )

    result = service.run_cycle(scheduled_for=NOW)
    evidence = M2OperationalRepository(m2_db).readiness()["snapshot_clock_diagnostics"]

    assert result.status == "FAILED_CLOSED"
    assert len(runner.calls) == 1
    assert [item["stage"] for item in evidence] == [
        "initial",
        "post-research-final-refresh",
    ]
    assert [item["validation_result"] for item in evidence] == [
        "accepted",
        "future-dated",
    ]
    assert evidence[-1]["future_offset_ms"] == "1000.001"


def test_clock_diagnostic_write_failure_cannot_change_fail_closed_behavior(m2_db, monkeypatch):
    service, _snapshots, _policies, runner, _store = _service(
        m2_db,
        snapshot=_snapshot(as_of=NOW + timedelta(seconds=1, microseconds=1)),
        response_received_at=NOW,
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        service._repository,
        "record_snapshot_clock_diagnostic",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("audit store unavailable")),
    )

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "FAILED_CLOSED"
    assert "future-dated" in " ".join(result.blocked_reasons)
    assert runner.calls == []
    assert M2OperationalRepository(m2_db).readiness()["snapshot_clock_diagnostics"] == ()


def test_timezone_naive_authoritative_snapshot_is_rejected_by_contract():
    with pytest.raises(ValidationError, match="timezone"):
        PortfolioSnapshot.build(
            **{
                **_snapshot().model_dump(
                    exclude={"content_hash", "as_of", "created_at"}
                ),
                "as_of": datetime(2026, 8, 8, 2, 0),
                "created_at": datetime(2026, 8, 8, 2, 0),
            }
        )


@pytest.mark.parametrize(
    "snapshot",
    (
        _snapshot(as_of=NOW - timedelta(minutes=6)),
        _snapshot(as_of=NOW + timedelta(seconds=1, microseconds=1)),
        PortfolioSnapshot.build(
            **{
                **_snapshot().model_dump(exclude={"content_hash", "reconciliation_status"}),
                "reconciliation_status": "DEGRADED",
            }
        ),
    ),
)
def test_invalid_authoritative_snapshot_fails_before_analysis(m2_db, snapshot):
    service, _snapshots, _policies, runner, _store = _service(m2_db, snapshot=snapshot)

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "FAILED_CLOSED"
    assert runner.calls == []
    assert not result.persisted_decision_ids


def test_restart_after_persistence_failure_reuses_immutable_authority_mirror(m2_db):
    real = DecisionScorecardService(db_manager=m2_db)
    fail_once = _FailOnceStore(real)
    service, snapshots, policies, runner, _store = _service(
        m2_db,
        store=fail_once,
    )

    failed = service.run_cycle(scheduled_for=NOW)
    recovered = service.run_cycle(scheduled_for=NOW + timedelta(minutes=5))

    assert failed.status == "FAILED_CLOSED"
    assert recovered.status == "COMPLETED"
    assert snapshots.calls == 3
    assert policies.calls == 2
    assert len(recovered.persisted_decision_ids) == 1
    assert recovered.duplicate_trigger is True


def test_restart_fails_closed_when_explicit_policy_changes_inside_cycle(m2_db):
    real = DecisionScorecardService(db_manager=m2_db)
    fail_once = _FailOnceStore(real)
    service, snapshots, policies, _runner, _store = _service(
        m2_db,
        store=fail_once,
    )

    failed = service.run_cycle(scheduled_for=NOW)
    base_policy = _policy()
    policies.policy = type(base_policy).build(
        **base_policy.model_dump(
            exclude={"content_hash", "risk_budget_per_trade"}
        ),
        risk_budget_per_trade=Decimal("0.009000"),
    )
    conflicted = service.run_cycle(scheduled_for=NOW + timedelta(minutes=1))

    assert failed.status == "FAILED_CLOSED"
    assert conflicted.status == "FAILED_CLOSED"
    assert "RiskPolicy changed" in " ".join(conflicted.blocked_reasons)
    assert snapshots.calls == 2
    assert policies.calls == 2
    assert not conflicted.persisted_decision_ids


def test_authority_becoming_stale_during_analysis_blocks_before_decision(m2_db):
    clock_values = iter((NOW, NOW, NOW + timedelta(minutes=6)))
    service, _snapshots, _policies, _runner, _store = _service(
        m2_db,
        clock=lambda: next(clock_values),
    )

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "FAILED_CLOSED"
    assert "stale" in " ".join(result.blocked_reasons)
    assert not result.persisted_decision_ids


def test_weakening_holding_evidence_produces_nonexecuting_hold(m2_db):
    runner = _AnalysisRunner(weakening=True)
    service, _snapshots, _policies, _runner, scorecards = _service(
        m2_db,
        runner=runner,
    )

    result = service.run_cycle(scheduled_for=NOW)

    payload = scorecards.get(result.persisted_decision_ids[0])["item"]
    decision = payload["investment_decision"]
    assert decision["action"] == "HOLD"
    assert decision["delta_quantity"] == 0
    assert "weakening evidence" in decision["rationale"]
    assert "渠道库存恶化" in payload["research_bundle"]["bear_case"]
    assert payload["execution_mandate"] is None


def test_same_policy_identity_with_different_content_hash_conflicts(m2_db):
    repository = M2OperationalRepository(m2_db)
    service, _snapshots, _policies, _runner, _store = _service(m2_db)
    result = service.run_cycle(scheduled_for=NOW)
    mirror = repository.load_authority_mirror(result.cycle_id)
    assert mirror is not None
    base_policy = _policy()
    changed = type(base_policy).build(
        **base_policy.model_dump(
            exclude={"content_hash", "risk_budget_per_trade"}
        ),
        risk_budget_per_trade=Decimal("0.009000"),
    )

    with pytest.raises(M2InputConflictError):
        repository.bind_authority_inputs(
            cycle_id=result.cycle_id,
            input_hash=build_input_hash(
                snapshot_hash=_snapshot().content_hash,
                policy_id=changed.policy_id,
                policy_version=changed.policy_version,
                policy_hash=changed.content_hash,
            ),
            snapshot_id=_snapshot().snapshot_id,
            snapshot_hash=_snapshot().content_hash,
            snapshot_json=_snapshot().canonical_json(),
            snapshot_as_of=_snapshot().as_of,
            reconciliation_status="RECONCILED",
            risk_policy_id=changed.policy_id,
            risk_policy_version=changed.policy_version,
            risk_policy_hash=changed.content_hash,
            risk_policy_json=changed.canonical_json(),
            symbols=[{"symbol": "600519", "source": "BOTH"}],
        )


def test_readiness_keeps_latest_completed_cycle_and_authoritative_snapshot(m2_db):
    completed_service, _snapshots, _policies, _runner, _store = _service(m2_db)
    completed = completed_service.run_cycle(scheduled_for=NOW)

    later = NOW + timedelta(hours=1)
    failed_service, _snapshots, _policies, _runner, _store = _service(
        m2_db,
        snapshot=RuntimeError("Athena unavailable"),
        clock=lambda: later,
    )
    failed = failed_service.run_cycle(scheduled_for=later)

    repository = M2OperationalRepository(m2_db)
    readiness = repository.readiness()
    latest_snapshot = repository.latest_authoritative_snapshot()
    assert failed.status == "FAILED_CLOSED"
    assert readiness["latest_cycle"]["decision_cycle_id"] == failed.cycle_id
    assert readiness["latest_completed_cycle"]["decision_cycle_id"] == completed.cycle_id
    assert readiness["symbols"][0]["decision_id"] in completed.persisted_decision_ids
    assert latest_snapshot is not None
    assert latest_snapshot.snapshot_id == _snapshot().snapshot_id
