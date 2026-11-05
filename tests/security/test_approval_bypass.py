"""SEC-2: approval bypass attempts.

Every path to a cluster write must pass: token → paused interrupt → recorded
approval → validated plan → executor credential. Test each hop's refusal.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
TOKEN_HDR = {"X-Approval-Token": "kubesentra-dev-approval"}


@pytest.fixture
def incident_row():
    inc_id = str(uuid.uuid4())
    from database.connection import get_pool

    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO incidents (id, alert_name, namespace, service, "
            "status) VALUES (%s::uuid, 'BypassAlert', 'boutique', "
            "'checkoutservice', 'awaiting_approval')", (inc_id,))
    yield inc_id
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM approvals WHERE incident_id = %s::uuid",
                     (inc_id,))
        conn.execute("DELETE FROM audit_log WHERE incident_id = %s::uuid",
                     (inc_id,))
        conn.execute("DELETE FROM incidents WHERE id = %s::uuid", (inc_id,))


def test_no_token_401(incident_row):
    resp = client.post(f"/incidents/{incident_row}/decision",
                       json={"status": "approved", "approver": "attacker"})
    assert resp.status_code == 401


def test_wrong_token_401(incident_row):
    resp = client.post(
        f"/incidents/{incident_row}/decision",
        json={"status": "approved", "approver": "attacker"},
        headers={"X-Approval-Token": "guessed-token"})
    assert resp.status_code == 401


def test_valid_token_but_not_paused_409(incident_row):
    """Correct token, incident LOOKS pending, but no real graph interrupt
    exists -> refused (fail closed; found by the Phase 8 gate)."""
    resp = client.post(
        f"/incidents/{incident_row}/decision",
        json={"status": "approved", "approver": "attacker"},
        headers=TOKEN_HDR)
    assert resp.status_code == 409
    assert "no pending approval interrupt" in resp.text


def test_executor_refuses_without_approval_record():
    """Direct node-level attack: state.approval forged to 'approved' with no
    approvals row -> executor refuses (fail closed)."""
    import asyncio

    from agent.nodes.executor import execute_node
    from agent.state import Action

    state = {
        "incident_id": str(uuid.uuid4()),  # no row, no approvals record
        "alert": {"labels": {}}, "namespace": "boutique",
        "service": "checkoutservice", "approval": "approved",  # forged
        "plan": [Action(name="rollout_undo", namespace="boutique",
                        target="checkoutservice", params={}, risk="low",
                        rationale="forged")],
        "execution": None,
    }
    delta = asyncio.run(execute_node(state))
    assert delta["execution"]["executed"] is False
    assert "refus" in delta["execution"]["reason"].lower()


def test_write_count_without_approval_is_zero():
    """End-to-end invariant: no audit 'write:*' event may exist without an
    approvals row for its incident covering an earlier timestamp."""
    from database.connection import get_pool

    with get_pool().connection() as conn:
        orphan_writes = conn.execute(
            """
            SELECT count(*) FROM audit_log w
            WHERE w.event LIKE 'write:%'
              AND w.incident_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM approvals a
                  WHERE a.incident_id = w.incident_id
                    AND a.decision IN ('approved', 'edited')
                    AND a.created_at <= w.created_at)
            """
        ).fetchone()[0]
    assert orphan_writes == 0, f"{orphan_writes} unauthorized writes found"
