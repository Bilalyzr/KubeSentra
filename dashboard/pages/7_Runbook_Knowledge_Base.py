"""Page 8: Runbook Knowledge Base - browse + hybrid retrieval."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from components.ui import api_error, card, page_chrome  # noqa: E402
from services import api  # noqa: E402

page_chrome("Runbook Knowledge Base",
            "23 runbooks · hybrid pgvector + full-text retrieval (RRF)")

st.markdown("### Retrieval")
q = st.text_input("Search the knowledge base",
                  "pod OOMKilled restarts memory limit")
if st.button("Search") and len(q.strip()) >= 2:
    try:
        results = api.runbook_search(q)
    except Exception as exc:  # noqa: BLE001
        api_error(exc)
        st.stop()
    for r in results:
        card(f'<b>{r["runbook"]}</b> :: {r["section"]} '
             f'<span class="ks-muted">score {r.get("score", 0)}</span>'
             f'<br>{r["content"][:320]}')
    if not results:
        st.info("No matches.")

st.markdown("### All runbooks")
try:
    books = api.runbooks()
except Exception as exc:  # noqa: BLE001
    api_error(exc)
    st.stop()
names = [b["name"] for b in books]
chosen = st.selectbox("Runbook", names)
book = next(b for b in books if b["name"] == chosen)
st.markdown(f'**Tags:** {", ".join(book["tags"]) or "—"}')
for section in book["sections"]:
    with st.expander(section["section"]):
        st.markdown(section["content"])
