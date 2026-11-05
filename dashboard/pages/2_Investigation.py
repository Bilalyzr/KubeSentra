"""Page 3: Incident Investigation - timeline, evidence, hypotheses."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from components.ui import api_error, card, page_chrome, pill  # noqa: E402
from services import api  # noqa: E402

page_chrome("Investigation", "Agent execution timeline, evidence and hypotheses")

try:
    incidents = api.incidents(limit=100)
except Exception as exc:  # noqa: BLE001
    api_error(exc)
    st.stop()

if not incidents:
    st.info("No incidents yet.")
    st.stop()

options = {f'{i["alert_name"]} · {i["service"]} · {i["status"]} · '
           f'{i["created_at"][:16]}': i["id"] for i in incidents}
chosen = st.selectbox("Incident", list(options))
inc = api.incident(options[chosen])

st.markdown(f'{pill(inc["status"])} **{inc["alert_name"]}** on '
            f'**{inc["service"]}** in `{inc["namespace"]}`')
meta = inc.get("alert_labels") or {}
st.markdown(f'<span class="ks-muted">alert labels: '
            f'<code>{json.dumps(meta.get("labels", {}))}</code> · '
            f'occurrences: {meta.get("occurrences", 1)}</span>',
            unsafe_allow_html=True)

tab_timeline, tab_evidence, tab_hyps = st.tabs(
    ["Agent timeline", "Evidence", "Hypotheses"])

with tab_timeline:
    events = api.timeline(inc["id"])
    # graph step timeline (richer) + audit events
    actions = inc.get("actions") or {}
    steps = actions.get("timeline", []) if isinstance(actions, dict) else []
    if steps:
        for s in steps:
            q = s.get("question")
            tools = s.get("tool_calls")
            card(f'<b>{s.get("agent", "?")}</b>'
                 + (f' — {q}' if q else '')
                 + (f' <span class="ks-muted">tools: {tools}</span>' if tools else '')
                 + (f' <span class="ks-muted">evidence: '
                    f'{s.get("evidence_added")}</span>'
                    if s.get("evidence_added") else ""))
    st.markdown("**Audit log**")
    for ev in events:
        st.markdown(f'- `{ev["time"][:19]}` **{ev["actor"]}** · {ev["event"]}')

with tab_evidence:
    for ev in api.evidence(inc["id"]):
        st.markdown(
            f'<div class="ks-evidence"><b>{ev["id"]}</b> '
            f'<span class="ks-muted">[{ev["source"]}] {ev["created"][:19]}</span>'
            f'<br>{ev["raw"][:400]}</div>', unsafe_allow_html=True)

with tab_hyps:
    payload = api.approval_payload(inc)
    hyps = payload.get("hypotheses") or []
    if not hyps:
        st.info("No persisted hypotheses for this incident "
                "(hypotheses are stored at the approval pause).")
    for h in sorted(hyps, key=lambda x: -x.get("confidence", 0)):
        card(f'<b>{h.get("confidence", 0):.2f}</b> · {h.get("cause", "?")}'
             f' {pill(str(h.get("category", "other")))}'
             f'<br><span class="ks-muted">supports: '
             f'{h.get("supporting", [])} · refutes: {h.get("refuting", [])}'
             '</span>')
