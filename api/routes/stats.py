"""System statistics endpoint (dashboard overview - real computed data)."""

from __future__ import annotations

from fastapi import APIRouter

from api.services import incident_service

router = APIRouter()


@router.get("/stats")
def stats() -> dict:
    return incident_service.get_stats()
