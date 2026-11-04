"""Incident query endpoints (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.services import incident_service

router = APIRouter()


@router.get("/incidents")
def list_incidents(status: str | None = Query(default=None),
                   limit: int = Query(default=50, ge=1, le=200)) -> dict:
    incidents = incident_service.list_incidents(status=status, limit=limit)
    return {"count": len(incidents), "incidents": incidents}


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str) -> dict:
    incident = incident_service.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident
