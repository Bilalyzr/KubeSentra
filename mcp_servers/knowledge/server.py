"""knowledge MCP server: incident memory and runbook retrieval.

Backed by PostgreSQL. Phase 3 ships full-text retrieval and incident
persistence; semantic (pgvector) retrieval and Reciprocal Rank Fusion are
added in Phase 6 together with runbook ingestion and bge-small embeddings.

Run: python -m mcp_servers.knowledge.server  (stdio transport)
"""

from __future__ import annotations

import json
import uuid

from mcp.server.fastmcp import FastMCP

from common.safety import cap, redact
from database.connection import get_pool

mcp = FastMCP("knowledge")

MAX_ROWS = 10


def _rows(sql: str, params: tuple) -> list[tuple]:
    with get_pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


@mcp.tool()
def search_incidents(query: str, service: str | None = None, limit: int = 5) -> str:
    """Search past incidents by keyword (full-text over alert name, service,
    root cause and summary). Returns the most recent matches.

    Past incidents are hints to verify, never automatic diagnoses.
    """
    limit = max(1, min(limit, MAX_ROWS))
    rows = _rows(
        """
        SELECT id, created_at, alert_name, service, root_cause,
               root_cause_category, resolved, summary
        FROM incidents
        WHERE to_tsvector('english',
               coalesce(alert_name,'') || ' ' || coalesce(service,'') || ' ' ||
               coalesce(root_cause,'') || ' ' || coalesce(summary,''))
              @@ websearch_to_tsquery('english', %s)
          AND (%s::text IS NULL OR service = %s::text)
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (query, service, service, limit),
    )
    if not rows:
        return f"(no matching incidents for {query!r})"
    lines = []
    for r in rows:
        lines.append(
            f"incident {r[0]} | {r[1]:%Y-%m-%d %H:%M} | alert={r[2]} service={r[3]} | "
            f"cause={r[4]} ({r[5]}) resolved={r[6]}\n  summary: {(r[7] or '')[:200]}"
        )
    return cap(redact("\n".join(lines)))


@mcp.tool()
def get_incident(incident_id: str) -> str:
    """Fetch one incident record by UUID, including actions and outcome."""
    try:
        uid = uuid.UUID(incident_id)
    except ValueError as exc:
        raise ValueError("incident_id must be a UUID") from exc
    rows = _rows(
        """
        SELECT id, created_at, alert_name, namespace, service, symptoms,
               root_cause, root_cause_category, actions, resolved,
               time_to_diagnosis_s, summary
        FROM incidents WHERE id = %s
        """,
        (uid,),
    )
    if not rows:
        return f"(incident {incident_id} not found)"
    r = rows[0]
    body = {
        "id": str(r[0]), "created_at": str(r[1]), "alert_name": r[2],
        "namespace": r[3], "service": r[4], "symptoms": r[5],
        "root_cause": r[6], "root_cause_category": r[7],
        "actions": r[8], "resolved": r[9],
        "time_to_diagnosis_s": r[10], "summary": r[11],
    }
    return cap(redact(json.dumps(body, indent=1, default=str)))


@mcp.tool()
def save_incident(alert_name: str, namespace: str, service: str, symptoms: str,
                  root_cause: str, root_cause_category: str,
                  actions: str = "[]", resolved: bool = False,
                  summary: str = "") -> str:
    """Persist an incident record (called by the Postmortem writer).

    Args:
        actions: JSON array of action objects, e.g. [{"name":"rollout_undo"}].
        summary: human-readable postmortem summary.
    The embedding column is filled by the Phase 6 memory pipeline.
    """
    try:
        actions_json = json.loads(actions) if actions else []
    except json.JSONDecodeError as exc:
        raise ValueError(f"actions must be valid JSON: {exc}") from exc
    incident_id = uuid.uuid4()
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO incidents (id, alert_name, namespace, service, symptoms,
                                   root_cause, root_cause_category, actions,
                                   resolved, summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (incident_id, alert_name, namespace, service, symptoms,
             root_cause, root_cause_category, json.dumps(actions_json),
             resolved, summary),
        )
    return f"saved incident {incident_id}"


@mcp.tool()
def search_runbooks(query: str, limit: int = 5) -> str:
    """Search runbook knowledge base by keyword (full-text over runbook
    content). Hybrid semantic + keyword retrieval (pgvector + RRF) is added
    in Phase 6 together with runbook ingestion."""
    limit = max(1, min(limit, MAX_ROWS))
    rows = _rows(
        """
        SELECT runbook, section, content
        FROM runbook_chunks
        WHERE tsv @@ websearch_to_tsquery('english', %s)
        ORDER BY ts_rank(tsv, websearch_to_tsquery('english', %s)) DESC
        LIMIT %s
        """,
        (query, query, limit),
    )
    if not rows:
        return (f"(no runbook chunks matched {query!r}; the knowledge base is "
                "populated during Phase 6 runbook ingestion)")
    lines = [
        f"== {r[0]} :: {r[1]}\n{r[2][:600]}" for r in rows
    ]
    return cap(redact("\n\n".join(lines)))


if __name__ == "__main__":
    mcp.run()
