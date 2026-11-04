"""Investigation orchestration: run the configured investigation mode for
one incident.

- multi_agent (default): Phase 5 LangGraph Triage/Supervisor/specialists
- baseline: Phase 4 single ReAct agent (kept for the E1 comparison)

Every outcome - success, escalation or failure - is persisted and audited.
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
                           detail={"mode": settings.investigation_mode,
                                   "namespace": namespace, "service": service})
    try:
        if settings.investigation_mode == "multi_agent":
            # run_multi_agent handles its own persistence (diagnosed /
            # escalated / failed) and re-marks investigating
            from agent.graph_runner import run_multi_agent
            await run_multi_agent(incident_id, alert)
            return

        if settings.investigation_mode != "baseline":
            raise ValueError(
                f"unknown INVESTIGATION_MODE {settings.investigation_mode!r} "
                "(expected multi_agent or baseline)")

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
