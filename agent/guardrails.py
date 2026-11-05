"""Remediation guardrails: structured plan validation + server-side dry run
(implementation document section 7).

Rules enforced in CODE, not prompts:
- action allowlist only (five actions)
- application namespace only; protected namespaces rejected
- scale replicas within 1..5
- set_resources quantities well-formed and within policy bounds vs the
  cluster's CURRENT limits (max 2x) - checked live at dry-run time
- every action carries a risk level and rationale

The dry run uses the executor credential with dry_run=All: the API server
validates and admits the request but persists nothing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.state import Action
from common.config import get_settings
from common.safety import is_protected

ALLOWED_ACTIONS = {"rollout_restart", "rollout_undo", "scale", "delete_pod",
                   "set_resources"}
QUANTITY_RE = re.compile(r"^(\d+(?:\.\d+)?)(m|Ki|Mi|Gi|Ti|k|M|G)?$")
NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$")
MAX_NAME_LEN = 253  # DNS subdomain limit (security battery: length cap)

# absolute sanity caps beyond the 2x-live-state rule (security battery:
# "999999999Gi" is well-formed but absurd)
ABSOLUTE_LIMITS = {"cpu": 8.0, "memory": 8 * 1024 ** 3}  # cores / bytes


class PlanRejected(ValueError):
    """Raised when a plan (original or human-edited) violates policy."""


def _quantity_ok(value: str) -> bool:
    return bool(QUANTITY_RE.match(value or ""))


def validate_action(action: dict[str, Any], app_namespace: str | None = None) -> Action:
    """Validate ONE action dict; returns the typed Action or raises PlanRejected."""
    settings = get_settings()
    ns = app_namespace or settings.app_namespace

    name = action.get("name")
    if name not in ALLOWED_ACTIONS:
        raise PlanRejected(
            f"action {name!r} is not on the allowlist {sorted(ALLOWED_ACTIONS)}")

    namespace = action.get("namespace") or ns
    if namespace != ns:
        raise PlanRejected(
            f"namespace {namespace!r} is outside the application namespace {ns!r}")
    if is_protected(namespace):
        raise PlanRejected(f"namespace {namespace!r} is protected")

    target = action.get("target") or ""
    if not NAME_RE.match(target) or len(target) > MAX_NAME_LEN:
        raise PlanRejected(f"invalid target name {target!r}")

    params = action.get("params") or {}
    if name == "scale":
        replicas = params.get("replicas")
        if not isinstance(replicas, int) or isinstance(replicas, bool):
            raise PlanRejected("scale requires integer params.replicas")
        if not (settings.scale_min_replicas <= replicas
                <= settings.scale_max_replicas):
            raise PlanRejected(
                f"replicas {replicas} outside "
                f"{settings.scale_min_replicas}..{settings.scale_max_replicas}")
    if name == "set_resources":
        limits = params.get("limits") or {}
        if not limits:
            raise PlanRejected("set_resources requires params.limits")
        for key in ("cpu", "memory"):
            if key in limits and not _quantity_ok(str(limits[key])):
                raise PlanRejected(f"invalid quantity for limits.{key}: "
                                   f"{limits[key]!r}")
            if key in limits:
                value = _parse_quantity(str(limits[key]))
                if value > ABSOLUTE_LIMITS[key]:
                    raise PlanRejected(
                        f"limits.{key}={limits[key]} exceeds the absolute "
                        f"policy cap")
    if name == "delete_pod":
        if not target:
            raise PlanRejected("delete_pod requires a pod name as target")

    risk = action.get("risk", "medium")
    if risk not in ("low", "medium", "high"):
        raise PlanRejected(f"invalid risk {risk!r}")

    try:
        return Action(name=name, namespace=namespace, target=target,
                      params=params, risk=risk,
                      rationale=action.get("rationale", ""),
                      runbook_ref=action.get("runbook_ref"))
    except Exception as exc:  # noqa: BLE001 - pydantic errors become rejections
        raise PlanRejected(f"malformed action: {exc}") from exc


def validate_plan(plan: list[dict[str, Any]],
                  app_namespace: str | None = None) -> list[Action]:
    """Validate a whole plan (LLM-proposed or human-edited)."""
    if not plan:
        raise PlanRejected("plan is empty")
    if len(plan) > 3:
        raise PlanRejected("plan may contain at most 3 actions")
    return [validate_action(a, app_namespace) for a in plan]


# --- server-side dry run -------------------------------------------------------

def _load_write_config():
    from kubernetes import config as k8s_config

    kubeconfig = get_settings().k8s_write_kubeconfig
    if kubeconfig and Path(kubeconfig).exists():
        k8s_config.load_kube_config(config_file=str(
            Path(kubeconfig) if Path(kubeconfig).is_absolute()
            else Path(__file__).resolve().parents[1] / kubeconfig))
    else:
        k8s_config.load_kube_config()


def dry_run_action(action: Action) -> dict[str, Any]:
    """Server-side dry run of one action via the executor credential.

    dry_run="All" means the API server fully validates and admits the request
    but persists nothing. Returns {"ok": bool, "detail": str}. Also enforces
    the set_resources max-2x-current policy against live cluster state.
    """
    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    settings = get_settings()
    try:
        _load_write_config()
        apps = k8s_client.AppsV1Api()
        core = k8s_client.CoreV1Api()

        if action.name in ("rollout_restart", "rollout_undo", "set_resources"):
            # fetch current deployment (also proves the target exists)
            dep = apps.read_namespaced_deployment(
                action.target, action.namespace, _request_timeout=10)
            if action.name == "set_resources":
                _check_resource_bounds(dep, action, settings)

            if action.name == "rollout_restart":
                body = {"spec": {"template": {"metadata": {"annotations": {
                    "kubectl.kubernetes.io/restartedAt":
                        datetime.now(timezone.utc).isoformat()}}}}}
                apps.patch_namespaced_deployment(
                    action.target, action.namespace, body, dry_run="All",
                    _request_timeout=10)
                return {"ok": True, "detail": "dry-run rollout_restart admitted"}
            if action.name == "rollout_undo":
                # patch template back to the previous ReplicaSet's template
                prev = _previous_revision_template(apps, action)
                apps.patch_namespaced_deployment(
                    action.target, action.namespace,
                    {"spec": {"template": prev}}, dry_run="All",
                    _request_timeout=10)
                return {"ok": True, "detail": "dry-run rollout_undo admitted"}
            # set_resources
            container = _find_container(
                dep, str(action.params.get("container", "server")))
            patched = _patch_resources(dep, container, action.params["limits"])
            apps.patch_namespaced_deployment(
                action.target, action.namespace, patched, dry_run="All",
                _request_timeout=10)
            return {"ok": True, "detail":
                    f"dry-run set_resources admitted ({action.params['limits']})"}

        if action.name == "scale":
            apps.patch_namespaced_deployment_scale(
                action.target, action.namespace,
                {"spec": {"replicas": action.params["replicas"]}},
                dry_run="All", _request_timeout=10)
            return {"ok": True, "detail":
                    f"dry-run scale to {action.params['replicas']} admitted"}

        if action.name == "delete_pod":
            core.delete_namespaced_pod(
                action.target, action.namespace, dry_run="All",
                _request_timeout=10)
            return {"ok": True, "detail": "dry-run delete_pod admitted"}

        return {"ok": False, "detail": f"unhandled action {action.name}"}
    except ApiException as exc:
        return {"ok": False, "detail": f"k8s {exc.status}: {exc.reason} - {exc.body}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _find_container(dep, name_hint: str):  # noqa: ANN001
    containers = dep.spec.template.spec.containers
    for c in containers:
        if c.name == name_hint:
            return c
    return containers[0]


def _check_resource_bounds(dep, action: Action, settings) -> None:  # noqa: ANN001
    limits = action.params.get("limits", {})
    container = _find_container(dep, str(action.params.get("container", "server")))
    current = container.resources.limits or {}
    for key in ("cpu", "memory"):
        if key in limits and key in current:
            new = _parse_quantity(str(limits[key]))
            cur = _parse_quantity(str(current[key]))
            if new > cur * settings.set_resources_max_factor + 1e-9:
                raise PlanRejected(
                    f"limits.{key}={limits[key]} exceeds "
                    f"{settings.set_resources_max_factor}x current "
                    f"({current[key]})")


def _parse_quantity(q: str) -> float:
    units = {"m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9, "Ki": 1024,
             "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4}
    m = QUANTITY_RE.match(q)
    if not m:
        raise ValueError(f"unparsable quantity {q!r}")
    return float(m.group(1)) * units.get(m.group(2) or "", 1)


def _previous_revision_template(apps, action: Action):  # noqa: ANN001
    rs_list = apps.list_namespaced_replica_set(
        action.namespace, label_selector=f"app={action.target}",
        _request_timeout=10).items
    by_rev = {}
    for rs in rs_list:
        rev = (rs.metadata.annotations or {}).get(
            "deployment.kubernetes.io/revision")
        if rev:
            by_rev[int(rev)] = rs
    revs = sorted(by_rev, reverse=True)
    if len(revs) < 2:
        raise PlanRejected("no previous revision to roll back to")
    return by_rev[revs[1]].spec.template


def _patch_resources(dep, container, limits: dict) -> dict:  # noqa: ANN001
    """Build a strategic-merge patch body for the container's resource limits."""
    containers = dep.spec.template.spec.containers
    idx = containers.index(container)
    padded = [{"name": c.name} for c in containers]
    padded[idx]["resources"] = {"limits": dict(limits)}
    return {"spec": {"template": {"spec": {"containers": padded}}}}
