"""SEC-5: duplicate alerts create ONE incident with an occurrence counter,
never duplicate investigations or duplicate writes."""

import uuid

from fastapi.testclient import TestClient

from api.main import app
from database.connection import get_pool

client = TestClient(app)


def test_burst_of_duplicates_single_incident():
    token = f"dupe-{uuid.uuid4().hex[:8]}"
    payload = {"alerts": [{
        "status": "firing",
        "labels": {"alertname": f"DupeAlert{token[:8]}",
                   "namespace": "boutique",
                   "pod": "frontend-58b4dc4d4d-mgzvg"},
        "annotations": {"summary": "dup test"},
    }]}
    created = []
    try:
        for _ in range(5):  # burst of 5 identical firing alerts
            resp = client.post("/alerts", json=payload)
            assert resp.status_code == 200
            body = resp.json()
            created.extend(body["created"])
        # exactly ONE incident; the rest attached
        assert len(created) == 1
        with get_pool().connection() as conn:
            occurrences = conn.execute(
                "SELECT alert_labels->>'occurrences' FROM incidents "
                "WHERE id = %s::uuid", (created[0],)).fetchone()[0]
            investigations = conn.execute(
                "SELECT count(*) FROM audit_log WHERE incident_id = %s::uuid "
                "AND event = 'investigation_started'",
                (created[0],)).fetchone()[0]
        assert int(occurrences) == 5
        assert investigations <= 1  # deduped - no repeated investigation
    finally:
        fallback = str(uuid.uuid4())
        with get_pool().connection() as conn:
            conn.execute("DELETE FROM audit_log WHERE incident_id = %s::uuid",
                         (created[0] if created else fallback,))
            conn.execute("DELETE FROM incidents WHERE id = %s::uuid",
                         (created[0] if created else fallback,))
