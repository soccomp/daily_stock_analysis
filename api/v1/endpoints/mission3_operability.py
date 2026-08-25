"""Authenticated GET-only Mission-3 Owner operability projection."""

from fastapi import APIRouter, Depends, Security
from fastapi.security import APIKeyCookie

from src.auth import COOKIE_NAME
from src.services.mission3_operability import Mission3OperabilityService
from api.deps import get_runtime_scheduler_service
from src.services.runtime_scheduler import RuntimeSchedulerService


admin_session_cookie = APIKeyCookie(
    name=COOKIE_NAME,
    scheme_name="AdminSessionCookie",
    auto_error=False,
)
router = APIRouter(dependencies=[Security(admin_session_cookie)])


@router.get("/operability")
def get_operability(
    runtime_scheduler: RuntimeSchedulerService = Depends(get_runtime_scheduler_service),
) -> dict:
    """Return persisted/read-only DSA facts; never initiate a Mission-3 action."""

    return Mission3OperabilityService(runtime_scheduler=runtime_scheduler).get()


__all__ = ["router"]
