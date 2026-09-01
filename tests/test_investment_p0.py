"""Focused contract and Single-Brain tests for the DSA/Athena P0 slice."""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from api.v1.schemas.decision_signals import DecisionSignalCreateRequest
from src.investment.contracts import (
    ExecutionMandate,
    ExecutionResult,
    InvestmentDecision,
    PortfolioSnapshot,
    ResearchBundle,
    RiskPolicy,
)
from src.investment.contracts.base import CanonicalContract
from src.investment.contracts.execution_result import SafetyCheck
from src.investment.contracts.investment_decision import (
    EntryPlan,
    StopPlan,
    TakeProfitPlan,
)
from src.investment.contracts.portfolio_snapshot import Position
from src.investment.contracts.research_bundle import (
    ExpectedReturnRange,
    ModelProvenance,
)
from src.investment.decision import DecisionSizingInput, InvestmentDecisionEngine
from src.investment.execution_projection import (
    DecisionSignalProjector,
    ExecutionMandateProjector,
)
from src.investment.research import ResearchBundleAdapter


NOW = datetime(2026, 8, 8, 1, 0, tzinfo=timezone.utc)


def _provenance() -> tuple[ModelProvenance, ...]:
    return (
        ModelProvenance(
            model_name="dsa-research-synthesis",
            model_version="p0-v1",
            provider="DSA",
            prompt_hash="a" * 64,
        ),
    )


def _research(**overrides) -> ResearchBundle:
    values = {
        "research_id": "research-600519-20260808",
        "trace_id": "research-trace-p0",
        "created_at": NOW,
        "producer": "DSA_RESEARCH",
        "symbol": "600519",
        "market": "CN",
        "as_of": NOW,
        "horizon": "swing",
        "trigger_source": "daily_analysis",
        "market_regime": "constructive",
        "industry_view": "positive",
        "fundamental_view": "positive",
        "technical_view": "positive",
        "valuation_view": "neutral",
        "intel_view": "positive",
        "capital_flow_view": "neutral",
        "bull_case": "Demand and margins improve.",
        "base_case": "Earnings remain resilient.",
        "bear_case": "Demand weakens.",
        "expected_return_range": ExpectedReturnRange(
            minimum=Decimal("0.100000"),
            maximum=Decimal("0.200000"),
        ),
        "catalysts": ("earnings",),
        "risk_factors": ("demand slowdown",),
        "invalidation_conditions": ("close below stop",),
        "evidence_refs": ("analysis:600519:20260808",),
        "data_quality": "HIGH",
        "confidence": Decimal("0.840000"),
        "model_provenance": _provenance(),
        "strategy_refs": ("p0-single-stock",),
    }
    values.update(overrides)
    return ResearchBundle.build(**values)


def _snapshot(**overrides) -> PortfolioSnapshot:
    position = Position(
        symbol="600519",
        market="CN",
        quantity=300,
        available_quantity=300,
        avg_cost=Decimal("90.00"),
        last_price=Decimal("100.00"),
        market_value=Decimal("30000.00"),
        unrealized_pnl=Decimal("3000.00"),
        price_as_of=NOW,
        price_source="ATHENA_SIM_RUNTIME",
    )
    values = {
        "snapshot_id": "snapshot-a",
        "trace_id": "snapshot-trace-p0",
        "created_at": NOW,
        "producer": "ATHENA_SIMULATION_RECONCILIATION",
        "account_id": "simulation-account-1",
        "broker": "ATHENA_LOCAL_SIM",
        "account_mode": "SIMULATION",
        "as_of": NOW,
        "revision": 1,
        "currency": "CNY",
        "equity": Decimal("1000000.00"),
        "cash": Decimal("400000.00"),
        "available_cash": Decimal("400000.00"),
        "reserved_cash": Decimal("0.00"),
        "positions": (position,),
        "active_orders": (),
        "realized_pnl": Decimal("0.00"),
        "unrealized_pnl": Decimal("3000.00"),
        "reconciliation_status": "RECONCILED",
        "data_quality": "HIGH",
        "limitations": (),
        "broker_snapshot_ref": "athena-sim:snapshot-a",
    }
    values.update(overrides)
    return PortfolioSnapshot.build(**values)


