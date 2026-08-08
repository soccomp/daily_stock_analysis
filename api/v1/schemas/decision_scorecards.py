"""Read-only API schema for the P1 Single Decision Scorecard."""

from typing import Any, Dict

from pydantic import BaseModel


class DecisionScorecardResponse(BaseModel):
    item: Dict[str, Any]
