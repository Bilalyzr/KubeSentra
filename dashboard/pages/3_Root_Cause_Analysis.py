"""Page 4: Root Cause Analysis - top cause, alternatives, evidence grounding."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from components.ui import api_error, card, page_chrome, pill  # noqa: E402
from services import api  # noqa: E402

page_chrome("Root Cause Analysis", "Evidence-grounded diagnosis")

try:
    incidents = api.incidents(limit=100)
except Exception as exc:  # noqa: BLE001
    api_error(exc)
    st.stop()

diagnosed = [i for i in incidents if i.get("root_cause")]
if not diagnosed:
    st.info("No diagnosed incidents yet.")
    st.stop()

options = {f'{i["alert_name"]} · {i["service"]} · {i["created_at"][:16]}':
           i["id"] for i in diagnosed}
chosen = st.selectbox("Incident", list(options))
inc = api.incident(options[chosen])

st.markdown(f'{pill(inc["status"])} **{inc["alert_name"]}** · '
            f'{inc["service"]} · category '
            f'{pill(inc.get("root_cause_category") or "other")}')

# the explanation text is persisted at diagnosis/awaiting_approval time
summary = inc.get("summary") or ""
is_postmortem = summary.startswith("{")

left, right = st.columns([3, 2])
with left:
    st.markdown("### Most likely root cause")
    st.markdown(inc.get("root_cause") or "—")
    st.markdown("### Explanation")
    if is_postmortem:
        try:
            doc = json.loads(summary)
            st.markdown(doc.get("root_cause") or "—")
        except json.JSONDecodeError:
            st.markdown(summary[:600])
    else:
        st.markdown(summary[:600])

with right:
    st.markdown("### Evidence grounding")
    if is_postmortem:
        try:
            doc = json.loads(summary)
            for ref in doc.get("evidence_references", []):
                st.markdown(
                    f'<div class="ks-evidence"><b>{ref["id"]}</b> '
                    f'<span class="ks-muted">[{ref["source"]}]</span><br>'
                    f'{ref["summary"]}</div>', unsafe_allow_html=True)
            st.markdown(f'**Verification:** {pill(doc.get("verification") or "")}'
                        .replace("None", "—"), unsafe_allow_html=True)
        except json.JSONDecodeError:
            st.write("—")
    else:
        # diagnosis-time summary carries the [confidence; evidence: ...] tag
        if "evidence:" in summary:
            st.code(summary[summary.index("evidence:"):][:200])
        st.info("Full evidence references appear in the postmortem after "
                "the approval workflow completes.")

    st.markdown("### Alternatives considered")
    payload = api.approval_payload(inc)
    hyps = payload.get("hypotheses") or []
    for h in sorted(hyps, key=lambda x: -x.get("confidence", 0))[1:]:
        card(f'{h.get("confidence", 0):.2f} · {h.get("cause", "?")} '
             f'{pill(str(h.get("category", "other")))}')
    if len(hyps) <= 1:
        st.markdown('<span class="ks-muted">—</span>', unsafe_allow_html=True)