def _policy(**overrides) -> RiskPolicy:
    values = {
        "policy_id": "risk-policy-p0",
        "policy_version": "1.0.0",
        "trace_id": "policy-provenance-trace",
        "created_at": NOW,
        "producer": "OWNER_POLICY",
        "account_scope": ("simulation-account-1",),
        "effective_from": NOW - timedelta(days=1),
        "max_single_position_weight": Decimal("0.150000"),
        "max_total_exposure": Decimal("0.900000"),
        "min_cash_weight": Decimal("0.100000"),
        "risk_budget_per_trade": Decimal("0.010000"),
        "max_concurrent_positions": 10,
        "min_data_quality": "MEDIUM",
        "allowed_markets": ("CN",),
        "allowed_instruments": ("EQUITY",),
        "position_sizing_method": "TARGET_WEIGHT",
        "stop_required": True,
    }
    values.update(overrides)
    return RiskPolicy.build(**values)


def _sizing(**overrides) -> DecisionSizingInput:
    values = {
        "decision_id": "decision-p0-1",
        "decision_cycle_id": "decision-cycle-p0-1",
        "created_at": NOW,
        "valid_from": NOW,
        "valid_until": NOW + timedelta(hours=2),
        "proposed_target_weight": Decimal("0.050000"),
        "lot_size": 100,
        "entry_plan": EntryPlan(
            limit_price=Decimal("100.00"),
            price_floor=Decimal("95.00"),
            price_ceiling=Decimal("100.00"),
        ),
        "stop_plan": StopPlan(stop_price=Decimal("50.00")),
        "take_profit_plan": TakeProfitPlan(target_price=Decimal("130.00")),
        "rationale": "Positive research supports a policy-constrained add.",
        "horizon": "swing",
    }
    values.update(overrides)
    return DecisionSizingInput(**values)


def _decision(
    *,
    research: ResearchBundle | None = None,
    snapshot: PortfolioSnapshot | None = None,
    policy: RiskPolicy | None = None,
    sizing: DecisionSizingInput | None = None,
) -> InvestmentDecision:
    return InvestmentDecisionEngine().decide(
        research=research or _research(),
        portfolio=snapshot or _snapshot(),
        risk_policy=policy or _policy(),
        sizing=sizing or _sizing(),
    )


def _blocked_result(
    *,
    decision: InvestmentDecision,
    mandate: ExecutionMandate,
) -> ExecutionResult:
    return ExecutionResult.build(
        result_id="result-blocked",
        mandate_id=mandate.mandate_id,
        mandate_hash=mandate.content_hash,
        decision_id=decision.decision_id,
        decision_hash=decision.content_hash,
        trace_id=decision.trace_id,
        created_at=NOW,
        producer="ATHENA_EXECUTION_SPINE",
        attempt_no=1,
        account_id=decision.account_id,
        symbol=decision.symbol,
        status="BLOCKED",
        requested_quantity=mandate.quantity,
        submitted_quantity=0,
        filled_quantity=0,
        remaining_quantity=mandate.quantity,
        requested_limit_price=mandate.limit_price,
        fees=Decimal("0.00"),
        correlation_id="correlation-blocked",
        safety_checks=(
            SafetyCheck(
                check="portfolio_snapshot",
                status="BLOCKED",
                reason="PORTFOLIO_SNAPSHOT_STALE",
            ),
        ),
        block_reason="PORTFOLIO_SNAPSHOT_STALE",
        last_update_at=NOW,
        reconciliation_status="NOT_REQUIRED",
    )


def _build_values(contract, **changes):
    values = contract.model_dump(mode="python", exclude={"content_hash"})
    values.update(changes)
    return values


def test_six_canonical_contracts_are_distinct_and_versioned() -> None:
    research = _research()
    snapshot = _snapshot()
    policy = _policy()
    decision = _decision(research=research, snapshot=snapshot, policy=policy)
    mandate = ExecutionMandateProjector.project(decision)
    result = _blocked_result(decision=decision, mandate=mandate)
    contract_types = (
        type(research),
        type(snapshot),
        type(policy),
        type(decision),
        type(mandate),
        type(result),
    )
    assert len(set(contract_types)) == 6
    assert all(issubclass(contract_type, CanonicalContract) for contract_type in contract_types)
    contracts = (research, snapshot, policy, decision, mandate, result)
    assert {contract.schema_version for contract in contracts} == {"1.0"}
    for contract in contracts:
        assert type(contract).model_validate_json(contract.canonical_json()) == contract


