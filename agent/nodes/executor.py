"""Executor: runs the APPROVED plan through the k8s-write MCP server.

Safety chain (implementation document 7):
- refuses to run unless state.approval is approved/edited
- one action at a time; stops the plan on the first failure
- immediately before each action: re-validate (same guardrails) AND a fresh
  server-side dry run (cluster state may have changed since approval)
- writes go through the k8s-write MCP server (executor credential,
  boutique-only Role) - never an LLM tool call, never arbitrary commands
- every step audited; duplicate execution guarded via the execution record
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from agent.guardrails import PlanRejected, dry_run_action, validate_action
from agent.state import Action, IncidentState

ROOT = Path(__file__).resolve().parents[2]

# action.name -> k8s-write MCP tool name
TOOL_MAP = {
    "rollout_restart": "rollout_restart",
    "rollout_undo": "rollout_undo",
    "scale": "scale_deployment",
    "delete_pod": "delete_pod",
    "set_resources": "set_resources",
}


async def call_write_server(action: Action) -> dict:
    """Invoke ONE action on the k8s-write MCP server over stdio."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["K8S_WRITE_KUBECONFIG"] = str(ROOT / ".secrets/k8s-write.kubeconfig")
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "mcp_servers.k8s_write.server"],
                                   env=env, cwd=str(ROOT))
    args: dict = {"namespace": action.namespace, "deployment": action.target}
    if action.name == "scale":
        args["replicas"] = action.params["replicas"]
    elif action.name == "delete_pod":
        args = {"namespace": action.namespace, "pod": action.target}
    elif action.name == "set_resources":
        import json as _json
        args["limits"] = _json.dumps(action.params["limits"])
        args["container"] = action.params.get("container", "server")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(TOOL_MAP[action.name], args)
            text = "\n".join(c.text for c in result.content
                             if hasattr(c, "text"))
            return {"ok": not result.isError, "detail": text}


def _approval_ok(state: IncidentState) -> bool:
    """Fail closed: execution requires an explicit recorded approval."""
    from database.connection import get_pool

    if state.get("approval") not in ("approved", "edited"):
        return False
    # cross-check: an approvals row must exist for this incident
    try:
        with get_pool().connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM approvals WHERE incident_id = %s::uuid "
                "AND decision IN ('approved','edited') LIMIT 1",
                (state["incident_id"],),
            ).fetchone()
        return row is not None
    except Exception:  # noqa: BLE001 - DB doubt = no execution (fail closed)
        return False


async def execute_node(state: IncidentState) -> dict:
    incident_id = state["incident_id"]
    plan: list[Action] = state.get("plan") or []

    if not _approval_ok(state):
        try:
            from api.services import incident_service
            incident_service.audit(incident_id, actor="executor",
                                   event="execution_refused",
                                   detail={"reason":
                                           "no valid approval record"})
        except Exception:  # noqa: BLE001 - audit must never break refusal
            pass
        return {"execution": {"executed": False,
                              "reason": "no valid approval record - refusing "
                                        "to execute (fail closed)",
                              "results": []},
                "timeline": [{"agent": "executor", "refused": True}]}

    if not plan:
        return {"execution": {"executed": False, "reason": "empty plan",
                              "results": []},
                "timeline": [{"agent": "executor", "skipped": "empty plan"}]}

    already = (state.get("execution") or {}).get("done_actions", [])
    results = list((state.get("execution") or {}).get("results", []))
    done: list[int] = list(already)

    for index, action in enumerate(plan):
        if index in done:
            continue  # duplicate-execution guard (node re-run after resume)
        try:
            # 1. re-validate the exact approved action
            validate_action(action.model_dump(), state.get("namespace"))
            # 2. fresh dry run - cluster state may have drifted since approval
            preflight = dry_run_action(action)
            if not preflight.get("ok"):
                results.append({"action": action.name, "target": action.target,
                                "ok": False, "stage": "preflight",
                                "detail": preflight.get("detail")})
                break  # stop the plan on first failure
            # 3. execute via the write MCP server
            outcome = await call_write_server(action)
            results.append({"action": action.name, "target": action.target,
                            "ok": outcome["ok"], "stage": "executed",
                            "detail": outcome["detail"][:500]})
            done.append(index)
            from api.services import incident_service
            incident_service.audit(
                incident_id, actor="executor",
                event="action_executed" if outcome["ok"] else "action_failed",
                detail={"action": action.name, "target": action.target,
                        "result": outcome["detail"][:300]})
            if not outcome["ok"]:
                break
        except PlanRejected as exc:
            results.append({"action": action.name, "target": action.target,
                            "ok": False, "stage": "revalidation",
                            "detail": str(exc)})
            break

    executed = bool(done) and all(r.get("ok") for r in results)
    return {"execution": {"executed": executed, "results": results,
                          "done_actions": done},
            "timeline": [{"agent": "executor",
                          "actions": [f"{r['action']}:{r['target']}"
                                      for r in results],
                          "ok": executed}]}
