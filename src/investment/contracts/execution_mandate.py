"""Deterministic machine-execution projection of an InvestmentDecision."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal, Mapping

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, model_validator
from typing_extensions import Self

from .base import CanonicalContract, CanonicalDecimal, StrictTrue

if TYPE_CHECKING:
    from .investment_decision import InvestmentDecision


class ExecutionMandate(CanonicalContract):
    """P0 instruction Athena must execute exactly or block without submission."""

    BUILD_DEFAULTS: ClassVar[Mapping[str, object]] = {
        "schema_version": "1.0",
        "operation": "SUBMIT",
        "side": "BUY",
        "order_type": "LIMIT",
        "simulation_only": True,
        "supersedes_mandate_id": None,
    }

    schema_version: Literal["1.0"]
    mandate_id: StrictStr = Field(min_length=1, max_length=160)
    decision_id: StrictStr = Field(min_length=1, max_length=160)
    decision_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    decision_cycle_id: StrictStr = Field(min_length=1, max_length=160)
    account_id: StrictStr = Field(min_length=1, max_length=160)
    symbol: StrictStr = Field(min_length=1, max_length=64)
    market: StrictStr = Field(min_length=1, max_length=32)

    mandate_type: Literal["ENTRY", "ADD"]
    operation: Literal["SUBMIT"]
    side: Literal["BUY"]
    quantity: StrictInt = Field(gt=0)
    order_type: Literal["LIMIT"]
    limit_price: CanonicalDecimal = Field(gt=0)
    trigger_condition: StrictStr = Field(min_length=1, max_length=256)
    time_in_force: Literal["DAY", "GTC"]
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    portfolio_snapshot_id: StrictStr = Field(min_length=1, max_length=160)
    portfolio_snapshot_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    expected_position_before: StrictInt = Field(ge=0)
    expected_position_after: StrictInt = Field(gt=0)
    simulation_only: StrictTrue
    idempotency_key: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes_mandate_id: StrictStr | None = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def _mandate_semantics(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if self.created_at > self.valid_until:
            raise ValueError("mandate cannot be created after decision expiry")
        if self.expected_position_after - self.expected_position_before != self.quantity:
            raise ValueError("mandate quantity must equal the expected position delta")
        if self.mandate_type == "ENTRY" and self.expected_position_before != 0:
            raise ValueError("ENTRY requires expected_position_before to be zero")
        if self.mandate_type == "ADD" and self.expected_position_before <= 0:
            raise ValueError("ADD requires an existing expected position")
        if (
            self.supersedes_id is not None
            and self.supersedes_mandate_id is not None
            and self.supersedes_id != self.supersedes_mandate_id
        ):
            raise ValueError("supersedes mandate identifiers must agree")
        return self

    def assert_matches_decision(self, decision: "InvestmentDecision") -> None:
        """Verify that this machine projection is exactly bound to one decision."""

        expected = {
            "trace_id": decision.trace_id,
            "decision_id": decision.decision_id,
            "decision_hash": decision.content_hash,
            "decision_cycle_id": decision.decision_cycle_id,
            "account_id": decision.account_id,
            "symbol": decision.symbol,
            "market": decision.market,
            "quantity": decision.delta_quantity,
            "limit_price": decision.entry_plan.limit_price,
            "portfolio_snapshot_id": decision.portfolio_snapshot_id,
            "portfolio_snapshot_hash": decision.portfolio_snapshot_hash,
            "expected_position_before": decision.current_quantity,
            "expected_position_after": decision.target_quantity,
        }
        mismatches = [
            field_name
            for field_name, expected_value in expected.items()
            if getattr(self, field_name) != expected_value
        ]
        expected_type = "ENTRY" if decision.action == "BUY" else "ADD"
        if self.mandate_type != expected_type:
            mismatches.append("mandate_type")
        if decision.action not in {"BUY", "ADD"}:
            mismatches.append("decision.action")
        if mismatches:
            raise ValueError(
                "execution mandate differs from InvestmentDecision: "
                + ", ".join(sorted(set(mismatches)))
            )
