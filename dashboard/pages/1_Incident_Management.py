"""Page 2: Incident Management - searchable, filterable, sortable list."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from components.ui import api_error, card, page_chrome, pill  # noqa: E402
from services import api  # noqa: E402

page_chrome("Incidents", "Search, filter and sort every recorded incident")

try:
    all_incidents = api.incidents(limit=200)
except Exception as exc:  # noqa: BLE001
    api_error(exc)
    st.stop()

left, mid = st.columns([1, 2])
with left:
    status_filter = st.selectbox(
        "Status", ["all", "open", "investigating", "awaiting_approval",
                   "approved", "resolved", "rejected", "failed", "escalated"])
with mid:
    query = st.text_input("Search (alert, service, namespace, cause)",
                          "").strip().lower()
sort_key = st.selectbox("Sort by", ["newest", "oldest", "service",
                                    "status", "time_to_diagnosis"])

rows = all_incidents
if status_filter != "all":
    rows = [r for r in rows if r["status"] == status_filter]
if query:
    rows = [r for r in rows if query in
            f"{r.get('alert_name','')} {r.get('service','')} "
            f"{r.get('namespace','')} {r.get('root_cause') or ''}".lower()]

def sort_fn(r):
    if sort_key == "newest":
        return r.get("created_at", "")
    if sort_key == "oldest":
        return "".join(chr(255 - ord(c)) for c in r.get("created_at", "")[:19])
    if sort_key == "service":
        return r.get("service", "")
    if sort_key == "status":
        return r.get("status", "")
    return -(r.get("time_to_diagnosis_s") or 0)

rows = sorted(rows, key=sort_fn)
st.markdown(f"**{len(rows)}** incident(s)")
for inc in rows:
    ttd = inc.get("time_to_diagnosis_s")
    card(
        f'{pill(inc["status"])} &nbsp;<b>{inc["alert_name"]}</b> · '
        f'{inc["service"]} <span class="ks-muted">in {inc["namespace"]}</span>'
        f' &nbsp;<span class="ks-muted">{inc["created_at"][:19]} · '
        f'diagnosis: {f"{ttd} s" if ttd is not None else "—"} · '
        f'restarts-grouped: {inc.get("alert_labels", {}).get("occurrences", 1)} '
        f'alert(s)</span>'
        f'<br><span class="ks-muted">{(inc.get("root_cause") or "")[:130]}</span>'
        f'<br><code style="color:#9aa4b2">{inc["id"]}</code>')