def test_contract_requires_timezone_aware_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ResearchBundle.build(
            **_build_values(_research(), as_of=datetime(2026, 8, 8, 1, 0))
        )


def test_decimal_wire_format_and_content_hash_are_stable() -> None:
    first = _snapshot()
    second = _snapshot()
    payload = json.loads(first.canonical_json())

    assert first.content_hash == second.content_hash
    assert first.canonical_json() == second.canonical_json()
    assert payload["equity"] == "1000000.00"
    assert payload["positions"][0]["avg_cost"] == "90.00"
    assert isinstance(payload["equity"], str)
    assert PortfolioSnapshot.model_validate_json(first.canonical_json()) == first


def test_dsa_consumes_an_athena_authoritative_snapshot_as_a_read_only_wire_fact() -> None:
    athena_wire = _snapshot().canonical_json()
    consumed = PortfolioSnapshot.model_validate_json(athena_wire)

    assert consumed.source == "ATHENA_RUNTIME"
    assert consumed.authoritative is True
    assert consumed.read_only is True
    assert consumed.simulation_only is True
    assert consumed.account_mode == "SIMULATION"
    assert consumed.position_for(symbol="600519", market="CN").quantity == 300


def test_position_lookup_matches_exchange_qualified_cn_symbols_without_rewriting_wire_data() -> None:
    sh_position = Position(
        symbol="SHSE.600519",
        market="CN",
        quantity=300,
        available_quantity=300,
        avg_cost=Decimal("90.00"),
        last_price=Decimal("100.00"),
        market_value=Decimal("30000.00"),
        unrealized_pnl=Decimal("3000.00"),
        price_as_of=NOW,
        price_source="ATHENA_SIM_RUNTIME",
    )
    sz_position = Position(
        symbol="SZSE.000001",
        market="CN",
        quantity=100,
        available_quantity=100,
        avg_cost=Decimal("10.00"),
        last_price=Decimal("11.00"),
        market_value=Decimal("1100.00"),
        unrealized_pnl=Decimal("100.00"),
        price_as_of=NOW,
        price_source="ATHENA_SIM_RUNTIME",
    )
    snapshot = _snapshot(positions=(sh_position, sz_position))

    assert snapshot.positions[0].symbol == "SHSE.600519"
    assert snapshot.position_for(symbol="600519", market="CN").quantity == 300
    assert snapshot.position_for(symbol="SH.600519", market="cn").quantity == 300
    assert snapshot.position_for(symbol="600519.SH", market="CN").quantity == 300
    assert snapshot.position_for(symbol="SH600519", market="CN").quantity == 300
    assert snapshot.position_for(symbol="000001", market="CN").quantity == 100
    assert snapshot.position_for(symbol="SZ.000001", market="CN").quantity == 100
    assert snapshot.position_for(symbol="000001.SZ", market="CN").quantity == 100


def test_binary_float_is_not_a_canonical_decimal_input() -> None:
    with pytest.raises(ValidationError, match="Decimal or decimal string"):
        ExpectedReturnRange(minimum=0.1, maximum=Decimal("0.2"))


def test_consumer_requires_and_verifies_content_hash() -> None:
    research = _research()
    missing_hash = research.model_dump(mode="python", exclude={"content_hash"})
    with pytest.raises(ValidationError, match="content_hash"):
        ResearchBundle.model_validate(missing_hash)

    tampered = research.model_dump(mode="python")
    tampered["base_case"] = "Tampered after publication."
    with pytest.raises(ValidationError, match="content_hash does not match"):
        ResearchBundle.model_validate(tampered)


def test_consumer_does_not_fill_a_missing_critical_wire_field() -> None:
    payload = _snapshot().model_dump(mode="python")
    payload.pop("simulation_only")
    with pytest.raises(ValidationError, match="simulation_only"):
        PortfolioSnapshot.model_validate(payload)


