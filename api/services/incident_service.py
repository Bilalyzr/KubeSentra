"""Incident persistence and audit helpers (all incident SQL lives here)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from psycopg.types.json import Json

from database.connection import get_pool

INCIDENT_COLUMNS = (
    "id, created_at, alert_name, namespace, service, symptoms, root_cause, "
    "root_cause_category, actions, resolved, time_to_diagnosis_s, summary, "
    "status, alert_labels, error"
)


def _row_to_dict(row: tuple) -> dict[str, Any]:
    keys = ("id", "created_at", "alert_name", "namespace", "service", "symptoms",
            "root_cause", "root_cause_category", "actions", "resolved",
            "time_to_diagnosis_s", "summary", "status", "alert_labels", "error")
    out = dict(zip(keys, row, strict=True))
    out["id"] = str(out["id"])
    out["created_at"] = str(out["created_at"])
    return out


def get_incident(incident_id: str) -> dict[str, Any] | None:
    try:
        uid = uuid.UUID(incident_id)
    except ValueError:
        return None
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {INCIDENT_COLUMNS} FROM incidents WHERE id = %s", (uid,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_incidents(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with get_pool().connection() as conn:
        if status:
            rows = conn.execute(
                f"SELECT {INCIDENT_COLUMNS} FROM incidents WHERE status = %s "
                f"ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {INCIDENT_COLUMNS} FROM incidents "
                f"ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def mark_resolved_by_fingerprint(fingerprint: str) -> int:
    """Resolve the newest closable incident matching this fingerprint.

    Live-gate lesson: alert flapping (e.g. CrashLoop backoff slowing the
    restart rate below the alert threshold) must NOT close an incident that
    is mid-investigation or paused for human approval - only incidents that
    are passively open/diagnosed/escalated/failed. The Verifier owns the
    final resolved verdict for active workflows.
    """
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id FROM incidents
            WHERE alert_labels->>'fingerprint' = %s
              AND status IN ('open', 'diagnosed', 'escalated', 'failed')
            ORDER BY created_at DESC LIMIT 1
            """,
            (fingerprint,),
        ).fetchone()
        if row is None:
            return 0
        conn.execute(
            "UPDATE incidents SET status = 'resolved', resolved = true WHERE id = %s",
            (row[0],),
        )
    audit(str(row[0]), actor="alertmanager", event="incident_resolved",
          detail={"fingerprint": fingerprint})
    return 1


def mark_investigating(incident_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE incidents SET status = 'investigating' WHERE id = %s",
            (uuid.UUID(incident_id),),
        )


def complete_investigation(incident_id: str, report: dict[str, Any],
                           tool_calls: list[dict], seconds: int) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE incidents
            SET status = 'diagnosed', root_cause = %s, root_cause_category = %s,
                summary = %s, actions = %s, time_to_diagnosis_s = %s, error = NULL
            WHERE id = %s
            """,
            (
                report["suspected_root_cause"], report["category"],
                report["summary"], json.dumps(tool_calls), seconds,
                uuid.UUID(incident_id),
            ),
        )


def fail_investigation(incident_id: str, error: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE incidents SET status = 'failed', error = %s WHERE id = %s",
            (error, uuid.UUID(incident_id)),
        )


def mark_escalated(incident_id: str, summary: str) -> None:
    """Budget exhausted without a confident diagnosis - hand over to a human
    with everything found so far."""
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE incidents SET status = 'escalated', summary = %s "
            "WHERE id = %s",
            (summary, uuid.UUID(incident_id)),
        )


def mark_awaiting_approval(incident_id: str, root_cause: str, category: str,
                           summary: str, plan: list, dry_run: list,
                           timeline: list, seconds: int,
                           hypotheses: list | None = None) -> None:
    """Graph paused at the approval interrupt: persist diagnosis + plan."""
    payload = {"plan": plan, "dry_run": dry_run, "hypotheses": hypotheses}
    with get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE incidents
            SET status = 'awaiting_approval', root_cause = %s,
                root_cause_category = %s, summary = %s,
                actions = %s::jsonb, time_to_diagnosis_s = %s
            WHERE id = %s
            """,
            (root_cause, category, summary,
             json.dumps({"approval_payload": payload, "timeline": timeline},
                        default=str),
             seconds, uuid.UUID(incident_id)),
        )


