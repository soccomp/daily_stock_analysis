"""Read-only response schema for Single Brain M2 readiness."""

from typing import Any

from pydantic import BaseModel


class SingleBrainM2ReadinessResponse(BaseModel):
    item: dict[str, Any]


class SingleBrainM2ResearchTriggerResponse(BaseModel):
    status: str
    enqueue_status: str
    research_trigger_id: str
    dedup_key: str
    created: bool
    duplicate_count: int