def test_strict_wire_rejects_integer_strings_and_integer_booleans() -> None:
    string_quantity = json.loads(_snapshot().canonical_json())
    string_quantity["positions"][0]["quantity"] = "300"
    with pytest.raises(ValidationError, match="quantity"):
        PortfolioSnapshot.model_validate_json(json.dumps(string_quantity))

    integer_boolean = json.loads(_snapshot().canonical_json())
    integer_boolean["authoritative"] = 1
    with pytest.raises(ValidationError, match="authoritative"):
        PortfolioSnapshot.model_validate_json(json.dumps(integer_boolean))


def test_canonical_json_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="duplicate canonical JSON key: schema_version"):
        PortfolioSnapshot.model_validate_json(
            '{"schema_version":"1.0","schema_version":"1.0"}'
        )


def test_contracts_are_deeply_immutable_and_copy_updates_are_forbidden() -> None:
    research = _research()
    with pytest.raises(ValidationError, match="frozen"):
        research.confidence = Decimal("0.1")
    with pytest.raises(TypeError, match="cannot be copied"):
        research.model_copy(update={"confidence": Decimal("0.1")})
    with pytest.raises(TypeError):
        research.risk_factors[0] = "changed"


def test_invalid_enum_is_rejected() -> None:
    with pytest.raises(ValidationError, match="account_mode"):
        PortfolioSnapshot.build(**_build_values(_snapshot(), account_mode="SANDBOX"))


def test_research_adapter_is_deterministic_and_has_no_allocation_fields() -> None:
    kwargs = {
        "research_id": "research-adapter-1",
        "trace_id": "research-adapter-trace",
        "created_at": NOW,
        "producer": "DSA_RESEARCH_ADAPTER",
        "symbol": "600519",
        "market": "cn",
        "as_of": NOW,
        "horizon": "swing",
        "trigger_source": "daily_analysis",
        "market_regime": "constructive",
        "industry_view": "positive",
        "fundamental_view": "positive",
        "technical_view": "positive",
        "valuation_view": "neutral",
        "intel_view": "neutral",
        "capital_flow_view": "positive",
        "bull_case": "up",
        "base_case": "stable",
        "bear_case": "down",
        "expected_return_minimum": Decimal("0.10"),
        "expected_return_maximum": Decimal("0.20"),
        "catalysts": ("earnings",),
        "risk_factors": ("demand",),
        "invalidation_conditions": ("breakdown",),
        "evidence_refs": ("evidence:1",),
        "data_quality": "HIGH",
        "confidence": Decimal("0.84"),
        "model_provenance": _provenance(),
    }
    first = ResearchBundleAdapter.from_dsa_views(**kwargs)
    second = ResearchBundleAdapter.from_dsa_views(**kwargs)
    assert first == second
    assert first.market == "CN"
    assert first.content_hash == second.content_hash
    assert {"target_quantity", "delta_quantity", "quantity", "action"}.isdisjoint(
        ResearchBundle.model_fields
    )


def test_brain_produces_final_add_200_with_exact_lineage() -> None:
    research = _research()
    snapshot = _snapshot()
    policy = _policy()
    decision = _decision(research=research, snapshot=snapshot, policy=policy)

    assert decision.action == "ADD"
    assert decision.current_quantity == 300
    assert decision.target_quantity == 500
    assert decision.delta_quantity == 200
    assert decision.target_weight == Decimal("0.050000")
    assert decision.research_ids == (research.research_id,)
    assert decision.portfolio_snapshot_id == snapshot.snapshot_id
    assert decision.portfolio_snapshot_hash == snapshot.content_hash
    assert decision.risk_policy_id == policy.policy_id
    assert decision.risk_policy_version == policy.policy_version
    assert decision.trace_id == research.trace_id


def test_brain_treats_exchange_qualified_position_as_existing_for_add() -> None:
    position = Position(
        symbol="SHSE.600519",
        market="CN",
        quantity=300,
        available_quantity=300,
        avg_cost=Decimal("90.00"),
        last_price=Decimal("100.00"),
        market_value=Decimal("30000.00"),
        unrealized_pnl=Decimal("3000.00"),
        price_as_of=NOW,
        price_source="ATHENA_SIM_RUNTIME",
    )

    decision = _decision(snapshot=_snapshot(positions=(position,)))

    assert decision.action == "ADD"
    assert decision.current_quantity == 300
    assert decision.delta_quantity == 200


