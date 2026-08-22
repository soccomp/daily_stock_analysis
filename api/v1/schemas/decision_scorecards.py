"""Read-only API schemas for Single Decision Scorecards."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DecisionScorecardResponse(BaseModel):
    item: Dict[str, Any]


class DecisionScorecardSummary(BaseModel):
    """Factual list projection derived from one immutable scorecard."""

    decision_id: str
    created_at: str
    source_report_id: int
    account_id: str
    symbol: str
    market: str
    action: str
    current_quantity: int
    target_quantity: int
    delta_quantity: int
    confidence: str
    rationale: str
    mode: Optional[str] = None
    execution_status: Optional[str] = None
    reconciliation_status: Optional[str] = None
    requested_quantity: Optional[int] = None
    submitted_quantity: Optional[int] = None
    filled_quantity: Optional[int] = None
    remaining_quantity: Optional[int] = None
    average_fill_price: Optional[str] = None
    block_reason: Optional[str] = None
    broker_reason: Optional[str] = None
    snapshot_b_available: bool
    integrity_status: str = "VALID"
    integrity_error: Optional[str] = None


class DecisionScorecardListResponse(BaseModel):
    items: List[DecisionScorecardSummary] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
