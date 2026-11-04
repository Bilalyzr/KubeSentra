"""Investigation orchestration: run the baseline agent for one incident.

This is the bridge between the webhook (HTTP) and the agent layer. Every
outcome - success or failure - is persisted on the incident and audited.
"""

from __future__ import annotations

import time
from typing import Any

from agent.observability import traced
from api.services import incident_service
from common.config import get_settings


@traced("incident-investigation")
async def run_investigation(incident_id: str, alert: dict[str, Any]) -> None:
    started = time.monotonic()
    settings = get_settings()
    namespace = alert.get("labels", {}).get("namespace") or settings.app_namespace
    service = alert.get("labels", {}).get("service", "unknown")

    incident_service.mark_investigating(incident_id)
    incident_service.audit(incident_id, actor="system",
                           event="investigation_started",
                           detail={"namespace": namespace, "service": service})
    try:
        # imported lazily so the API can start without the agent stack
        from agent.baseline import run_baseline
        report, tool_calls = await run_baseline(alert, namespace, service)
        incident_service.complete_investigation(
            incident_id,
            report.model_dump(),
            tool_calls,
            seconds=int(time.monotonic() - started),
        )
        incident_service.audit(
            incident_id, actor="baseline-agent",
            event="investigation_completed",
            detail={"category": report.category,
                    "confidence": report.confidence,
                    "tool_calls": len(tool_calls)},
        )
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, never hidden
        incident_service.fail_investigation(
            incident_id, f"{type(exc).__name__}: {exc}")
        incident_service.audit(
            incident_id, actor="system", event="investigation_failed",
            detail={"error": f"{type(exc).__name__}: {exc}"},
        )
