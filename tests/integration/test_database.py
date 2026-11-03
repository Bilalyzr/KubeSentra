"""Integration tests against the live PostgreSQL database.

Skipped automatically when the database is unreachable. Start it first:

    docker compose up -d postgres
    python -m database.migrate

These tests fail (not skip) if migrations have not been applied - that is a
real regression signal, not an environment problem.
"""

import uuid

import psycopg
import pytest
from psycopg.types.json import Json

from common.config import get_settings

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "runbook_chunks",
    "incidents",
    "evidence_raw",
    "audit_log",
    "schema_migrations",
}


def _connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url, connect_timeout=3)


try:
    with _connect() as _probe:
        _probe.execute("SELECT 1").fetchone()
    _DB_AVAILABLE = True
except Exception:  # noqa: BLE001 - any failure means "not running"
    _DB_AVAILABLE = False

if not _DB_AVAILABLE:
    pytest.skip("PostgreSQL not reachable - run `docker compose up -d postgres`",
                allow_module_level=True)


def test_select_one():
    with _connect() as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1


def test_pgvector_extension_enabled():
    with _connect() as conn:
        row = conn.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    assert row is not None, "pgvector extension is not installed"


def test_core_tables_exist():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        ).fetchall()
    tables = {row[0] for row in rows}
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing tables: {missing} (did migrations run?)"


def test_migrations_recorded():
    with _connect() as conn:
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    assert {"0001", "0002"} <= applied


def test_incident_roundtrip_with_vector_embedding():
    incident_id = uuid.uuid4()
    vec = "[" + ",".join(["0.0"] * 384) + "]"
    with _connect() as conn:
        conn.execute(
            """INSERT INTO incidents (id, alert_name, namespace, service, symptoms, embedding)
               VALUES (%s, 'TestAlert', 'boutique', 'checkoutservice', 'test symptom', %s::vector)""",
            (incident_id, vec),
        )
        row = conn.execute(
            "SELECT alert_name, root_cause FROM incidents WHERE id = %s",
            (incident_id,),
        ).fetchone()
        assert row == ("TestAlert", None)

        conn.execute("DELETE FROM incidents WHERE id = %s", (incident_id,))
        count = conn.execute(
            "SELECT count(*) FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone()[0]
    assert count == 0


def test_runbook_chunk_generates_tsv():
    with _connect() as conn:
        row = conn.execute(
            """INSERT INTO runbook_chunks (runbook, section, content, symptoms)
               VALUES ('test-runbook', 'symptoms',
                       'Pod is stuck in CrashLoopBackOff state', ARRAY['crashloop'])
               RETURNING id, tsv""",
        ).fetchone()
        chunk_id, tsv = row
        assert tsv is not None and str(tsv) != ""
        conn.execute("DELETE FROM runbook_chunks WHERE id = %s", (chunk_id,))


def test_audit_log_accepts_jsonb_detail():
    with _connect() as conn:
        audit_id = conn.execute(
            """INSERT INTO audit_log (actor, event, detail)
               VALUES ('pytest', 'unit_test', %s) RETURNING id""",
            (Json({"phase": 1}, ),),
        ).fetchone()[0]
        conn.execute("DELETE FROM audit_log WHERE id = %s", (audit_id,))
