"""Incident query endpoints (read-only)."""

from __future__ import annotations

import json

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


@router.get("/incidents/{incident_id}/timeline")
def get_timeline(incident_id: str) -> dict:
    if incident_service.get_incident(incident_id) is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return {"incident_id": incident_id,
            "events": incident_service.get_timeline(incident_id)}


@router.get("/incidents/{incident_id}/evidence")
def get_evidence(incident_id: str) -> dict:
    if incident_service.get_incident(incident_id) is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return {"incident_id": incident_id,
            "evidence": incident_service.get_evidence(incident_id)}


@router.get("/incidents/{incident_id}/postmortem")
def get_postmortem(incident_id: str) -> dict:
    incident = incident_service.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    summary = incident.get("summary") or ""
    if summary.startswith("{"):
        try:
            return {"incident_id": incident_id, "postmortem": json.loads(summary)}
        except json.JSONDecodeError:
            pass
    return {"incident_id": incident_id,
            "postmortem": None,
            "summary_text": summary}
