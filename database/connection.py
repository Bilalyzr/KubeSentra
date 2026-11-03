"""PostgreSQL connectivity for KubeSentra (psycopg3).

A lazily created process-wide connection pool. Later phases (LangGraph
checkpointer, repositories) create their own connections; this module serves
application-level queries and the readiness check.
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool

from common.config import get_settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Return the shared connection pool, creating it on first use."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_settings().database_url,
            min_size=1,
            max_size=5,
            open=True,
        )
    return _pool


def close_pool() -> None:
    """Close the shared pool (used on shutdown and in tests)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def check_connection() -> bool:
    """Return True when the database answers a trivial query.

    Raises on connection failure - callers decide how to report that.
    """
    with get_pool().connection() as conn:
        return conn.execute("SELECT 1").fetchone()[0] == 1
