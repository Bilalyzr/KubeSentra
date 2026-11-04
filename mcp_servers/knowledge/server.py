"""knowledge MCP server: incident memory and runbook retrieval.

Retrieval is HYBRID (implementation document 6.1):
- pgvector cosine similarity (bge-small-en-v1.5 embeddings)
- PostgreSQL full-text search (exact strings like OOMKilled matter)
- Reciprocal Rank Fusion merge

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
RRF_K = 60


def _rows(sql: str, params: tuple) -> list[tuple]:
    with get_pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def _embed_or_none(text: str) -> list[float] | None:
    """Best-effort local embedding; None falls back to FTS-only.

    Set KUBESENTRA_NO_EMBEDDINGS=1 to skip model loading entirely (used in
    MCP protocol tests - loading torch inside a stdio server subprocess is
    slow and has deadlocked on Windows)."""
    import os

    if os.environ.get("KUBESENTRA_NO_EMBEDDINGS"):
        return None
    try:
        from common.embeddings import embed_query
        return embed_query(text)
    except Exception:  # noqa: BLE001 - model unavailable -> keyword-only
        return None


def hybrid_search_runbooks(query: str, limit: int = 4) -> list[dict]:
    """RRF over the vector leg and the FTS leg. Returns runbook chunks."""
    limit = max(1, min(limit, MAX_ROWS))
    vec = _embed_or_none(query)

    fts_rows = _rows(
        """
        SELECT id, runbook, section, content FROM runbook_chunks
        WHERE tsv @@ websearch_to_tsquery('english', %s)
        ORDER BY ts_rank(tsv, websearch_to_tsquery('english', %s)) DESC
        LIMIT %s
        """,
        (query, query, limit * 3),
    )
    sem_rows: list[tuple] = []
    if vec is not None:
        vec_literal = str(vec).replace(" ", "")
        sem_rows = _rows(
            """
            SELECT id, runbook, section, content FROM runbook_chunks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vec_literal, limit * 3),
        )

    # Reciprocal Rank Fusion
    scores: dict[int, dict] = {}
    for rank, row in enumerate(fts_rows):
        scores.setdefault(row[0], {"row": row, "score": 0.0})
        scores[row[0]]["score"] += 1.0 / (RRF_K + rank + 1)
    for rank, row in enumerate(sem_rows):
        scores.setdefault(row[0], {"row": row, "score": 0.0})
        scores[row[0]]["score"] += 1.0 / (RRF_K + rank + 1)
    ranked = sorted(scores.values(), key=lambda d: d["score"], reverse=True)
    return [{"runbook": d["row"][1], "section": d["row"][2],
             "content": d["row"][3], "score": round(d["score"], 5)}
            for d in ranked[:limit]]


@mcp.tool()
def search_runbooks(query: str, limit: int = 4) -> str:
    """HYBRID search of the runbook knowledge base (semantic pgvector +
    keyword full-text, merged with Reciprocal Rank Fusion). Use for
    diagnosing and for choosing remediation."""
    results = hybrid_search_runbooks(query, limit)
    if not results:
        return (f"(no runbook chunks matched {query!r}; run "
                "python -m knowledge.ingest if the base is empty)")
    lines = [f"== {r['runbook']} :: {r['section']} (score {r['score']})\n"
             f"{r['content'][:600]}" for r in results]
    return cap(redact("\n\n".join(lines)))


