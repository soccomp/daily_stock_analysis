"""Authenticated GET-only Mission-3 Owner operability projection."""

from fastapi import APIRouter, Security
from fastapi.security import APIKeyCookie

from src.auth import COOKIE_NAME
from src.services.mission3_operability import Mission3OperabilityService


admin_session_cookie = APIKeyCookie(
    name=COOKIE_NAME,
    scheme_name="AdminSessionCookie",
    auto_error=False,
)
router = APIRouter(dependencies=[Security(admin_session_cookie)])


@router.get("/operability")
def get_operability() -> dict:
    """Return persisted/read-only DSA facts; never initiate a Mission-3 action."""

    return Mission3OperabilityService().get()


__all__ = ["router"]
