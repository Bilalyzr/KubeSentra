"""Runbook knowledge-base endpoints (dashboard page 8).

Retrieval reuses the knowledge MCP server's hybrid search in-process.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from database.connection import get_pool

router = APIRouter()


@router.get("/runbooks")
def list_runbooks() -> dict:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT runbook, section, content, symptoms FROM runbook_chunks "
            "ORDER BY runbook, id"
        ).fetchall()
    books: dict[str, dict] = {}
    for runbook, section, content, symptoms in rows:
        book = books.setdefault(runbook, {"name": runbook,
                                          "tags": symptoms or [],
                                          "sections": []})
        book["sections"].append({"section": section, "content": content})
    return {"count": len(books), "runbooks": list(books.values())}


@router.get("/runbooks/search")
def search_runbooks(q: str = Query(min_length=2), limit: int = 4) -> dict:
    from mcp_servers.knowledge.server import hybrid_search_runbooks

    results = hybrid_search_runbooks(q, limit)
    return {"query": q, "results": results}
