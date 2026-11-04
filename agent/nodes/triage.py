"""Triage agent: scope the incident, gather initial context programmatically
(past incidents + pod snapshot) and form 2-4 initial hypotheses."""

from __future__ import annotations

import json

from agent.evidence import record_evidence, store_step_audit
from agent.llm import ainvoke_with_retry, build_llm
from agent.state import IncidentState, evidence_ids, filter_valid_ids, parse_hypotheses

TRIAGE_PROMPT = """You are the Triage agent for a Kubernetes incident.

Firing alert: {alert}
Namespace: {namespace} | Service: {service}

Current pod snapshot for the service:
{pods}

Similar past incidents (hints to VERIFY, never copy as answers):
{similar}

Produce 2-4 initial root-cause hypotheses covering the distinct plausible
explanations. Assign initial confidences (0-1) and cite any evidence IDs you
used (E1 = past incidents, E2 = pod snapshot). Do not confirm anything yet.

Reply with ONLY the JSON array:
[{{"cause": "...", "category": "resource|config|application|image|network|dependency|change|other",
   "confidence": 0.0, "supporting": [], "refuting": []}}]"""


def _compact_service_lines(pods_text: str, service: str) -> str:
    lines = [ln for ln in pods_text.splitlines() if service in ln]
    return "\n".join(lines[:12]) or pods_text.splitlines()[:12].__str__()


async def triage_node(state: IncidentState) -> dict:
    incident_id = state["incident_id"]
    alert = state.get("alert", {})
    namespace = state.get("namespace", "")
    service = state.get("service", "")
    labels = alert.get("labels", {})

    # programmatic context - deterministic inputs, no LLM needed
    from mcp_servers.k8s_read.server import list_pods
    from mcp_servers.knowledge.server import (search_incidents,
                                               search_similar_incidents)

    query = f"{labels.get('alertname', '')} {service}".strip()
    try:
        similar_raw = search_similar_incidents(query=query, service=service,
                                               limit=3)
    except Exception:  # noqa: BLE001 - memory must never break triage
        similar_raw = search_incidents(query=query, service=service, limit=3)
    pods_raw = list_pods(namespace=namespace)

    similar_lines = [ln for ln in similar_raw.splitlines()
                     if ln.strip() and not ln.startswith("(")][:3]
    if similar_lines:
        first = similar_lines[0]
        cause_part = "; ".join(p.strip() for p in first.split("|")[2:4])
        memory_summary = f"Past incidents (hints to verify): {cause_part or first}"
    else:
        memory_summary = "No similar past incidents found."
    evidence = [
        record_evidence(
            incident_id, "memory",
            summary=memory_summary,
            raw_output=similar_raw, existing_count=0,
        ),
        record_evidence(
            incident_id, "k8s",
            summary="Initial pod snapshot:\n" + _compact_service_lines(pods_raw, service),
            raw_output=pods_raw, existing_count=1,
        ),
    ]

    prompt = TRIAGE_PROMPT.format(
        alert=json.dumps(alert), namespace=namespace, service=service,
        pods=_compact_service_lines(pods_raw, service),
        similar="\n".join(similar_lines) or "(none)",
    )
    llm = build_llm("primary")
    text = await ainvoke_with_retry(llm, prompt)
    hypotheses = parse_hypotheses(text)
    valid = evidence_ids(evidence)
    for i, hyp in enumerate(hypotheses):
        hypotheses[i] = hyp.model_copy(update={
            "supporting": filter_valid_ids(hyp.supporting, valid),
            "refuting": filter_valid_ids(hyp.refuting, valid),
        })

    step = {"agent": "triage", "evidence_added": [e.id for e in evidence],
            "hypotheses": len(hypotheses)}
    store_step_audit(incident_id, step)
    return {"evidence": evidence, "hypotheses": hypotheses,
            "similar_incidents": [{"summary": ln} for ln in similar_lines],
            "steps_used": 0, "timeline": [step]}
