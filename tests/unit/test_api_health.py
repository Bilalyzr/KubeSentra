"""Unit tests for the FastAPI health/readiness endpoints.

The not-ready path is tested by monkeypatching the database module, so no
live PostgreSQL is needed here.
"""

from fastapi.testclient import TestClient

from api.main import app
from database import connection as db

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "KubeSentra"
    assert "time" in body


def test_ready_ok_when_db_answers(monkeypatch):
    monkeypatch.setattr(db, "check_connection", lambda: True)
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "database": "connected"}


def test_ready_503_when_db_unreachable(monkeypatch):
    def boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(db, "check_connection", boom)
    resp = client.get("/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "unreachable"
    assert body["error"] == "RuntimeError"


def test_ready_503_when_query_fails(monkeypatch):
    monkeypatch.setattr(db, "check_connection", lambda: False)
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["database"] == "query_failed"
