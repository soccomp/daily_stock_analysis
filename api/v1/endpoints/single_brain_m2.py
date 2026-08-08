"""Authenticated GET-only Single Brain M2 operator readiness."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.single_brain_m2 import SingleBrainM2ReadinessResponse
from src.auth import COOKIE_NAME
from src.services.single_brain_m2_readiness_service import SingleBrainM2ReadinessService


logger = logging.getLogger(__name__)
admin_session_cookie = APIKeyCookie(
    name=COOKIE_NAME,
    scheme_name="AdminSessionCookie",
    auto_error=False,
)
router = APIRouter(dependencies=[Security(admin_session_cookie)])


@router.get(
    "/readiness",
    response_model=SingleBrainM2ReadinessResponse,
    responses={
        401: {"model": ErrorResponse, "description": "未登录或管理员会话无效"},
        500: {"model": ErrorResponse, "description": "M2 readiness 读取失败"},
    },
    summary="读取 Single Brain M2 影子运行就绪状态",
    operation_id="getSingleBrainM2Readiness",
)
def get_readiness() -> SingleBrainM2ReadinessResponse:
    try:
        return SingleBrainM2ReadinessResponse(
            item=SingleBrainM2ReadinessService().get()
        )
    except Exception as exc:
        logger.error("Read Single Brain M2 readiness failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "Read M2 readiness failed"},
        ) from exc

