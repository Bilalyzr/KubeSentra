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
    """Resolve the newest non-resolved incident matching this fingerprint."""
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id FROM incidents
            WHERE alert_labels->>'fingerprint' = %s AND status <> 'resolved'
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
                           timeline: list, seconds: int) -> None:
    """Graph paused at the approval interrupt: persist diagnosis + plan."""
    payload = {"plan": plan, "dry_run": dry_run}
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


def audit(incident_id: str, actor: str, event: str, detail: dict) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO audit_log (incident_id, actor, event, detail) "
            "VALUES (%s, %s, %s, %s)",
            (uuid.UUID(incident_id), actor, event, Json(detail)),
        )
