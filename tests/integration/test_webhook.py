"""Integration tests for the alert webhook + dedupe + incident lifecycle.

Uses a stub investigation runner so no LLM is needed; the honest
LLM-not-configured failure path is tested against the REAL runner.

Requires PostgreSQL (docker compose up -d postgres).
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import webhook as webhook_module
from api.services import incident_service
from database.connection import get_pool

pytestmark = pytest.mark.integration

client = TestClient(app)

TOKEN = f"webhook-test-{uuid.uuid4().hex[:8]}"
ALERTNAME = f"TestAlert{TOKEN[:12]}"


def _payload(status: str = "firing", pod: str = "checkoutservice-6fd54f5c78-gdtds") -> dict:
    return {
        "receiver": "test",
        "status": status,
        "alerts": [{
            "status": status,
            "labels": {
                "alertname": ALERTNAME,
                "namespace": "boutique",
                "pod": pod,
                "severity": "critical",
            },
            "annotations": {"summary": f"{TOKEN} restarts climbing"},
        }],
    }


def _cleanup(created_ids: list[str]):
    with get_pool().connection() as conn:
        for inc_id in created_ids:
            conn.execute("DELETE FROM audit_log WHERE incident_id = %s",
                         (uuid.UUID(inc_id),))
            conn.execute("DELETE FROM incidents WHERE id = %s",
                         (uuid.UUID(inc_id),))
        # sweep any stragglers from this test run
        conn.execute("DELETE FROM audit_log WHERE incident_id IN "
                     "(SELECT id FROM incidents WHERE alert_name = %s)",
                     (ALERTNAME,))
        conn.execute("DELETE FROM incidents WHERE alert_name = %s", (ALERTNAME,))


def _stub_investigation(incident_id: str, alert: dict) -> None:
    incident_service.complete_investigation(
        incident_id,
        {"suspected_root_cause": f"stub cause {TOKEN}", "category": "resource",
         "confidence": 0.9, "key_findings": ["stub"],
         "summary": f"stub summary {TOKEN}"},
        tool_calls=[{"name": "list_pods", "args": {}}],
        seconds=1,
    )


def test_webhook_full_lifecycle(monkeypatch):
    monkeypatch.setattr(webhook_module, "run_investigation", _stub_investigation)
    created_ids = []
    try:
        # 1. first firing alert creates an incident and completes it (stub)
        resp = client.post("/alerts", json=_payload())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"], body
        created_ids = body["created"]

        incident = incident_service.get_incident(created_ids[0])
        assert incident["status"] == "diagnosed"
        assert incident["root_cause"] == f"stub cause {TOKEN}"
        assert incident["service"] == "checkoutservice"
        assert incident["alert_labels"]["fingerprint"].startswith(ALERTNAME)
        assert incident["alert_labels"]["occurrences"] == 1

        # 2. duplicate firing alert within the window attaches, no new incident
        resp = client.post("/alerts", json=_payload())
        body = resp.json()
        assert body["created"] == []
        assert body["attached"] == 1

        incident = incident_service.get_incident(created_ids[0])
        assert incident["alert_labels"]["occurrences"] == 2

        # 3. different pod suffix, same service -> still deduplicated
        resp = client.post("/alerts", json=_payload(pod="checkoutservice-999999999-zzzzz"))
        assert resp.json()["attached"] == 1

        # 4. resolved notification closes the incident
        resp = client.post("/alerts", json=_payload(status="resolved"))
        assert resp.json()["resolved"] == 1
        incident = incident_service.get_incident(created_ids[0])
        assert incident["status"] == "resolved"
        assert incident["resolved"] is True

        # 5. a resolved notification with nothing open is a no-op
        resp = client.post("/alerts", json=_payload(status="resolved"))
        assert resp.json()["resolved"] == 0

        # 6. GET endpoints serve the incident
        listing = client.get("/incidents").json()
        assert any(i["id"] == created_ids[0] for i in listing["incidents"])
        single = client.get(f"/incidents/{created_ids[0]}")
        assert single.status_code == 200
        assert single.json()["alert_name"] == ALERTNAME

        missing = client.get(f"/incidents/{uuid.uuid4()}")
        assert missing.status_code == 404

        # 7. audit trail exists
        with get_pool().connection() as conn:
            events = [r[0] for r in conn.execute(
                "SELECT event FROM audit_log WHERE incident_id = %s ORDER BY id",
                (uuid.UUID(created_ids[0]),)).fetchall()]
        assert "incident_created" in events
        assert "incident_resolved" in events
    finally:
        _cleanup(created_ids)


def test_webhook_ignores_protected_namespaces():
    """Alerts from kube-system/monitoring/chaos-mesh must not create incidents
    (found in the live gate: stale control-plane alerts flooded the API)."""
    payload = _payload()
    payload["alerts"][0]["labels"]["namespace"] = "kube-system"
    resp = client.post("/alerts", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == []
    assert body["ignored_protected"] == 1


def test_webhook_llm_misconfiguration_marks_failure_honestly(monkeypatch):
    """REAL baseline runner with a broken LLM config (build_llm raises): the
    incident must be marked failed with a clear LLM error - never a simulated
    diagnosis. (Pinned to baseline mode: the default is now multi_agent.)"""
    import agent.baseline as baseline_module
    from agent.llm import LLMNotConfigured
    from common.config import get_settings

    monkeypatch.setenv("INVESTIGATION_MODE", "baseline")
    get_settings.cache_clear()

    def boom(role: str = "primary"):
        raise LLMNotConfigured("LLM_API_KEY is not set (simulated)")

    monkeypatch.setattr(baseline_module, "build_llm", boom)
    created_ids = []
    try:
        resp = client.post("/alerts", json=_payload())
        created_ids = resp.json()["created"]
        assert created_ids

        incident = incident_service.get_incident(created_ids[0])
        assert incident["status"] == "failed"
        assert "LLM" in (incident["error"] or ""), incident["error"]
    finally:
        get_settings.cache_clear()
        _cleanup(created_ids)


def _db_up() -> bool:
    try:
        with get_pool().connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:  # noqa: BLE001
        return False


if not _db_up():
    pytest.skip("PostgreSQL not reachable - run `docker compose up -d postgres`",
                allow_module_level=True)
