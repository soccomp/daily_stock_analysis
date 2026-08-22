"""Read-only Pallas-010 dependency health projection."""

from fastapi import APIRouter

from src.services.dependency_health import get_dependency_health_store


router = APIRouter()


@router.get("/health")
async def dependency_health() -> dict:
    """Return the persisted dependency snapshot; never performs a network probe."""
    return get_dependency_health_store().snapshot()


__all__ = ["router"]