def test_brain_decision_is_reproducible_for_identical_inputs() -> None:
    research = _research()
    snapshot = _snapshot()
    policy = _policy()
    sizing = _sizing()
    first = _decision(research=research, snapshot=snapshot, policy=policy, sizing=sizing)
    second = _decision(research=research, snapshot=snapshot, policy=policy, sizing=sizing)
    assert first == second
    assert first.content_hash == second.content_hash


def test_brain_enforces_maximum_position_weight() -> None:
    decision = _decision(
        policy=_policy(
            max_single_position_weight=Decimal("0.050000"),
            risk_budget_per_trade=Decimal("0.050000"),
        ),
        sizing=_sizing(proposed_target_weight=Decimal("0.200000")),
    )
    assert decision.target_quantity == 500
    assert decision.delta_quantity == 200
    assert decision.target_weight <= Decimal("0.050000")


def test_brain_enforces_risk_budget_per_trade() -> None:
    decision = _decision(
        sizing=_sizing(proposed_target_weight=Decimal("0.150000")),
    )
    assert decision.target_quantity == 500
    assert decision.delta_quantity == 200
    assert "risk_budget_delta=200" in decision.risk_reasoning


def test_brain_enforces_minimum_cash_before_final_quantity() -> None:
    decision = _decision(
        snapshot=_snapshot(
            cash=Decimal("110000.00"),
            available_cash=Decimal("110000.00"),
        ),
        policy=_policy(
            max_single_position_weight=Decimal("0.200000"),
            risk_budget_per_trade=Decimal("0.100000"),
        ),
        sizing=_sizing(proposed_target_weight=Decimal("0.100000")),
    )
    assert decision.target_quantity == 400
    assert decision.delta_quantity == 100
    assert Decimal("110000") - Decimal(decision.delta_quantity) * Decimal("100") == Decimal("100000")


def test_brain_cash_cap_uses_observed_current_value_plus_new_limit_notional() -> None:
    decision = _decision(
        snapshot=_snapshot(
            cash=Decimal("110000.00"),
            available_cash=Decimal("110000.00"),
            positions=(
                Position(
                    symbol="600519",
                    market="CN",
                    quantity=300,
                    available_quantity=300,
                    avg_cost=Decimal("100.00"),
                    last_price=Decimal("200.00"),
                    market_value=Decimal("60000.00"),
                    unrealized_pnl=Decimal("30000.00"),
                    price_as_of=NOW,
                    price_source="ATHENA_DECIMAL_SIM",
                ),
            ),
        ),
        policy=_policy(
            max_single_position_weight=Decimal("0.200000"),
            risk_budget_per_trade=Decimal("0.100000"),
        ),
        sizing=_sizing(proposed_target_weight=Decimal("0.100000")),
    )

    assert decision.current_weight == Decimal("0.060000")
    assert decision.delta_quantity == 100
    assert decision.target_weight == Decimal("0.070000")


def test_brain_does_not_add_when_observed_position_already_exceeds_position_cap() -> None:
    decision = _decision(
        snapshot=_snapshot(
            positions=(
                Position(
                    symbol="600519",
                    market="CN",
                    quantity=300,
                    available_quantity=300,
                    avg_cost=Decimal("100.00"),
                    last_price=Decimal("200.00"),
                    market_value=Decimal("60000.00"),
                    unrealized_pnl=Decimal("30000.00"),
                    price_as_of=NOW,
                    price_source="ATHENA_DECIMAL_SIM",
                ),
            ),
        ),
        policy=_policy(
            max_single_position_weight=Decimal("0.050000"),
            risk_budget_per_trade=Decimal("0.050000"),
        ),
        sizing=_sizing(proposed_target_weight=Decimal("0.150000")),
    )

    assert decision.action == "HOLD"
    assert decision.delta_quantity == 0
    assert decision.target_weight == decision.current_weight == Decimal("0.060000")


