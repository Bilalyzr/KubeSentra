"""Human approval interrupt (implementation document 4.6).

The graph PAUSES here with the diagnosis, the validated plan and each
action's server-side dry-run result. It resumes only via
POST /incidents/{id}/decision with a valid approval token.

Edited plans are RE-VALIDATED with the same code path as the original.
An invalid edit does NOT crash the workflow: because LangGraph checkpoints
the resume value into the pending task, raising would brick the thread -
instead the node re-interrupts with the validation error so the human can
submit a corrected plan. After 3 invalid attempts it fails safe to
'rejected' (nothing has executed).
"""

from __future__ import annotations

from langgraph.types import interrupt

from agent.guardrails import dry_run_action, validate_plan
from agent.state import IncidentState

MAX_INVALID_EDITS = 3


def route_after_approval(state: IncidentState) -> str:
    """Phase 7 wiring: approved/edited -> execute; rejected -> postmortem."""
    if state.get("approval") in ("approved", "edited"):
        return "execute"
    return "postmortem"


async def approval_node(state: IncidentState) -> dict:
    report = state.get("report")
    base_payload = {
        "incident_id": state["incident_id"],
        "service": state.get("service"),
        "namespace": state.get("namespace"),
        "root_cause": report.root_cause if report else None,
        "category": report.category if report else None,
        "confidence": report.confidence if report else None,
        "supporting_evidence": report.supporting_evidence if report else [],
        "plan": [a.model_dump() for a in state.get("plan", [])],
        "dry_run": state.get("plan_dry_run", []),
    }

    invalid_attempts = 0
    payload = dict(base_payload)
    while True:
        decision = interrupt(payload)  # durable pause (checkpointer-backed)

        status = (decision or {}).get("status")
        if status not in ("approved", "edited", "rejected"):
            payload = {**base_payload,
                       "validation_error": f"invalid status {status!r}; use "
                                           "approved/edited/rejected"}
            continue

        if status == "rejected":
            return {"approval": "rejected",
                    "plan": state.get("plan", []),
                    "timeline": [{"agent": "approval", "decision": "rejected"}]}

        if status == "approved":
            return {"approval": "approved",
                    "plan": state.get("plan", []),
                    "plan_dry_run": state.get("plan_dry_run", []),
                    "timeline": [{"agent": "approval", "decision": "approved",
                                  "plan_size": len(state.get("plan", []))}]}

        # edited: re-validate with identical rules
        try:
            plan = validate_plan((decision or {}).get("plan") or [],
                                 state.get("namespace"))
        except Exception as exc:  # noqa: BLE001 - PlanRejected and friends
            invalid_attempts += 1
            if invalid_attempts >= MAX_INVALID_EDITS:
                return {"approval": "rejected",
                        "plan": state.get("plan", []),
                        "timeline": [{"agent": "approval",
                                      "decision": "rejected",
                                      "reason": f"{MAX_INVALID_EDITS} invalid "
                                                f"edits; last error: {exc}"}]}
            payload = {**base_payload,
                       "validation_error": f"edited plan rejected: {exc} - "
                                           "submit a corrected plan"}
            continue

        dry_runs = [{"target": a.target, "name": a.name, **dry_run_action(a)}
                    for a in plan]
        return {"approval": "edited", "plan": plan, "plan_dry_run": dry_runs,
                "timeline": [{"agent": "approval", "decision": "edited",
                              "plan_size": len(plan)}]}
