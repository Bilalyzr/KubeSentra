"""Human approval decisions: POST /incidents/{id}/decision (spec 10.1).

Authenticated with the approval bearer token. This is the ONLY way a paused
investigation resumes - there is no programmatic bypass.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from agent.guardrails import PlanRejected
from api.services import incident_service
from common.config import get_settings

router = APIRouter()


class DecisionRequest(BaseModel):
    status: str = Field(pattern="^(approved|edited|rejected)$")
    plan: list[dict] | None = None   # required when status == "edited"
    approver: str = Field(min_length=1, max_length=100)


@router.post("/incidents/{incident_id}/decision")
async def decide(incident_id: str, body: DecisionRequest,
                 x_approval_token: str = Header(default="")) -> dict:
    settings = get_settings()
    if not secrets.compare_digest(x_approval_token, settings.approval_token):
        raise HTTPException(status_code=401, detail="invalid approval token")

    incident = incident_service.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    if incident["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"incident is '{incident['status']}', not awaiting approval")

    if body.status == "edited" and not body.plan:
        raise HTTPException(status_code=400,
                            detail="edited decisions require a plan")

    # the graph must actually be PAUSED at the approval interrupt - resuming
    # a live/absent thread would crash mid-graph (found by the dashboard gate)
    from agent.graph_runner import thread_is_paused_at_approval

    if not await thread_is_paused_at_approval(incident_id):
        raise HTTPException(
            status_code=409,
            detail={"message": "no pending approval interrupt for this "
                               "incident - the workflow is not paused for a "
                               "decision",
                    "status": incident["status"]})

    from agent.graph_runner import resume_decision
    try:
        final_status, validation_error = await resume_decision(
            incident_id, {"status": body.status, "plan": body.plan or []},
            body.approver)
    except PlanRejected as exc:
        raise HTTPException(status_code=400,
                            detail=f"plan rejected by policy: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500,
                            detail=f"{type(exc).__name__}: {exc}") from exc

    if final_status == "awaiting_approval":
        # invalid edit: nothing executed, graph still paused for a corrected
        # decision
        raise HTTPException(
            status_code=400,
            detail={"validation_error": validation_error,
                    "message": "edited plan rejected by policy; the incident "
                               "remains awaiting a corrected decision"})

    return {"ok": True, "incident_id": incident_id, "status": final_status}
