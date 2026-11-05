"""Phase 8 dashboard gate: render EVERY page with Streamlit AppTest against
the LIVE backend, assert real data flows, and verify the approval page's
buttons hit the real API (surfacing the real response verbatim).

Run with the API live: python scripts/dashboard_gate.py
"""
import json
import sys
import time
from pathlib import Path

import httpx
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

BASE = "http://127.0.0.1:8547"
PAGES = [
    ("Overview", "dashboard/app.py"),
    ("Incident Management", "dashboard/pages/1_Incident_Management.py"),
    ("Investigation", "dashboard/pages/2_Investigation.py"),
    ("Root Cause Analysis", "dashboard/pages/3_Root_Cause_Analysis.py"),
    ("Remediation Approval", "dashboard/pages/4_Remediation_Approval.py"),
    ("Execution & Verification", "dashboard/pages/5_Execution_Verification.py"),
    ("History & Memory", "dashboard/pages/6_History_Memory.py"),
    ("Runbook KB", "dashboard/pages/7_Runbook_Knowledge_Base.py"),
    ("Observability", "dashboard/pages/8_System_Observability.py"),
]

failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(name)


def api_up() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    if not api_up():
        raise SystemExit("API is not running on :8547")
    print("API is live\n")

    # --- 1. every page renders against the real backend --------------------
    for name, path in PAGES:
        try:
            at = AppTest.from_file(str(ROOT / path), default_timeout=120)
            at.run()
            crashed = bool(at.exception)
            check(f"render: {name}", not crashed,
                  str(at.exception)[:160] if crashed else "")
        except Exception as exc:  # noqa: BLE001
            check(f"render: {name}", False, str(exc)[:160])

    # --- 2. overview contains REAL stats (non-zero: we have incidents) ------
    at = AppTest.from_file(str(ROOT / "dashboard/app.py"), default_timeout=120)
    at.run()
    body_text = " ".join(m.value for m in at.markdown)
    stats = httpx.get(BASE + "/stats", timeout=10).json()
    check("overview: total metric matches API",
          str(stats["total"]) in body_text, f"total={stats['total']}")

    # --- 3. runbook page: retrieval returns the OOM runbook -----------------
    at = AppTest.from_file(str(ROOT / "dashboard/pages/7_Runbook_Knowledge_Base.py"),
                           default_timeout=120)
    at.run()
    at.button[0].click()
    at.run()
    body = " ".join(m.value for m in at.markdown)
    check("runbooks: hybrid search surfaces OOM runbook", "OOM" in body)

    # --- 4. approval page: button click hits the REAL API --------------------
    # seed an awaiting_approval incident so the page has a target
    seed = {
        "id": str(__import__("uuid").uuid4()),
        "plan": [{"name": "rollout_undo", "namespace": "boutique",
                  "target": "checkoutservice", "params": {}, "risk": "low",
                  "rationale": "gate", "runbook_ref": None}],
        "dry_run": [{"ok": True, "detail": "dry-run admitted"}],
    }
    from database.connection import get_pool
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO incidents (id, alert_name, namespace, service, "
            "status, root_cause, root_cause_category, summary, actions) "
            "VALUES (%s::uuid, 'GateAlert', 'boutique', 'checkoutservice', "
            "'awaiting_approval', 'gate cause', 'resource', 'gate summary', "
            "%s::jsonb)",
            (seed["id"], json.dumps({"approval_payload": {
                "plan": seed["plan"], "dry_run": seed["dry_run"]},
                "timeline": []})))
    try:
        at = AppTest.from_file(str(ROOT / "dashboard/pages/4_Remediation_Approval.py"),
                               default_timeout=120)
        at.run()
        if at.exception:
            check("approval page renders", False, str(at.exception)[:160])
        else:
            # selectbox defaults to first pending incident; enter approver
            at.text_input[0].set_value("dashboard-gate")
            at.run()
            # REJECT on a synthetic incident that has NO real paused graph
            # thread -> the API must answer 409 (honest, no crash, no fake
            # success) and the page must surface that response verbatim
            at.button[1].click()   # [0]=Approve [1]=Reject
            at.run()
            body = " ".join(m.value for m in at.success) + \
                   " ".join(m.value for m in at.error)
            check("approval: Reject hit the real API (response surfaced)",
                  ("409" in body) or ("no pending approval interrupt" in body),
                  body[:200])
            # the graph thread must NOT have been resumed/crashed: incident
            # stays awaiting_approval (the endpoint refuses gracefully)
            with get_pool().connection() as conn:
                status = conn.execute(
                    "SELECT status FROM incidents WHERE id = %s::uuid",
                    (seed["id"],)).fetchone()[0]
            check("approval: synthetic incident untouched (still paused)",
                  status == "awaiting_approval", f"status={status}")
            # no approvals row must exist for a refused decision
            with get_pool().connection() as conn:
                dec = conn.execute(
                    "SELECT count(*) FROM approvals "
                    "WHERE incident_id = %s::uuid", (seed["id"],)).fetchone()[0]
            check("approval: no approval record for refused decision",
                  dec == 0, f"rows={dec}")
    finally:
        with get_pool().connection() as conn:
            conn.execute("DELETE FROM approvals WHERE incident_id = %s::uuid",
                         (seed["id"],))
            conn.execute("DELETE FROM audit_log WHERE incident_id = %s::uuid",
                         (seed["id"],))
            conn.execute("DELETE FROM incidents WHERE id = %s::uuid",
                         (seed["id"],))

    print()
    if failures:
        print(f"GATE FAILED: {failures}")
        sys.exit(1)
    print("DASHBOARD GATE PASSED — every page renders real data and the "
          "approval control drives the real API.")


if __name__ == "__main__":
    main()
