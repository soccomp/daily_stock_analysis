"""Read-only Single Decision Scorecard endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.decision_scorecards import DecisionScorecardResponse
from src.auth import COOKIE_NAME
from src.services.decision_scorecard_service import (
    DecisionScorecardNotFoundError,
    DecisionScorecardService,
)


logger = logging.getLogger(__name__)
admin_session_cookie = APIKeyCookie(
    name=COOKIE_NAME,
    scheme_name="AdminSessionCookie",
    auto_error=False,
)
router = APIRouter(dependencies=[Security(admin_session_cookie)])


@router.get(
    "/{decision_id}",
    response_model=DecisionScorecardResponse,
    responses={
        401: {"model": ErrorResponse, "description": "未登录或管理员会话无效"},
        404: {"model": ErrorResponse, "description": "Scorecard 不存在"},
        500: {"model": ErrorResponse, "description": "Scorecard 读取失败"},
    },
    summary="按 decision_id 查询 Single Decision Scorecard",
    description=(
        "只读返回同一投资决策的 Research、Snapshot A、RiskPolicy、Decision、"
        "DecisionSignal、Mandate、ExecutionResult 与 Snapshot B lineage。"
    ),
    operation_id="getSingleDecisionScorecard",
)
def get_scorecard(
    decision_id: str = Path(..., min_length=1, max_length=160),
) -> DecisionScorecardResponse:
    try:
        return DecisionScorecardResponse(
            **DecisionScorecardService().get(decision_id)
        )
    except DecisionScorecardNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.error("Read decision scorecard failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": "Read decision scorecard failed",
            },
        ) from exc
