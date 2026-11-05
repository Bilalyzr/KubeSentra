"""Page 5: Remediation Approval - the human gate.

Approve / Edit / Reject call the REAL token-authenticated API; responses
(including errors) are surfaced verbatim. Nothing is simulated.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from components.ui import api_error, card, page_chrome, pill  # noqa: E402
from services import api  # noqa: E402

page_chrome("Remediation Approval", "Human-in-the-loop decision gate")

try:
    pending = api.incidents(status="awaiting_approval", limit=50)
    others = [i for i in api.incidents(limit=100)
              if i["status"] in ("approved", "rejected", "resolved")]
except Exception as exc:  # noqa: BLE001
    api_error(exc)
    st.stop()

if not pending:
    st.success("No incidents awaiting approval.")
    st.markdown("### Recent decisions")
    for inc in others[:5]:
        card(f'{pill(inc["status"])} {inc["alert_name"]} · {inc["service"]}')
    st.stop()

chosen = st.selectbox(
    "Incident awaiting approval",
    [f'{i["alert_name"]} · {i["service"]} · {i["created_at"][:16]}'
     for i in pending])
inc = pending[[f'{i["alert_name"]} · {i["service"]} · {i["created_at"][:16]}'
               for i in pending].index(chosen)]

st.markdown(f'{pill(inc["status"])} **{inc["alert_name"]}** · '
            f'{inc["service"]} in `{inc["namespace"]}`')
st.markdown(f'**Diagnosis:** {inc.get("root_cause") or "—"} '
            f'{pill(inc.get("root_cause_category") or "")}')
st.markdown(f'**Explanation:** {(inc.get("summary") or "")[:400]}')

payload = api.approval_payload(inc)
plan = payload.get("plan") or []
dry = payload.get("dry_run") or []

st.markdown("### Proposed plan")
if not plan:
    st.info("The planner proposed NO allowlisted action (policy-dropped or "
            "human-only fix). You can supply one via Edit, or Reject.")
for idx, action in enumerate(plan):
    dr = dry[idx] if idx < len(dry) else {}
    card(f'<b>{action["name"]}</b> → <code>{action["target"]}</code> '
         f'in <code>{action["namespace"]}</code>'
         f'<br>params: <code>{json.dumps(action.get("params", {}))}</code> · '
         f'risk: <b>{action.get("risk")}</b>'
         f'<br><span class="ks-muted">{action.get("rationale", "")}</span>'
         f'<br>runbook: <i>{action.get("runbook_ref") or "—"}</i> · '
         f'dry-run: <b style="color:{"#2ecc71" if dr.get("ok") else "#e74c3c"}">'
         f'{"admitted" if dr.get("ok") else (dr.get("detail") or "failed")}'
         f'</b>')

approver = st.text_input("Approver name", value="", max_chars=100)
st.markdown('<span class="ks-muted">Decision token is read from the '
            'environment (APPROVAL_TOKEN) - never entered here.</span>',
            unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1:
    approve_clicked = st.button("✅ Approve", type="primary", use_container_width=True,
                                disabled=not approver.strip())
with col2:
    reject_clicked = st.button("⛔ Reject", use_container_width=True,
                               disabled=not approver.strip())
with col3:
    edit_mode = st.toggle("✏️ Edit mode")

edited_plan_text = ""
edit_clicked = False
if edit_mode:
    st.markdown("### Edited plan (JSON array - will be RE-VALIDATED by policy)")
    edited_plan_text = st.text_area(
        "plan", value=json.dumps(plan, indent=1), height=220)
    edit_clicked = st.button("Submit edited plan", type="primary",
                             disabled=not approver.strip())

if approve_clicked:
    code, body = api.post_decision(inc["id"], "approved", None, approver)
    if code == 200:
        st.success(f"Approved ({code}). Execution and verification follow.")
    else:
        st.error(f"Rejected by backend ({code}): {json.dumps(body)[:400]}")

if reject_clicked:
    code, body = api.post_decision(inc["id"], "rejected", None, approver)
    if code == 200:
        st.success(f"Rejected ({code}). A postmortem will be written.")
    else:
        st.error(f"Rejected by backend ({code}): {json.dumps(body)[:400]}")

if edit_clicked:
    try:
        plan_obj = json.loads(edited_plan_text)
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON: {exc}")
        st.stop()
    code, body = api.post_decision(inc["id"], "edited", plan_obj, approver)
    if code == 200:
        st.success(f"Edited plan accepted ({code}) - re-validated and "
                   "dry-run, then executed.")
    else:
        st.error(f"Backend response ({code}): {json.dumps(body)[:400]}")
