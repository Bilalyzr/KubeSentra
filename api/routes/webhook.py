"""Alertmanager webhook: POST /alerts (implementation doc section 10.1)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from api.dedupe import alert_fingerprint, open_or_attach_incident
from api.schemas.alerts import AlertmanagerPayload
from api.services import incident_service
from api.services.investigation import run_investigation
from common.safety import is_protected

router = APIRouter()


class WebhookResponse(BaseModel):
    ok: bool
    received: int
    created: list[str]
    attached: int
    resolved: int
    ignored_protected: int


@router.post("/alerts", response_model=WebhookResponse)
async def receive_alerts(payload: AlertmanagerPayload,
                         background_tasks: BackgroundTasks) -> WebhookResponse:
    created: list[str] = []
    attached = 0
    resolved = 0
    ignored = 0

    for alert in payload.alerts:
        namespace = alert.labels.get("namespace", "")
        # unscoped alerts (no namespace label) cannot be safely scoped to the
        # application namespace - ignore them along with protected namespaces
        if not namespace or is_protected(namespace):
            ignored += 1
            continue
        if alert.status == "firing":
            incident_id, is_new = open_or_attach_incident(alert)
            if is_new:
                created.append(str(incident_id))
                incident_service.audit(
                    str(incident_id), actor="alertmanager",
                    event="incident_created",
                    detail={"fingerprint": alert_fingerprint(alert)},
                )
                background_tasks.add_task(
                    run_investigation, str(incident_id), alert.model_dump()
                )
            else:
                attached += 1
        else:
            # resolved notifications never create incidents - they only
            # close matching open ones
            resolved += incident_service.mark_resolved_by_fingerprint(
                alert_fingerprint(alert))

    return WebhookResponse(ok=True, received=len(payload.alerts),
                           created=created, attached=attached, resolved=resolved,
                           ignored_protected=ignored)
