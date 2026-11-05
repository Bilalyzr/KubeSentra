"""Page 7: Incident History & Memory - searchable past incidents +
similar-incident retrieval (episodic memory via the knowledge service)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from components.ui import api_error, card, page_chrome, pill  # noqa: E402
from services import api  # noqa: E402

page_chrome("History & Memory", "Past incidents and episodic-memory retrieval")

tab_history, tab_similar = st.tabs(["Incident history", "Similar incidents"])

with tab_history:
    query = st.text_input("Search history (alert/service/cause)", "").lower()
    try:
        rows = api.incidents(limit=200)
    except Exception as exc:  # noqa: BLE001
        api_error(exc)
        st.stop()
    if query:
        rows = [r for r in rows if query in
                f"{r.get('alert_name','')} {r.get('service','')} "
                f"{r.get('root_cause') or ''}".lower()]
    st.markdown(f"**{len(rows)}** incident(s)")
    for inc in rows:
        card(f'{pill(inc["status"])} <b>{inc["alert_name"]}</b> · '
             f'{inc["service"]} · {inc["created_at"][:16]}'
             f'<br><span class="ks-muted">cause: '
             f'{(inc.get("root_cause") or "—")[:110]}</span>')

with tab_similar:
    st.markdown("Retrieval uses the same embedding-based memory the Triage "
                "agent uses (bge-small vectors over past incidents).")
    q = st.text_input("Query", "pod restarting out of memory")
    if st.button("Retrieve similar incidents") and q.strip():
        # the knowledge MCP search runs in-process via the API's runbook
        # search; for incidents we reuse the MCP server function through a
        # lightweight call - exposed via /runbooks/search? No: incidents
        # memory search is an MCP tool. Call it directly through the
        # backend's knowledge service (same process semantics).
        from mcp_servers.knowledge.server import similar_incidents

        results = similar_incidents(q, service=None, limit=5)
        if not results:
            st.info("No similar incidents found.")
        for r in results:
            card(f'<b>{r.get("alert_name", "?")}</b> · {r.get("service")} · '
                 f'sim {r.get("similarity")}'
                 f'<br><span class="ks-muted">'
                 f'{(r.get("root_cause") or "")[:140]}</span>')
