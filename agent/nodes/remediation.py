"""Remediation Planner: turns a diagnosis into a VALIDATED, dry-run-checked
plan of allowlisted actions (implementation document 5.1 / 7).

Safety chain (code, not prompts):
1. LLM may only propose actions from the allowlist
2. validate_plan rejects anything out of policy (namespace, params, bounds)
3. every surviving action is server-side dry-run with the executor
   credential (admitted but not persisted)
4. the plan then pauses for human approval - nothing has been executed
"""

from __future__ import annotations

import json
import re

from agent.evidence import store_step_audit
from agent.guardrails import PlanRejected, dry_run_action, validate_plan
from agent.llm import ainvoke_with_retry, build_llm
from agent.state import Action, IncidentState

PLANNER_PROMPT = """You are the Remediation Planner for a Kubernetes incident.
Given the diagnosis and retrieved runbooks, propose AT MOST 2 remediation
actions for a human to approve.

ALLOWED ACTIONS ONLY (anything else will be rejected):
- rollout_restart  {{namespace, target(deployment)}}
- rollout_undo     {{namespace, target(deployment)}}
- scale            {{namespace, target(deployment), params:{{replicas: 1..5}}}}
- delete_pod       {{namespace, target(pod name)}}
- set_resources    {{namespace, target(deployment), params:{{limits:{{cpu?,memory?}}, container?}}}}

Diagnosis: {diagnosis}
Alert: {alert}
Service: {service} in namespace {namespace}
Key evidence:
{evidence}

Runbook guidance:
{runbooks}

Rules:
- Pick the action the runbook marks preferred; prefer the smallest fix.
- risk: low/medium/high (restarts under load = medium; undo = low;
  resource changes = medium).
- If NO allowlisted action addresses the cause, return [] (empty list) - a
  human-only fix is a valid outcome.

Reply with ONLY the JSON array of actions:
[{{"name": "...", "namespace": "{namespace}", "target": "...", "params": {{}},
   "risk": "low", "rationale": "...", "runbook_ref": "runbook name"}}]"""


def _parse_actions(text: str) -> list[dict]:
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(cleaned[start:end + 1])
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


async def remediation_node(state: IncidentState) -> dict:
    report = state.get("report")
    if report is None:
        raise ValueError("remediation requires a diagnosis report")

    incident_id = state["incident_id"]
    namespace = state.get("namespace", "")
    service = state.get("service", "")

    # 1. retrieve runbook guidance (hybrid RAG) unless disabled (E3 switch)
    from common.config import get_settings

    if get_settings().rag_enabled:
        from mcp_servers.knowledge.server import hybrid_search_runbooks
        query = (f"{report.root_cause} {report.category} "
                 f"{state.get('alert', {}).get('labels', {}).get('alertname', '')} "
                 f"{service}")
        runbooks = hybrid_search_runbooks(query, limit=4)
        runbook_text = "\n\n".join(
            f"== {r['runbook']} :: {r['section']}\n{r['content'][:500]}"
            for r in runbooks) or "(no runbooks matched)"
    else:
        runbook_text = "(runbook retrieval disabled for this evaluation run)"

    prompt = PLANNER_PROMPT.format(
        diagnosis=json.dumps(report.model_dump(), default=str),
        alert=json.dumps(state.get("alert", {})),
        service=service, namespace=namespace,
        evidence="\n".join(f"{e.id} [{e.source}] {e.summary}"
                           for e in state.get("evidence", [])[-8:]),
        runbooks=runbook_text,
    )

    # 2. LLM proposal + strict validation (one retry with the rejection reason)
    actions: list[Action] = []
    raw_text = await ainvoke_with_retry(build_llm("primary"), prompt)
    proposed = _parse_actions(raw_text)
    if not proposed:
        # an empty proposal is a VALID outcome: "no allowlisted action fits,
        # human fix required" - skip validation and pause with an empty plan
        step = {"agent": "remediation", "proposed": 0, "kept": 0,
                "dry_runs": [], "note": "no allowlisted action proposed"}
        store_step_audit(incident_id, step)
        return {"plan": [], "plan_dry_run": [], "timeline": [step]}
    try:
        actions = validate_plan(proposed, namespace)
    except PlanRejected as first_rejection:
        retry_prompt = (prompt + f"\n\nYour previous proposal was REJECTED: "
                         f"{first_rejection}. Fix it and reply again with ONLY "
                         f"the corrected JSON array (or []).")
        raw_text = await ainvoke_with_retry(build_llm("primary"), retry_prompt)
        retry_proposed = _parse_actions(raw_text)
        actions = (validate_plan(retry_proposed, namespace)
                   if retry_proposed else [])

    # 3. server-side dry run each action; drop any that fail admission
    plan: list[Action] = []
    dry_runs: list[dict] = []
    for action in actions:
        result = dry_run_action(action)
        if result.get("ok"):
            plan.append(action)
            dry_runs.append({"target": action.target, "name": action.name,
                             **result})
        else:
            dry_runs.append({"target": action.target, "name": action.name,
                             "dropped": True, **result})

    step = {"agent": "remediation",
            "proposed": len(actions), "kept": len(plan),
            "dry_runs": dry_runs}
    store_step_audit(incident_id, step)
    return {"plan": plan, "plan_dry_run": dry_runs, "timeline": [step]}