def get_timeline(incident_id: str) -> list[dict]:
    """Audit-log timeline for an incident (dashboard page 3)."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT created_at, actor, event, detail FROM audit_log "
            "WHERE incident_id = %s::uuid ORDER BY id",
            (incident_id,),
        ).fetchall()
    return [{"time": str(r[0]), "actor": r[1], "event": r[2],
             "detail": r[3]} for r in rows]


def get_evidence(incident_id: str) -> list[dict]:
    """Raw evidence payloads for an incident (dashboard page 3)."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, source, raw_output, created_at FROM evidence_raw "
            "WHERE incident_id = %s::uuid ORDER BY id",
            (incident_id,),
        ).fetchall()
    return [{"id": r[0], "source": r[1], "raw": r[2], "created": str(r[3])}
            for r in rows]


def get_stats() -> dict:
    """Overview statistics - computed from real rows only."""
    with get_pool().connection() as conn:
        def one(sql: str, params: tuple = ()) -> Any:
            return conn.execute(sql, params).fetchone()[0]

        by_status = dict(conn.execute(
            "SELECT status, count(*) FROM incidents GROUP BY status"
        ).fetchall())
        total = one("SELECT count(*) FROM incidents")
        avg_ttd = one(
            "SELECT avg(time_to_diagnosis_s) FROM incidents "
            "WHERE time_to_diagnosis_s IS NOT NULL")
        verdicts = dict(conn.execute(
            "SELECT summary::jsonb->>'verification' AS v, count(*) "
            "FROM incidents WHERE summary LIKE '{%' "
            "AND summary::jsonb ? 'verification' GROUP BY v"
        ).fetchall())
        recent = list_incidents(limit=10)
    executed = sum(verdicts.values())
    resolved = verdicts.get("RESOLVED", 0)
    return {
        "total": total,
        "by_status": by_status,
        "active": by_status.get("open", 0) + by_status.get("investigating", 0),
        "awaiting_approval": by_status.get("awaiting_approval", 0),
        "resolved": by_status.get("resolved", 0),
        "failed": by_status.get("failed", 0) + by_status.get("escalated", 0),
        "avg_time_to_diagnosis_s": round(float(avg_ttd), 1)
        if avg_ttd is not None else None,
        "verification_verdicts": verdicts,
        "remediation_attempts": executed,
        "remediation_success_rate": round(resolved / executed, 3)
        if executed else None,
        "recent": recent,
    }


def record_approval(incident_id: str, approver: str, decision: str,
                    plan: list) -> str:
    approval_id = str(uuid.uuid4())
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO approvals (id, incident_id, approver, decision, plan) "
            "VALUES (%s, %s::uuid, %s, %s, %s::jsonb)",
            (approval_id, incident_id, approver, decision,
             json.dumps(plan, default=str)),
        )
        new_status = ("approved" if decision in ("approved", "edited")
                      else "rejected")
        conn.execute(
            "UPDATE incidents SET status = %s WHERE id = %s::uuid",
            (new_status, incident_id),
        )
    return approval_id


def delete_approval(approval_id: str) -> None:
    """Revoke a provisionally recorded approval (e.g. the edited plan turned
    out invalid and the graph re-interrupted - nothing may execute)."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM approvals WHERE id = %s::uuid",
                     (approval_id,))


def audit(incident_id: str, actor: str, event: str, detail: dict) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO audit_log (incident_id, actor, event, detail) "
            "VALUES (%s, %s, %s, %s)",
            (uuid.UUID(incident_id), actor, event, Json(detail)),
        )
