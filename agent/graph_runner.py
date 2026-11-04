"""Multi-agent investigation runner: wires the graph to the Postgres
checkpointer (thread_id = incident_id, so an investigation survives restarts
and can later be resumed at the Phase 6 approval interrupt), enforces the
overall timeout, and persists the outcome.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from agent.observability import traced
from api.services import incident_service
from common.config import get_settings

from langgraph.checkpoint.base import BaseCheckpointSaver  # noqa: E402


class AsyncCheckpointerAdapter(BaseCheckpointSaver):
    """Runs the SYNC PostgresSaver's operations in worker threads so an
    async LangGraph graph can use it.

    Why not AsyncPostgresSaver? psycopg-async rejects Windows' Proactor
    event loop, while MCP stdio subprocess spawning requires exactly that
    loop. This adapter keeps one Proactor loop for everything. (In
    langgraph-checkpoint 3.x the base class's async methods raise
    NotImplementedError instead of wrapping the sync ones.)
    """

    def __init__(self, sync_saver) -> None:  # noqa: ANN001
        super().__init__()
        self._saver = sync_saver

    def __getattr__(self, name):  # delegate sync passthroughs (setup etc.)
        return getattr(self._saver, name)

    async def aget_tuple(self, config):
        return await asyncio.to_thread(self._saver.get_tuple, config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(
            self._saver.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id):
        return await asyncio.to_thread(
            self._saver.put_writes, config, writes, task_id)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        def _collect():
            return list(self._saver.list(
                config, filter=filter, before=before, limit=limit))
        return iter(await asyncio.to_thread(_collect))

    async def adelete_thread(self, config):
        return await asyncio.to_thread(self._saver.delete_thread, config)


def _initial_state(incident_id: str, alert: dict) -> dict:
    from api.dedupe import service_from_labels

    labels = alert.get("labels", {})
    return {
        "incident_id": incident_id,
        "alert": alert,
        "namespace": labels.get("namespace") or get_settings().app_namespace,
        "service": service_from_labels(labels),
        "evidence": [],
        "hypotheses": [],
        "similar_incidents": [],
        "steps_used": 0,
        "cost_usd": 0.0,
        "timeline": [],
    }


async def _salvage_partial_timeline(graph, config: dict, incident_id: str) -> None:
    """Persist whatever steps the checkpointer recorded before the failure."""
    try:
        state = await graph.aget_state(config)
        timeline = (state.values or {}).get("timeline", [])
        if timeline:
            from api.services import incident_service as svc
            with get_pool_conn() as conn:
                conn.execute(
                    "UPDATE incidents SET actions = %s::jsonb WHERE id = %s",
                    (json.dumps(timeline, default=str), uuid.UUID(incident_id)),
                )
            svc.audit(incident_id, actor="system",
                      event="partial_timeline_salvaged",
                      detail={"steps": len(timeline)})
    except Exception:  # noqa: BLE001 - salvage is best-effort
        pass


def get_pool_conn():
    from database.connection import get_pool
    return get_pool().connection()


async def resume_decision(incident_id: str, decision: dict,
                          approver: str) -> tuple[str, str | None]:
    """Resume a paused investigation with a human decision.

    Returns (status, validation_error). status:
    - 'awaiting_approval' + error: the edited plan was invalid; the graph
      re-interrupted and is still paused (incident unchanged)
    - 'approved' / 'edited' / 'rejected': terminal decision recorded
    """
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.types import Command

    from agent.graph import build_graph

    settings = get_settings()
    with PostgresSaver.from_conn_string(settings.database_url) as saver:
        graph = build_graph(checkpointer=AsyncCheckpointerAdapter(saver))
        config = {"configurable": {"thread_id": incident_id}}
        final = await asyncio.wait_for(
            graph.ainvoke(Command(resume=decision), config=config),
            timeout=300,
        )
        snapshot = await graph.aget_state(config)

    if snapshot.next:
        # re-interrupted: the human's edit failed validation; still paused
        validation_error = None
        try:
            for task in snapshot.tasks:
                for intr in task.interrupts:
                    validation_error = (intr.value or {}).get("validation_error")
                    if validation_error:
                        break
        except Exception:  # noqa: BLE001
            pass
        incident_service.audit(
            incident_id, actor=f"human:{approver}",
            event="approval_edit_invalid",
            detail={"error": validation_error or "plan failed validation"})
        return "awaiting_approval", validation_error

    status = (final.get("approval") or decision.get("status", "rejected"))
    plan = [a.model_dump() for a in final.get("plan", [])]
    incident_service.record_approval(incident_id, approver,
                                     decision.get("status", status), plan)
    incident_service.audit(incident_id, actor=f"human:{approver}",
                           event="approval_decision",
                           detail={"decision": decision.get("status"),
                                   "plan": [a["name"] for a in plan]})
    return status, None


@traced("multi-agent-investigation")
async def run_multi_agent(incident_id: str, alert: dict[str, Any]) -> None:
    settings = get_settings()
    started = time.monotonic()
    incident_service.mark_investigating(incident_id)
    incident_service.audit(incident_id, actor="system",
                           event="investigation_started",
                           detail={"mode": "multi_agent"})
    try:
        # NOTE: the SYNC PostgresSaver is deliberate. The async saver needs
        # psycopg-async, which rejects Windows' Proactor event loop - while
        # MCP stdio subprocess spawning requires exactly that loop. langgraph
        # wraps sync checkpointers in an executor for async graphs, so this
        # works on both worlds (writes are small and fast).
        from langgraph.checkpoint.postgres import PostgresSaver

        from agent.graph import build_graph

        with PostgresSaver.from_conn_string(settings.database_url) as saver:
            saver.setup()  # idempotent checkpoint table creation
            graph = build_graph(checkpointer=AsyncCheckpointerAdapter(saver))
            config = {"configurable": {"thread_id": incident_id}}
            try:
                final = await asyncio.wait_for(
                    graph.ainvoke(_initial_state(incident_id, alert),
                                  config=config),
                    timeout=settings.investigation_timeout_s,
                )
            except Exception:
                # timeout/crash mid-investigation: salvage the partial timeline
                # from the checkpointer so the record is honest, not empty
                await _salvage_partial_timeline(graph, config, incident_id)
                raise

        seconds = int(time.monotonic() - started)
        report = final.get("report")
        timeline = final.get("timeline", [])
        outcome = final.get("outcome") or {}
        interrupted = bool(final.get("__interrupt__"))

        if interrupted and report is not None:
            # the graph paused at the human-approval interrupt: persist the
            # diagnosis + validated plan and wait for a decision
            incident_service.mark_awaiting_approval(
                incident_id,
                root_cause=report.root_cause,
                category=report.category,
                summary=(f"{report.explanation} [confidence "
                         f"{report.confidence:.2f}; evidence: "
                         f"{', '.join(report.supporting_evidence) or 'none'}]"),
                plan=[a.model_dump() for a in final.get("plan", [])],
                dry_run=final.get("plan_dry_run", []),
                timeline=timeline,
                seconds=seconds,
            )
            incident_service.audit(
                incident_id, actor="multi-agent",
                event="awaiting_approval",
                detail={"steps": final.get("steps_used", 0),
                        "plan": [a.name for a in final.get("plan", [])],
                        "seconds": seconds},
            )
            return

        if report is not None:
            summary = (
                f"{report.explanation} [confidence {report.confidence:.2f}; "
                f"evidence: {', '.join(report.supporting_evidence) or 'none'}]"
            )
            incident_service.complete_investigation(
                incident_id,
                {"suspected_root_cause": report.root_cause,
                 "category": report.category, "summary": summary,
                 "confidence": report.confidence,
                 "supporting_evidence": report.supporting_evidence},
                tool_calls=timeline,  # full step timeline for the dashboard
                seconds=seconds,
            )
            incident_service.audit(
                incident_id, actor="multi-agent",
                event="investigation_completed",
                detail={"steps": final.get("steps_used", 0),
                        "confidence": report.confidence,
                        "evidence_items": len(final.get("evidence", [])),
                        "seconds": seconds},
            )
        elif outcome.get("escalated"):
            incident_service.mark_escalated(
                incident_id, outcome.get("human_summary", "escalated"))
            incident_service.audit(incident_id, actor="multi-agent",
                                   event="investigation_escalated",
                                   detail={"steps": final.get("steps_used", 0)})
        else:
            incident_service.fail_investigation(
                incident_id, "graph ended without a report or escalation")
    except Exception as exc:  # noqa: BLE001 - every failure is recorded
        incident_service.fail_investigation(
            incident_id, f"{type(exc).__name__}: {exc}")
        incident_service.audit(incident_id, actor="system",
                               event="investigation_failed",
                               detail={"error": f"{type(exc).__name__}: {exc}"})