def test_brain_keeps_negative_expected_return_research_at_hold() -> None:
    decision = _decision(
        research=_research(
            expected_return_range=ExpectedReturnRange(
                minimum=Decimal("-0.200000"),
                maximum=Decimal("-0.100000"),
            )
        )
    )
    assert decision.action == "HOLD"
    assert decision.target_quantity == decision.current_quantity == 300
    assert decision.delta_quantity == 0


def test_historical_hold_with_legacy_entry_plan_remains_readable() -> None:
    legacy_hold = _decision(
        research=_research(
            expected_return_range=ExpectedReturnRange(
                minimum=Decimal("-0.200000"),
                maximum=Decimal("-0.100000"),
            )
        )
    )

    restored = InvestmentDecision.model_validate_json(legacy_hold.canonical_json())

    assert legacy_hold.action == restored.action == "HOLD"
    assert restored.entry_plan is not None
    assert restored.content_hash == legacy_hold.content_hash


def test_brain_rejects_non_simulation_portfolio() -> None:
    snapshot = PortfolioSnapshot.build(
        **_build_values(_snapshot(), account_mode="PAPER")
    )
    with pytest.raises(ValueError, match="authoritative simulation portfolios"):
        _decision(snapshot=snapshot)


def test_brain_rejects_portfolio_below_policy_data_quality() -> None:
    with pytest.raises(ValueError, match="portfolio data quality"):
        _decision(snapshot=_snapshot(data_quality="LOW"))


@pytest.mark.parametrize(
    "producer_offset",
    (timedelta(milliseconds=93), timedelta(seconds=1)),
)
def test_brain_accepts_authoritative_snapshot_within_clock_skew_budget(
    producer_offset: timedelta,
) -> None:
    snapshot = _snapshot(
        as_of=NOW + producer_offset,
        created_at=NOW + producer_offset,
    )
    canonical_json = snapshot.canonical_json()
    content_hash = snapshot.content_hash

    decision = _decision(snapshot=snapshot)

    assert decision.portfolio_snapshot_hash == content_hash
    assert snapshot.canonical_json() == canonical_json
    assert snapshot.content_hash == content_hash


def test_brain_rejects_authoritative_snapshot_beyond_clock_skew_budget() -> None:
    with pytest.raises(ValueError, match="portfolio input cannot be from the future"):
        _decision(
            snapshot=_snapshot(
                as_of=NOW + timedelta(seconds=1, microseconds=1),
                created_at=NOW + timedelta(seconds=1, microseconds=1),
            )
        )


def test_brain_keeps_research_future_time_validation_at_zero_tolerance() -> None:
    with pytest.raises(ValueError, match="decision inputs cannot be from the future"):
        _decision(research=_research(as_of=NOW + timedelta(microseconds=1)))


def test_brain_keeps_risk_policy_effective_time_validation_unchanged() -> None:
    with pytest.raises(ValueError, match="risk policy is not effective"):
        _decision(policy=_policy(effective_from=NOW + timedelta(microseconds=1)))


def test_brain_rejects_decision_window_that_outlives_risk_policy() -> None:
    with pytest.raises(ValueError, match="cannot outlive the risk policy"):
        _decision(
            policy=_policy(effective_until=NOW + timedelta(hours=1)),
            sizing=_sizing(valid_until=NOW + timedelta(hours=2)),
        )


def test_mandate_projection_is_exact_and_fully_deterministic() -> None:
    decision = _decision()
    first = ExecutionMandateProjector.project(decision)
    second = ExecutionMandateProjector.project(decision)

    assert first == second
    assert first.content_hash == second.content_hash
    assert first.mandate_id == second.mandate_id
    assert first.idempotency_key == second.idempotency_key
    assert first.quantity == decision.delta_quantity == 200
    assert first.decision_hash == decision.content_hash
    assert first.expected_position_before == 300
    assert first.expected_position_after == 500
    assert first.simulation_only is True
    assert tuple(inspect.signature(ExecutionMandateProjector.project).parameters) == (
        "decision",
    )


def test_mandate_cannot_masquerade_as_a_resized_decision() -> None:
    decision = _decision()
    mandate = ExecutionMandateProjector.project(decision)
    resized = ExecutionMandate.build(
        **_build_values(
            mandate,
            quantity=100,
            expected_position_after=400,
        )
    )
    with pytest.raises(ValueError, match="differs from InvestmentDecision"):
        resized.assert_matches_decision(decision)


