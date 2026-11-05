"""Page 9: System Observability - real operational stats only.

LLM token/cost tracking requires Langfuse keys (not configured in this
lab); this page shows what IS measured: agent steps, tool usage,
diagnosis latency distribution, outcomes. Nothing is fabricated."""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from components.ui import api_error, card, metric_row, page_chrome, pill  # noqa: E402
from services import api  # noqa: E402

page_chrome("System Observability", "Real measured system behaviour")

try:
    s = api.stats()
    incidents = api.incidents(limit=200)
except Exception as exc:  # noqa: BLE001
    api_error(exc)
    st.stop()

# --- agent step statistics (from persisted timelines) --------------------------
agent_counter: Counter = Counter()
tool_counter: Counter = Counter()
timeline_lengths = []
for inc in incidents:
    actions = inc.get("actions") or {}
    steps = actions.get("timeline", []) if isinstance(actions, dict) else []
    timeline_lengths.append(len(steps))
    for step in steps:
        agent_counter[step.get("agent", "?")] += 1
        for t in step.get("tool_calls", []) or []:
            tool_counter[t] += 1

metric_row([
    ("Incidents analysed", str(len(incidents)), None),
    ("Agent steps recorded", str(sum(agent_counter.values())), None),
    ("MCP tool calls", str(sum(tool_counter.values())), None),
    ("Avg steps / incident",
     f"{(sum(agent_counter.values()) / len(incidents)):.1f}"
     if incidents else "—", None),
])

c1, c2 = st.columns(2)
with c1:
    st.markdown("### Steps by agent")
    if agent_counter:
        st.bar_chart(dict(agent_counter.most_common()))
    else:
        st.info("No step timelines recorded yet.")
with c2:
    st.markdown("### Tool usage")
    if tool_counter:
        st.bar_chart(dict(tool_counter.most_common(12)))
    else:
        st.info("No tool calls recorded in timelines yet.")

st.markdown("### Diagnosis latency (real runs only)")
ttds = [i["time_to_diagnosis_s"] for i in incidents
        if i.get("time_to_diagnosis_s") is not None]
if ttds:
    st.bar_chart({"seconds": {i["id"][:8]: i["time_to_diagnosis_s"]
                              for i in incidents
                              if i.get("time_to_diagnosis_s") is not None}})
    st.markdown(f'n={len(ttds)} · min={min(ttds)}s · median='
                f'{sorted(ttds)[len(ttds)//2]}s · max={max(ttds)}s')
else:
    st.info("No timed diagnoses yet.")

st.markdown("### Outcomes")
for status, count in sorted(s.get("by_status", {}).items()):
    card(f'{pill(status)} &nbsp;{count}')
verdicts = s.get("verification_verdicts", {})
for verdict, count in verdicts.items():
    card(f'{pill(verdict)} &nbsp;{count} — verifier-confirmed')

st.info("LLM token/cost dashboards activate when Langfuse keys are "
        "configured (LANGFUSE_*); the system records what it truly measures "
        "and does not display placeholder statistics.")
