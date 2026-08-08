"""Read-only response schema for Single Brain M2 readiness."""

from typing import Any

from pydantic import BaseModel


class SingleBrainM2ReadinessResponse(BaseModel):
    item: dict[str, Any]

