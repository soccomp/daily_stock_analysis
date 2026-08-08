"""Athena-owned execution outcome contract consumed by DSA."""

from __future__ import annotations

from typing import ClassVar, Literal, Mapping

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, model_validator
from typing_extensions import Self

from .base import CanonicalContract, CanonicalDecimal, FrozenValue, StrictTrue


class SafetyCheck(FrozenValue):
    check: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["PASSED", "BLOCKED", "UNKNOWN"]
    reason: StrictStr | None = Field(default=None, min_length=1, max_length=512)


class ExecutionResult(CanonicalContract):
    """Traceable execution fact; UNKNOWN is terminal for automatic submission."""

    BUILD_DEFAULTS: ClassVar[Mapping[str, object]] = {
        "schema_version": "1.0",
        "average_fill_price": None,
        "slippage_bps": None,
        "broker_order_id": None,
        "block_reason": None,
        "broker_reason": None,
        "submitted_at": None,
        "completed_at": None,
        "broker_evidence_ref": None,
        "portfolio_snapshot_after_id": None,
        "portfolio_snapshot_after_hash": None,
        "simulation_only": True,
        "retry_forbidden": True,
    }

    schema_version: Literal["1.0"]
    result_id: StrictStr = Field(min_length=1, max_length=160)
    mandate_id: StrictStr = Field(min_length=1, max_length=160)
    mandate_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: StrictStr = Field(min_length=1, max_length=160)
    decision_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    attempt_no: StrictInt = Field(gt=0)
    account_id: StrictStr = Field(min_length=1, max_length=160)
    symbol: StrictStr = Field(min_length=1, max_length=64)
    status: Literal[
        "ACCEPTED",
        "ACTIVE",
        "PARTIALLY_FILLED",
        "FILLED",
        "BLOCKED",
        "BROKER_REJECTED",
        "EXPIRED",
        "CANCELLED",
        "UNKNOWN",
    ]

    requested_quantity: StrictInt = Field(gt=0)
    submitted_quantity: StrictInt = Field(ge=0)
    filled_quantity: StrictInt = Field(ge=0)
    remaining_quantity: StrictInt = Field(ge=0)
    requested_limit_price: CanonicalDecimal = Field(gt=0)
    average_fill_price: CanonicalDecimal | None = Field(gt=0)
    fees: CanonicalDecimal = Field(ge=0)
    slippage_bps: CanonicalDecimal | None

    broker_order_id: StrictStr | None = Field(min_length=1, max_length=160)
    correlation_id: StrictStr = Field(min_length=1, max_length=160)
    safety_checks: tuple[SafetyCheck, ...]
    block_reason: StrictStr | None = Field(min_length=1, max_length=256)
    broker_reason: StrictStr | None = Field(min_length=1, max_length=512)

    submitted_at: AwareDatetime | None
    last_update_at: AwareDatetime
    completed_at: AwareDatetime | None
    broker_evidence_ref: StrictStr | None = Field(min_length=1, max_length=512)
    reconciliation_status: Literal[
        "NOT_REQUIRED",
        "PENDING_RECONCILIATION",
        "RECONCILED",
        "DEGRADED",
        "UNKNOWN",
    ]
    portfolio_snapshot_after_id: StrictStr | None = Field(min_length=1, max_length=160)
    portfolio_snapshot_after_hash: StrictStr | None = Field(pattern=r"^[0-9a-f]{64}$")
    simulation_only: StrictTrue
    retry_forbidden: StrictTrue

    @model_validator(mode="after")
    def _execution_semantics(self) -> Self:
        if self.submitted_quantity not in (0, self.requested_quantity):
            raise ValueError("submitted_quantity must be zero or exactly requested_quantity")
        if self.filled_quantity > self.submitted_quantity:
            raise ValueError("filled_quantity cannot exceed submitted_quantity")
        if self.remaining_quantity != self.requested_quantity - self.filled_quantity:
            raise ValueError("remaining_quantity must equal requested minus filled")
        if self.filled_quantity > 0 and self.average_fill_price is None:
            raise ValueError("average_fill_price is required when filled_quantity is positive")
        if self.filled_quantity == 0 and self.average_fill_price is not None:
            raise ValueError("average_fill_price requires a positive filled_quantity")
        if (
            self.average_fill_price is not None
            and self.average_fill_price > self.requested_limit_price
        ):
            raise ValueError("BUY average_fill_price cannot exceed requested_limit_price")
        if self.status == "FILLED" and not (
            self.filled_quantity == self.requested_quantity and self.remaining_quantity == 0
        ):
            raise ValueError("FILLED requires the full requested quantity")
        if self.status == "PARTIALLY_FILLED" and not (
            0 < self.filled_quantity < self.requested_quantity
        ):
            raise ValueError("PARTIALLY_FILLED requires a non-zero partial quantity")
        if self.status == "BLOCKED" and self.submitted_quantity != 0:
            raise ValueError("BLOCKED results cannot submit")
        if self.status == "BLOCKED" and self.block_reason is None:
            raise ValueError("BLOCKED requires block_reason")
        if self.status in {"ACCEPTED", "ACTIVE", "PARTIALLY_FILLED", "FILLED"}:
            if self.submitted_quantity != self.requested_quantity:
                raise ValueError("accepted execution states require exact submission quantity")
            if self.submitted_at is None:
                raise ValueError("submitted_at is required after submission")
        if self.submitted_quantity > 0 and self.submitted_at is None:
            raise ValueError("submitted_at is required when an exact quantity was submitted")
        if self.status == "EXPIRED":
            if self.submitted_quantity == 0 and self.filled_quantity != 0:
                raise ValueError("pre-submission EXPIRED results cannot contain fills")
            if self.submitted_quantity > 0 and self.filled_quantity >= self.requested_quantity:
                raise ValueError("an expired order must have an unfilled remainder")
        if self.status == "UNKNOWN":
            if self.submitted_quantity != self.requested_quantity:
                raise ValueError("UNKNOWN represents an ambiguous exact submission attempt")
            if self.reconciliation_status != "PENDING_RECONCILIATION":
                raise ValueError("UNKNOWN execution requires reconciliation before any retry")
        if (self.portfolio_snapshot_after_id is None) != (
            self.portfolio_snapshot_after_hash is None
        ):
            raise ValueError("post-execution snapshot id and hash must be supplied together")
        if self.completed_at is not None and self.completed_at < self.last_update_at:
            raise ValueError("completed_at cannot precede last_update_at")
        if self.submitted_at is not None and self.last_update_at < self.submitted_at:
            raise ValueError("last_update_at cannot precede submitted_at")
        return self
