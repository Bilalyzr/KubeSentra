"""Postmortem writer: closes every incident with a structured report stored
in PostgreSQL (with an embedding, so future triage can retrieve it)."""

from __future__ import annotations

import json
import uuid

from agent.state import IncidentState


def _latest_approval(incident_id: str) -> dict | None:
    from database.connection import get_pool

    try:
        with get_pool().connection() as conn:
            row = conn.execute(
                "SELECT approver, decision, plan, created_at FROM approvals "
                "WHERE incident_id = %s::uuid ORDER BY created_at DESC LIMIT 1",
                (incident_id,),
            ).fetchone()
        if row is None:
            return None
        return {"approver": row[0], "decision": row[1], "plan": row[2],
                "approved_at": str(row[3])}
    except Exception:  # noqa: BLE001
        return None


async def _lessons(state: IncidentState, root_cause: str) -> list[str]:
    """Cheap-LLM lessons/prevention bullets; deterministic fallback."""
    fallback = [
        f"Monitor {state.get('service', 'the service')} for recurrence of: "
        f"{root_cause[:120]}.",
        "Keep runbook knowledge current for this failure category.",
    ]
    try:
        from agent.llm import ainvoke_with_retry, build_llm
        prompt = (
            "Write 3 short 'lessons learned / prevention' bullets for this "
            "Kubernetes incident. Reply with ONLY a JSON array of strings.\n"
            f"Root cause: {root_cause}\n"
            f"Evidence: " + "; ".join(f"{e.id} {e.summary[:80]}"
                                      for e in state.get("evidence", [])[:6]))
        text = await ainvoke_with_retry(build_llm("cheap"), prompt)
        start, end = text.find("["), text.rfind("]")
        bullets = json.loads(text[start:end + 1])
        ok = [str(b)[:200] for b in bullets if isinstance(b, str)]
        return ok[:4] if ok else fallback
    except Exception:  # noqa: BLE001
        return fallback


async def postmortem_node(state: IncidentState) -> dict:
    incident_id = state["incident_id"]
    report = state.get("report")
    execution = state.get("execution") or {}
    outcome = state.get("outcome") or {}
    approval = _latest_approval(incident_id)
    lessons = await _lessons(state, report.root_cause if report else
                             (outcome.get("reason") or "uncertain"))

    postmortem = {
        "overview": (
            f"Incident on {state.get('service', 'unknown')} in namespace "
            f"{state.get('namespace', '?')} triggered by alert "
            f"{state.get('alert', {}).get('labels', {}).get('alertname', '?')}."),
        "timeline": [s for s in state.get("timeline", [])],
        "affected_service": state.get("service"),
        "symptoms": state.get("alert", {}).get("annotations", {}).get("summary",
                                                                      ""),
        "root_cause": report.root_cause if report else None,
        "root_cause_category": report.category if report else None,
        "evidence_references": [{"id": e.id, "source": e.source,
                                 "summary": e.summary[:150]}
                                for e in state.get("evidence", [])],
        "investigation_steps": [s.get("agent") for s in
                                state.get("timeline", [])],
        "remediation": {"plan": [a.model_dump() for a in
                                 state.get("plan", [])],
                        "executed": execution.get("executed", False),
                        "results": execution.get("results", [])},
        "approval": approval,
        "verification": outcome.get("verdict"),
        "verification_checks": outcome.get("checks", {}),
        "lessons_learned": lessons,
    }

    # persist: full text into summary, resolved flag from the verdict
    verdict = outcome.get("verdict")
    resolved = verdict == "RESOLVED"
    text = json.dumps(postmortem, indent=1, default=str)
    try:
        from common.embeddings import embed_texts
        from database.connection import get_pool
        embed = " ".join(filter(None, [
            state.get("alert", {}).get("labels", {}).get("alertname", ""),
            state.get("service", ""), postmortem["symptoms"],
            postmortem["root_cause"] or "", " ".join(lessons)]))
        vec = embed_texts([embed[:1000]])[0]
        with get_pool().connection() as conn:
            conn.execute(
                """
                UPDATE incidents
                SET summary = %s, resolved = %s,
                    status = CASE WHEN %s THEN 'resolved' ELSE status END,
                    embedding = %s::vector
                WHERE id = %s
                """,
                (text, resolved, resolved,
                 str(vec).replace(" ", ""), uuid.UUID(incident_id)),
            )
    except Exception as exc:  # noqa: BLE001 - text persistence even without
        # the embedding model
        from database.connection import get_pool
        with get_pool().connection() as conn:
            conn.execute(
                "UPDATE incidents SET summary = %s, resolved = %s, "
                "status = CASE WHEN %s THEN 'resolved' ELSE status END "
                "WHERE id = %s",
                (text, resolved, resolved, uuid.UUID(incident_id)),
            )

    try:
        from api.services import incident_service
        incident_service.audit(incident_id, actor="postmortem",
                               event="postmortem_written",
                               detail={"verdict": verdict,
                                       "resolved": resolved,
                                       "chars": len(text)})
    except Exception:  # noqa: BLE001 - audit must never break the postmortem
        pass
    return {"timeline": [{"agent": "postmortem", "verdict": verdict,
                          "resolved": resolved}]}
