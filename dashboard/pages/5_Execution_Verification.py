"""Page 6: Execution & Verification - what ran, what the cluster said,
what the verifier concluded."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from components.ui import api_error, card, page_chrome, pill  # noqa: E402
from services import api  # noqa: E402

page_chrome("Execution & Verification",
            "Approved actions, Kubernetes results, verifier verdict")

try:
    incidents = [i for i in api.incidents(limit=100)
                 if i["status"] in ("approved", "resolved", "rejected",
                                    "failed", "escalated")]
except Exception as exc:  # noqa: BLE001
    api_error(exc)
    st.stop()

if not incidents:
    st.info("No incidents have passed the approval stage yet.")
    st.stop()

options = {f'{i["alert_name"]} · {i["service"]} · {i["status"]} · '
           f'{i["created_at"][:16]}': i["id"] for i in incidents}
chosen = st.selectbox("Incident", list(options))
inc = api.incident(options[chosen])

try:
    pm = api.postmortem(inc["id"]) or {}
except Exception as exc:  # noqa: BLE001 - surface the real error, don't crash
    api_error(exc)
    pm = {}
doc = pm.get("postmortem") or {}

st.markdown(f'{pill(inc["status"])} **{inc["alert_name"]}** · {inc["service"]}')

rem = doc.get("remediation") or {}
st.markdown("### Execution")
if not rem:
    payload = api.approval_payload(inc)
    st.info(f"No executed remediation recorded. Plan at decision time: "
            f"{[a.get('name') for a in payload.get('plan', [])] or 'empty'}")
else:
    st.markdown(f'Executed: **{"yes" if rem.get("executed") else "no"}**')
    for r in rem.get("results", []):
        ok = r.get("ok")
        card(f'<b>{r.get("action")}</b> → <code>{r.get("target")}</code> · '
             f'stage: {r.get("stage") or "executed"} · '
             f'<b style="color:{"#2ecc71" if ok else "#e74c3c"}">'
             f'{"OK" if ok else "FAILED"}</b>'
             f'<br><span class="ks-muted">{(r.get("detail") or "")[:220]}'
             f'</span>')

st.markdown("### Verification")
verdict = doc.get("verification")
if verdict:
    st.markdown(f'Verdict: {pill(verdict)}')
    checks = doc.get("verification_checks") or {}
    c1, c2, c3 = st.columns(3)
    c1.metric("Pods ready", "yes" if checks.get("pods_ready") else "no")
    c2.metric("Rollout wait", f'{checks.get("rollout_wait_s", "—")} s')
    c3.metric("Original alert firing",
              "yes" if checks.get("alert_still_firing") else "no")
else:
    st.info("No verification recorded (incident may not have reached the "
            "executor/verifier stage).")

st.markdown("### Approval record")
approval = doc.get("approval")
if approval:
    st.markdown(f'**{approval.get("approver")}** — {pill(approval.get("decision", ""))} '
                f'<span class="ks-muted">at {str(approval.get("approved_at"))[:19]}</span>',
                unsafe_allow_html=True)
    st.json(approval.get("plan") or {})