def test_mandate_cannot_disable_simulation_only() -> None:
    mandate = ExecutionMandateProjector.project(_decision())
    with pytest.raises(ValidationError, match="simulation_only"):
        ExecutionMandate.build(
            **_build_values(mandate, simulation_only=False)
        )


def test_decision_signal_is_a_read_only_projection_of_the_same_decision() -> None:
    decision = _decision()
    signal = DecisionSignalProjector.project(decision)
    legacy_request = DecisionSignalCreateRequest.model_validate(signal)
    assert signal["action"] == "add"
    assert legacy_request.action == "add"
    assert legacy_request.stock_code == decision.symbol
    assert signal["trace_id"] == decision.trace_id
    assert signal["metadata"]["investment_decision_id"] == decision.decision_id
    assert signal["metadata"]["investment_decision_hash"] == decision.content_hash
    assert signal["metadata"]["delta_quantity"] == 200
    assert signal["metadata"]["read_only_projection"] is True


def test_execution_result_supports_expired_partial_without_resubmission() -> None:
    result = ExecutionResult.build(
        result_id="result-expired-partial",
        mandate_id="mandate-1",
        mandate_hash="b" * 64,
        decision_id="decision-p0-1",
        decision_hash="c" * 64,
        trace_id="research-trace-p0",
        created_at=NOW,
        producer="ATHENA_EXECUTION_SPINE",
        attempt_no=1,
        account_id="simulation-account-1",
        symbol="600519",
        status="EXPIRED",
        requested_quantity=200,
        submitted_quantity=200,
        filled_quantity=100,
        remaining_quantity=100,
        requested_limit_price=Decimal("100.00"),
        average_fill_price=Decimal("99.90"),
        fees=Decimal("1.00"),
        slippage_bps=Decimal("-10.00"),
        broker_order_id="sim-order-1",
        correlation_id="correlation-1",
        safety_checks=(SafetyCheck(check="simulation_only", status="PASSED"),),
        submitted_at=NOW,
        last_update_at=NOW + timedelta(minutes=1),
        completed_at=NOW + timedelta(minutes=1),
        broker_evidence_ref="athena-journal:sim-order-1",
        reconciliation_status="RECONCILED",
        portfolio_snapshot_after_id="snapshot-b",
        portfolio_snapshot_after_hash="d" * 64,
    )
    assert result.filled_quantity == 100
    assert result.remaining_quantity == 100
    assert result.retry_forbidden is True
    with pytest.raises(ValidationError, match="cannot exceed requested_limit_price"):
        ExecutionResult.build(
            **_build_values(result, average_fill_price=Decimal("100.01"))
        )


def test_unknown_execution_is_exact_attempt_and_never_auto_retryable() -> None:
    result = ExecutionResult.build(
        result_id="result-unknown",
        mandate_id="mandate-1",
        mandate_hash="b" * 64,
        decision_id="decision-p0-1",
        decision_hash="c" * 64,
        trace_id="research-trace-p0",
        created_at=NOW,
        producer="ATHENA_EXECUTION_SPINE",
        attempt_no=1,
        account_id="simulation-account-1",
        symbol="600519",
        status="UNKNOWN",
        requested_quantity=200,
        submitted_quantity=200,
        filled_quantity=0,
        remaining_quantity=200,
        requested_limit_price=Decimal("100.00"),
        average_fill_price=None,
        fees=Decimal("0.00"),
        slippage_bps=None,
        broker_order_id=None,
        correlation_id="correlation-unknown",
        safety_checks=(SafetyCheck(check="submission_integrity", status="UNKNOWN"),),
        submitted_at=NOW,
        last_update_at=NOW,
        broker_evidence_ref="athena-journal:unknown",
        reconciliation_status="PENDING_RECONCILIATION",
    )
    assert result.status == "UNKNOWN"
    assert result.retry_forbidden is True
    with pytest.raises(ValidationError, match="zero or exactly requested_quantity"):
        ExecutionResult.build(
            **_build_values(result, submitted_quantity=100)
        )