def similar_incidents(query: str, service: str | None = None,
                      limit: int = 3) -> list[dict]:
    """Vector similarity over past incidents (episodic memory), newest-first
    tiebreak, optional service filter. Falls back to FTS without the model."""
    limit = max(1, min(limit, MAX_ROWS))
    vec = _embed_or_none(query)
    if vec is not None:
        vec_literal = str(vec).replace(" ", "")
        rows = _rows(
            """
            SELECT id, created_at, alert_name, service, root_cause,
                   root_cause_category, resolved, summary,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM incidents
            WHERE embedding IS NOT NULL
              AND (%s::text IS NULL OR service = %s)
            ORDER BY embedding <=> %s::vector, created_at DESC
            LIMIT %s
            """,
            (vec_literal, service, service, vec_literal, limit),
        )
        return [{"id": str(r[0]), "created_at": str(r[1]), "alert_name": r[2],
                 "service": r[3], "root_cause": r[4], "category": r[5],
                 "resolved": r[6], "summary": (r[7] or "")[:200],
                 "similarity": round(float(r[8]), 3)} for r in rows]
    # FTS fallback
    rows = _rows(
        """
        SELECT id, created_at, alert_name, service, root_cause,
               root_cause_category, resolved, summary
        FROM incidents
        WHERE to_tsvector('english',
               coalesce(alert_name,'') || ' ' || coalesce(service,'') || ' ' ||
               coalesce(root_cause,'') || ' ' || coalesce(summary,''))
              @@ websearch_to_tsquery('english', %s)
          AND (%s::text IS NULL OR service = %s)
        ORDER BY created_at DESC LIMIT %s
        """,
        (query, service, service, limit),
    )
    return [{"id": str(r[0]), "created_at": str(r[1]), "alert_name": r[2],
             "service": r[3], "root_cause": r[4], "category": r[5],
             "resolved": r[6], "summary": (r[7] or "")[:200],
             "similarity": None} for r in rows]


@mcp.tool()
def search_similar_incidents(query: str, service: str | None = None,
                             limit: int = 3) -> str:
    """Retrieve the most similar PAST incidents by embedding similarity
    (episodic memory). Results are hints to verify - never automatic
    diagnoses."""
    results = similar_incidents(query, service, limit)
    if not results:
        return f"(no similar incidents for {query!r})"
    lines = []
    for r in results:
        sim = f" sim={r['similarity']}" if r["similarity"] is not None else ""
        lines.append(
            f"incident {r['id']} | {r['created_at'][:16]} | alert={r['alert_name']} "
            f"service={r['service']}{sim} | cause={r['root_cause']} ({r['category']}) "
            f"resolved={r['resolved']}\n  summary: {r['summary']}")
    return cap(redact("\n".join(lines)))


@mcp.tool()
def search_incidents(query: str, service: str | None = None, limit: int = 5) -> str:
    """Keyword (full-text) search over past incidents - alert name, service,
    root cause and summary."""
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
          AND (%s::text IS NULL OR service = %s)
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (query, service, service, limit),
    )
    if not rows:
        return f"(no matching incidents for {query!r})"
    lines = [
        f"incident {r[0]} | {r[1]:%Y-%m-%d %H:%M} | alert={r[2]} service={r[3]} | "
        f"cause={r[4]} ({r[5]}) resolved={r[6]}\n  summary: {(r[7] or '')[:200]}"
        for r in rows
    ]
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
               time_to_diagnosis_s, summary, status
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
        "time_to_diagnosis_s": r[10], "summary": r[11], "status": r[12],
    }
    return cap(redact(json.dumps(body, indent=1, default=str)))


@mcp.tool()
def save_incident(alert_name: str, namespace: str, service: str, symptoms: str,
                  root_cause: str, root_cause_category: str,
                  actions: str = "[]", resolved: bool = False,
                  summary: str = "") -> str:
    """Persist an incident record WITH its embedding (episodic memory);
    called by the Postmortem writer.

    Args:
        actions: JSON array of action objects, e.g. [{"name":"rollout_undo"}].
        summary: human-readable postmortem summary.
    """
    try:
        actions_json = json.loads(actions) if actions else []
    except json.JSONDecodeError as exc:
        raise ValueError(f"actions must be valid JSON: {exc}") from exc
    incident_id = uuid.uuid4()
    embed_text = " ".join(filter(None, [alert_name, service, symptoms,
                                        root_cause, summary]))
    vec = _embed_or_none(embed_text)
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO incidents (id, alert_name, namespace, service, symptoms,
                                   root_cause, root_cause_category, actions,
                                   resolved, summary, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
            """,
            (incident_id, alert_name, namespace, service, symptoms,
             root_cause, root_cause_category, json.dumps(actions_json),
             resolved, summary,
             str(vec).replace(" ", "") if vec else None),
        )
    return f"saved incident {incident_id}" + (
        " (with embedding)" if vec else " (embedding unavailable - FTS only)")


if __name__ == "__main__":
    mcp.run()
