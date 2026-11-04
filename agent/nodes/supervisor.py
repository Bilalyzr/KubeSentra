"""Supervisor: decides which specialist investigates next.

Hard routing rules run FIRST (spec 4.3) and are pure/testable; the LLM only
chooses when the hard rules defer. Loop-guard prevents asking one specialist
forever.
"""

from __future__ import annotations

import json
import re

from agent.llm import ainvoke_with_retry, build_llm
from agent.state import IncidentState, evidence_ids, filter_valid_ids, parse_hypotheses
from common.config import get_settings

ALLOWED_AGENTS = ("metrics_agent", "logs_agent", "k8s_agent")
SPECIALIST_TITLES = {
    "metrics_agent": "Metrics specialist (Prometheus)",
    "logs_agent": "Logs specialist (Loki)",
    "k8s_agent": "Kubernetes state specialist",
}

SUPERVISOR_PROMPT = """You are the Supervisor coordinating a Kubernetes incident
investigation. Based on the current hypotheses, evidence and questions already
asked, choose the ONE specialist whose evidence would most change the ranking,
and write ONE specific question for it to answer.

Specialists: metrics_agent (CPU/memory/throttling/restarts metrics),
logs_agent (error patterns from logs), k8s_agent (pods, events, rollouts).

Hypotheses (JSON, confidence 0-1):
{hypotheses}

Evidence so far:
{evidence}

Questions already asked (do NOT repeat them):
{asked}

Reply with ONLY this JSON:
{{"next_agent": "metrics_agent|logs_agent|k8s_agent",
   "question": "one specific, answerable question",
   "rationale": "one sentence"}}"""


def decide_route(state: IncidentState) -> str:
    """Pure hard-routing rules (no LLM). Returns 'diagnose', 'escalate'
    or 'llm' (defer to the LLM supervisor)."""
    hypotheses = state.get("hypotheses") or []
    steps = state.get("steps_used", 0)
    settings = get_settings()

    if steps >= settings.max_investigation_steps:
        return "diagnose" if any(h.confidence >= 0.5 for h in hypotheses) \
            else "escalate"

    if hypotheses:
        top = max(hypotheses, key=lambda h: h.confidence)
        if top.confidence >= 0.8:
            by_id = {e.id: e for e in state.get("evidence", [])}
            sources = {by_id[i].source for i in (top.supporting or [])
                       if i in by_id}
            if len(sources) >= 2:
                return "diagnose"
    return "llm"


def _asked_questions(state: IncidentState) -> list[str]:
    return [s.get("question", "") for s in state.get("timeline", [])
            if s.get("question")]


def _loop_guard(state: IncidentState, choice: str) -> str:
    """If the same specialist was chosen 3+ times consecutively, force a
    different one (or diagnose if we have anything to diagnose)."""
    recent = [s.get("agent") for s in state.get("timeline", [])[-3:]]
    if len(recent) >= 3 and recent.count(choice) >= 3:
        hypotheses = state.get("hypotheses") or []
        if any(h.confidence >= 0.5 for h in hypotheses):
            return "diagnose"
        others = [a for a in ALLOWED_AGENTS if a != choice]
        return others[len(recent) % len(others)]
    return choice


async def supervisor_node(state: IncidentState) -> dict:
    route = decide_route(state)
    timeline_entry = {"agent": "supervisor", "route": route}

    if route in ("diagnose", "escalate"):
        return {"next_agent": route, "timeline": [timeline_entry]}

    hypotheses = state.get("hypotheses") or []
    evidence = state.get("evidence", [])
    prompt = SUPERVISOR_PROMPT.format(
        hypotheses=json.dumps([h.model_dump() for h in hypotheses], indent=1),
        evidence="\n".join(f"{e.id} [{e.source}] {e.summary}" for e in evidence)
        or "(none yet)",
        asked="\n".join(f"- {q}" for q in _asked_questions(state)) or "(none)",
    )
    llm = build_llm("primary")
    text = await ainvoke_with_retry(llm, prompt)

    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        decision = json.loads(match.group(0)) if match else {}
        choice = decision.get("next_agent", "")
        question = decision.get("question", "").strip()
    except json.JSONDecodeError:
        choice, question = "", ""

    valid_ids = evidence_ids(state)
    if choice not in ALLOWED_AGENTS or not question:
        # degraded fallback: rotate through specialists deterministically
        choice = ALLOWED_AGENTS[state.get("steps_used", 0) % len(ALLOWED_AGENTS)]
        question = f"Investigate {state.get('service', 'the service')} for your area."

    choice = _loop_guard(state, choice)
    timeline_entry.update({"choice": choice, "question": question})
    return {"next_agent": choice, "next_question": question,
            "timeline": [timeline_entry]}


def route_from_supervisor(state: IncidentState) -> str:
    """Conditional-edge router: supervisor's decision is final here."""
    nxt = state.get("next_agent", "escalate")
    return nxt if nxt in (*ALLOWED_AGENTS, "diagnose", "escalate") else "escalate"
