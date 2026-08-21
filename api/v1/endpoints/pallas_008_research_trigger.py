"""PALLAS-008 loopback ingress into the canonical DSA research ledger."""

from __future__ import annotations

import hmac
import json
import logging
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import ValidationError

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.single_brain_m2 import SingleBrainM2ResearchTriggerResponse
from src.investment.contracts.research_trigger import ResearchTrigger
from src.investment.m2.research_trigger import ResearchTriggerConflictError, ResearchTriggerCoordinator
from src.storage import DatabaseManager


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/research-triggers",
    response_model=SingleBrainM2ResearchTriggerResponse,
    responses={
        401: {"model": ErrorResponse, "description": "内部触发器凭证无效"},
        409: {"model": ErrorResponse, "description": "触发器去重键内容冲突"},
        500: {"model": ErrorResponse, "description": "触发器入队失败"},
    },
    summary="将外部候选交给 DSA 研究触发协调器",
    operation_id="enqueueSingleBrainM2ResearchTrigger",
)
def enqueue_research_trigger(
    trigger: dict[str, object],
    pallas_token: str | None = Header(default=None, alias="X-Pallas-Research-Trigger-Token"),
) -> SingleBrainM2ResearchTriggerResponse:
    """Accept one loopback PALLAS trigger and persist it via the coordinator."""
    expected = str(os.getenv("PALLAS_DSA_RESEARCH_TRIGGER_TOKEN", "") or "").strip()
    supplied = str(pallas_token or "")
    if (expected and not hmac.compare_digest(supplied, expected)) or (
        not expected and os.getenv("ADMIN_AUTH_ENABLED", "").strip().lower() in {"true", "1", "yes"}
    ):
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "message": "Research trigger credential required"})
    try:
        canonical_trigger = ResearchTrigger.model_validate_json(json.dumps(trigger, ensure_ascii=False))
        result = ResearchTriggerCoordinator(DatabaseManager.get_instance()).enqueue(canonical_trigger)
    except (TypeError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_research_trigger", "message": "Research trigger is invalid"}) from exc
    except ResearchTriggerConflictError as exc:
        raise HTTPException(status_code=409, detail={"error": "trigger_conflict", "message": str(exc)}) from exc
    except Exception as exc:
        logger.error("Enqueue PALLAS research trigger failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "Research trigger enqueue failed"}) from exc
    return SingleBrainM2ResearchTriggerResponse(
        status="ACCEPTED",
        enqueue_status=result.status,
        research_trigger_id=result.trigger.research_trigger_id,
        dedup_key=result.trigger.dedup_key,
        created=result.created,
        duplicate_count=result.duplicate_count,
    )
