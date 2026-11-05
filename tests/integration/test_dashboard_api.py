"""Integration tests: the new dashboard-facing API endpoints against the
real database (stats, timeline, evidence, postmortem, runbooks).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from database.connection import get_pool

pytestmark = pytest.mark.integration

client = TestClient(app)


def _db_up() -> bool:
    try:
        with get_pool().connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:  # noqa: BLE001
        return False


if not _db_up():
    pytest.skip("PostgreSQL not reachable", allow_module_level=True)


TOKEN = f"dash-{uuid.uuid4().hex[:8]}"
INC_ID = None


@pytest.fixture(scope="module", autouse=True)
def seed_incident():
    global INC_ID
    INC_ID = str(uuid.uuid4())
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO incidents (id, alert_name, namespace, service, "
            "symptoms, root_cause, root_cause_category, status, "
            "time_to_diagnosis_s, actions) "
            "VALUES (%s::uuid, 'TestAlert', 'boutique', 'checkoutservice', "
            "'symptoms', 'cause here', 'resource', 'resolved', 42, "
            "'{\"timeline\": [{\"agent\": \"triage\"}]}'::jsonb)",
            (INC_ID,))
        conn.execute(
            "INSERT INTO evidence_raw (id, incident_id, source, raw_output) "
            "VALUES ('E1', %s::uuid, 'k8s', 'raw payload')", (INC_ID,))
        conn.execute(
            "INSERT INTO audit_log (incident_id, actor, event, detail) "
            "VALUES (%s::uuid, 'test', 'incident_created', '{}')", (INC_ID,))
    yield
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM audit_log WHERE incident_id = %s::uuid",
                     (INC_ID,))
        conn.execute("DELETE FROM evidence_raw WHERE incident_id = %s::uuid",
                     (INC_ID,))
        conn.execute("DELETE FROM incidents WHERE id = %s::uuid", (INC_ID,))


def test_stats_endpoint_shape():
    resp = client.get("/stats")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("total", "by_status", "active", "awaiting_approval",
                "resolved", "failed", "avg_time_to_diagnosis_s",
                "recent"):
        assert key in body
    assert body["total"] >= 1
    assert any(i["id"] == INC_ID for i in body["recent"])


def test_timeline_endpoint():
    resp = client.get(f"/incidents/{INC_ID}/timeline")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert any(e["event"] == "incident_created" for e in events)


def test_evidence_endpoint():
    resp = client.get(f"/incidents/{INC_ID}/evidence")
    assert resp.status_code == 200
    ev = resp.json()["evidence"]
    assert ev and ev[0]["id"] == "E1" and ev[0]["source"] == "k8s"


def test_postmortem_endpoint_text_summary():
    resp = client.get(f"/incidents/{INC_ID}/postmortem")
    assert resp.status_code == 200
    body = resp.json()
    # no JSON postmortem on the seeded row -> summary_text fallback
    assert body["postmortem"] is None


def test_postmortem_404():
    assert client.get(f"/incidents/{uuid.uuid4()}/postmortem").status_code == 404


def test_runbooks_list_and_search():
    resp = client.get("/runbooks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 20
    names = [b["name"] for b in body["runbooks"]]
    assert any("OOM" in n for n in names)

    resp = client.get("/runbooks/search", params={"q": "OOMKilled"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results and any("OOM" in r["runbook"] for r in results)
