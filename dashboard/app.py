"""KubeSentra dashboard entry point: Overview (page 1).
Run: streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from components.ui import api_error, card, metric_row, page_chrome, pill  # noqa: E402
from services import api  # noqa: E402

page_chrome("Overview", "KubeSentra — Kubernetes incident response")

try:
    s = api.stats()
except Exception as exc:  # noqa: BLE001
    api_error(exc)
    st.stop()

metric_row([
    ("Total incidents", str(s["total"]), None),
    ("Active", str(s["active"]), "open + investigating"),
    ("Pending approvals", str(s["awaiting_approval"]), "human gate"),
    ("Resolved", str(s["resolved"]), None),
    ("Failed / escalated", str(s["failed"]), None),
])

ttd = s.get("avg_time_to_diagnosis_s")
rate = s.get("remediation_success_rate")
metric_row([
    ("Avg time to diagnosis", f"{ttd:.0f} s" if ttd is not None else "—",
     "alert → diagnosis (real runs only)"),
    ("Remediation attempts", str(s.get("remediation_attempts", 0)),
     "actions executed via approval"),
    ("Remediation success", f"{rate * 100:.0f}%" if rate is not None else "—",
     "verifier-confirmed RESOLVED / executed"),
    ("Verification verdicts", str(s.get("verification_verdicts", {})) or "{}",
     None),
])

st.markdown("### Recent activity")
for inc in s.get("recent", [])[:10]:
    card(
        f'{pill(inc["status"])} &nbsp;<b>{inc["alert_name"]}</b> · '
        f'{inc["service"]} <span class="ks-muted">in {inc["namespace"]} · '
        f'{inc["created_at"][:19]} · root cause: '
        f'{(inc.get("root_cause") or "—")[:90]}</span>')
if not s.get("recent"):
    st.info("No incidents recorded yet.")
