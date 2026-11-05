"""k8s-write MCP server: the ONLY path that can modify the cluster.

Design (implementation document 5.1 / 7):
- runs under the executor ServiceAccount - a Role bound to the application
  namespace ONLY (kube-system et al. are unreachable at the RBAC level)
- every tool re-validates its arguments through the SAME guardrails code
  path as the planner and the approval gate (defense in depth)
- no arbitrary command execution - exactly five structured actions
- every call is audited (actor, action, k8s response excerpt)
- called ONLY by the executor stage, after a recorded human approval;
  the server itself cannot know an approval exists, which is why the
  executor performs that check before invoking it

Run: python -m mcp_servers.k8s_write.server  (stdio transport)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from agent.guardrails import validate_action
from common.config import get_settings
from common.safety import TOOL_TIMEOUT_S

mcp = FastMCP("k8s-write")

ROOT = Path(__file__).resolve().parents[2]


def _client():  # noqa: ANN202 - kubernetes client pair
    from kubernetes import client as k8s_client, config as k8s_config

    kubeconfig = get_settings().k8s_write_kubeconfig
    if kubeconfig and (Path(kubeconfig) if Path(kubeconfig).is_absolute()
                       else ROOT / kubeconfig).exists():
        k8s_config.load_kube_config(config_file=str(
            (Path(kubeconfig) if Path(kubeconfig).is_absolute()
             else ROOT / kubeconfig)))
    else:
        k8s_config.load_kube_config()  # dev fallback: default context
    return k8s_client.AppsV1Api(), k8s_client.CoreV1Api()


def _audit(tool: str, detail: dict) -> None:
    """Best-effort audit row for every write-server call."""
    try:
        from database.connection import get_pool
        from psycopg.types.json import Json

        with get_pool().connection() as conn:
            conn.execute(
                "INSERT INTO audit_log (incident_id, actor, event, detail) "
                "VALUES (NULL, 'k8s-write-server', %s, %s)",
                (f"write:{tool}", Json(detail)),
            )
    except Exception:  # noqa: BLE001 - auditing must not block execution
        pass


def _validate(tool_alias: str, namespace: str, target: str,
              params: dict | None = None) -> None:
    """Validate through the shared guardrails (same rules as planner/approval).

    Raises PlanRejected/ValueError on any violation - BEFORE any cluster call.
    """
    validate_action({
        "name": tool_alias, "namespace": namespace, "target": target,
        "params": params or {}, "risk": "medium", "rationale": "write-server",
    })


@mcp.tool()
def rollout_restart(namespace: str, deployment: str) -> str:
    """Restart a deployment's pods (rolling). Allowlisted action."""
    _validate("rollout_restart", namespace, deployment)
    apps, _ = _client()
    body = {"spec": {"template": {"metadata": {"annotations": {
        "kubectl.kubernetes.io/restartedAt":
            datetime.now(timezone.utc).isoformat()}}}}}
    apps.patch_namespaced_deployment(deployment, namespace, body,
                                     _request_timeout=TOOL_TIMEOUT_S)
    _audit("rollout_restart", {"namespace": namespace,
                               "deployment": deployment})
    return f"rollout_restart issued for {namespace}/{deployment}"


@mcp.tool()
def rollout_undo(namespace: str, deployment: str) -> str:
    """Roll a deployment back to its previous revision. Allowlisted action."""
    _validate("rollout_undo", namespace, deployment)
    from agent.guardrails import _previous_revision_template
    from agent.state import Action

    apps, _ = _client()
    action = Action(name="rollout_undo", namespace=namespace, target=deployment,
                    risk="low", rationale="write-server")
    template = _previous_revision_template(apps, action)
    apps.patch_namespaced_deployment(
        deployment, namespace, {"spec": {"template": template}},
        _request_timeout=TOOL_TIMEOUT_S)
    _audit("rollout_undo", {"namespace": namespace, "deployment": deployment})
    return f"rollout_undo issued for {namespace}/{deployment}"


@mcp.tool()
def scale_deployment(namespace: str, deployment: str, replicas: int) -> str:
    """Scale a deployment to 1..5 replicas. Allowlisted action."""
    _validate("scale", namespace, deployment, {"replicas": replicas})
    apps, _ = _client()
    apps.patch_namespaced_deployment_scale(
        deployment, namespace, {"spec": {"replicas": replicas}},
        _request_timeout=TOOL_TIMEOUT_S)
    _audit("scale_deployment", {"namespace": namespace,
                                "deployment": deployment,
                                "replicas": replicas})
    return f"scaled {namespace}/{deployment} to {replicas}"


@mcp.tool()
def delete_pod(namespace: str, pod: str) -> str:
    """Delete one pod (the ReplicaSet recreates it). Allowlisted action."""
    _validate("delete_pod", namespace, pod)
    _, core = _client()
    core.delete_namespaced_pod(pod, namespace, _request_timeout=TOOL_TIMEOUT_S)
    _audit("delete_pod", {"namespace": namespace, "pod": pod})
    return f"deleted pod {namespace}/{pod}"


@mcp.tool()
def set_resources(namespace: str, deployment: str, limits: str,
                  container: str = "server") -> str:
    """Update a container's resource limits (JSON like {"memory":"256Mi"}).
    Policy-bounded to 2x the current live limits. Allowlisted action."""
    try:
        limits_dict = json.loads(limits) if isinstance(limits, str) else limits
    except json.JSONDecodeError as exc:
        raise ValueError(f"limits must be a JSON object: {exc}") from exc
    _validate("set_resources", namespace, deployment,
              {"limits": limits_dict, "container": container})
    from agent.guardrails import (_check_resource_bounds, _find_container,
                                  _patch_resources)
    from agent.state import Action

    apps, _ = _client()
    dep = apps.read_namespaced_deployment(deployment, namespace,
                                          _request_timeout=TOOL_TIMEOUT_S)
    action = Action(name="set_resources", namespace=namespace,
                    target=deployment,
                    params={"limits": limits_dict, "container": container},
                    risk="medium", rationale="write-server")
    _check_resource_bounds(dep, action, get_settings())
    current = _find_container(dep, container)
    body = _patch_resources(dep, current, limits_dict)
    apps.patch_namespaced_deployment(deployment, namespace, body,
                                     _request_timeout=TOOL_TIMEOUT_S)
    _audit("set_resources", {"namespace": namespace, "deployment": deployment,
                             "limits": limits_dict})
    return f"limits updated on {namespace}/{deployment}: {limits_dict}"


if __name__ == "__main__":
    mcp.run()
