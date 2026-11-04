"""Integration tests: hybrid RAG retrieval and episodic memory.

Requires PostgreSQL + an ingested knowledge base (python -m knowledge.ingest).
Skips when either is missing.
"""

import uuid

import pytest

from database.connection import get_pool

pytestmark = pytest.mark.integration


def _db_up() -> bool:
    try:
        with get_pool().connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:  # noqa: BLE001
        return False


if not _db_up():
    pytest.skip("PostgreSQL not reachable", allow_module_level=True)


def _kb_ready() -> bool:
    with get_pool().connection() as conn:
        count = conn.execute("SELECT count(*) FROM runbook_chunks").fetchone()[0]
    return count > 0


if not _kb_ready():
    pytest.skip("knowledge base empty - run python -m knowledge.ingest",
                allow_module_level=True)


def test_semantic_query_finds_oom_runbook():
    from mcp_servers.knowledge.server import hybrid_search_runbooks
    results = hybrid_search_runbooks(
        "pod keeps restarting, container killed for exceeding memory", limit=3)
    names = [r["runbook"] for r in results]
    assert any("OOM" in n for n in names), names


def test_exact_keyword_fts_leg():
    """Exact Kubernetes error strings must be retrievable even when semantic
    similarity is weak - the FTS leg of the hybrid search."""
    from mcp_servers.knowledge.server import hybrid_search_runbooks
    results = hybrid_search_runbooks("ImagePullBackOff", limit=3)
    names = [r["runbook"] for r in results]
    assert any("Image" in n for n in names), names


def test_hybrid_returns_scores():
    from mcp_servers.knowledge.server import hybrid_search_runbooks
    results = hybrid_search_runbooks("readiness probe failing pod not ready",
                                     limit=3)
    assert results and all("score" in r for r in results)
    assert any("readiness" in r["runbook"].lower() for r in results)


def test_episodic_memory_roundtrip():
    """save_incident stores an embedding; similar_incidents retrieves it by
    semantic similarity (the triage memory path)."""
    from mcp_servers.knowledge.server import save_incident, similar_incidents
    token = f"memtest-{uuid.uuid4().hex[:8]}"
    saved = save_incident(
        alert_name="PodRestarting", namespace="boutique",
        service="checkoutservice",
        symptoms=f"restarts climbing {token}",
        root_cause=f"memory limit too low causing OOMKilled {token}",
        root_cause_category="resource", resolved=True,
        summary=f"{token} checkoutservice OOM after limit cut",
    )
    assert "with embedding" in saved, saved  # model must be available here
    inc_id = saved.split()[2]

    found = similar_incidents(
        "checkoutservice repeatedly killed out of memory restarts",
        service="checkoutservice", limit=3)
    try:
        assert any(f["id"] == inc_id for f in found), found
        match = next(f for f in found if f["id"] == inc_id)
        assert match["similarity"] is not None and match["similarity"] > 0.5
    finally:
        with get_pool().connection() as conn:
            conn.execute("DELETE FROM incidents WHERE id = %s::uuid", (inc_id,))
