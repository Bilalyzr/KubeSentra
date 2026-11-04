"""k8s-read MCP server: read-only Kubernetes investigation tools.

Every tool:
- validates its namespace (protected namespaces are rejected)
- uses the dedicated read-only ServiceAccount kubeconfig when configured
- redacts secrets, caps output size and wraps untrusted content
- applies a 10s request timeout

Run: python -m mcp_servers.k8s_read.server  (stdio transport)
"""

from __future__ import annotations

from pathlib import Path

from kubernetes import client, config
from mcp.server.fastmcp import FastMCP

from common.config import get_settings
from common.safety import TOOL_TIMEOUT_S, check_namespace, sanitize

mcp = FastMCP("k8s-read")

_core: client.CoreV1Api | None = None
_apps: client.AppsV1Api | None = None
_metrics: client.CustomObjectsApi | None = None


def _apis() -> tuple[client.CoreV1Api, client.AppsV1Api, client.CustomObjectsApi]:
    global _core, _apps, _metrics
    if _core is None:
        kubeconfig = get_settings().k8s_reader_kubeconfig
        if kubeconfig and Path(kubeconfig).exists():
            config.load_kube_config(config_file=kubeconfig)
        else:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
        _core = client.CoreV1Api()
        _apps = client.AppsV1Api()
        _metrics = client.CustomObjectsApi()
    return _core, _apps, _metrics


def _default_ns(namespace: str | None) -> str:
    return namespace or get_settings().app_namespace


def _age(timestamp) -> str:  # noqa: ANN001 - k8s client datetime
    if timestamp is None:
        return "?"
    delta = (clientApiClientNow() - timestamp).total_seconds()
    for unit, div in (("d", 86400), ("h", 3600), ("m", 60)):
        if delta >= div:
            return f"{delta / div:.0f}{unit}"
    return f"{delta:.0f}s"


def clientApiClientNow():  # noqa: N802 - small helper matching usage
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


@mcp.tool()
def list_pods(namespace: str | None = None, label_selector: str | None = None) -> str:
    """List pods in a namespace with status, restarts and node.

    Args:
        namespace: defaults to the application namespace (boutique).
        label_selector: optional Kubernetes label selector, e.g. app=frontend.
    """
    ns = _default_ns(namespace)
    check_namespace(ns)
    core, _, _ = _apis()
    pods = core.list_namespaced_pod(
        ns, label_selector=label_selector, _request_timeout=TOOL_TIMEOUT_S
    ).items
    lines = ["NAME\tREADY\tSTATUS\tRESTARTS\tAGE\tNODE"]
    for p in sorted(pods, key=lambda x: x.metadata.name):
        ready = sum(1 for c in (p.status.container_statuses or []) if c.ready)
        total = len(p.spec.containers)
        restarts = sum(c.restart_count for c in (p.status.container_statuses or []))
        phase = p.status.phase
        if not ready and phase == "Running":
            phase = "NotReady"
        lines.append(
            f"{p.metadata.name}\t{ready}/{total}\t{phase}\t{restarts}\t"
            f"{_age(p.status.start_time)}\t{p.spec.node_name}"
        )
    return sanitize("\n".join(lines), source="kubectl list_pods")


@mcp.tool()
def describe_pod(namespace: str | None = None, pod: str = "") -> str:
    """Key details of one pod: containers, images, restarts, last states,
    probes, resources, node. Use get_pod_logs for log content."""
    ns = _default_ns(namespace)
    check_namespace(ns)
    if not pod:
        raise ValueError("pod name is required")
    core, _, _ = _apis()
    p = core.read_namespaced_pod(pod, ns, _request_timeout=TOOL_TIMEOUT_S)
    out = [f"Pod {ns}/{pod}", f"phase={p.status.phase} node={p.spec.node_name}"]
    for c in p.spec.containers:
        out.append(f"container {c.name}: image={c.image}")
        if c.resources.limits or c.resources.requests:
            out.append(f"  resources: requests={c.resources.requests} limits={c.resources.limits}")
        if c.readiness_probe:
            out.append(f"  readiness: {c.readiness_probe.http_get or c.readiness_probe.grpc or c.readiness_probe.tcp_socket or 'exec'}")
        if c.liveness_probe:
            out.append(f"  liveness:  {c.liveness_probe.http_get or c.liveness_probe.grpc or c.liveness_probe.tcp_socket or 'exec'}")
    for cs in p.status.container_statuses or []:
        last = cs.last_state.terminated
        if last:
            out.append(
                f"lastState[{cs.name}]: {last.reason} exit={last.exit_code} "
                f"started={last.started_at} finished={last.finished_at}"
            )
        wait = cs.state.waiting
        if wait and wait.reason:
            out.append(f"waiting[{cs.name}]: {wait.reason} {wait.message or ''}")
        out.append(f"restarts[{cs.name}]: {cs.restart_count}")
    events = core.list_namespaced_event(ns, _request_timeout=TOOL_TIMEOUT_S).items
    relevant = [
        e for e in events
        if e.involved_object.name == pod and e.reason in
        ("Killing", "BackOff", "Unhealthy", "Failed", "FailedScheduling", "Pulled")
    ][:10]
    for e in relevant:
        out.append(f"event: {e.reason} {e.message}")
    return sanitize("\n".join(out), source="kubectl describe_pod")


@mcp.tool()
def get_events(namespace: str | None = None, involved_object: str | None = None,
               limit: int = 30) -> str:
    """Recent Kubernetes events, newest first, optionally filtered by object
    name prefix (e.g. a deployment or pod name)."""
    ns = _default_ns(namespace)
    check_namespace(ns)
    limit = max(1, min(limit, 100))
    core, _, _ = _apis()
    events = core.list_namespaced_event(ns, _request_timeout=TOOL_TIMEOUT_S).items
    if involved_object:
        events = [e for e in events if e.involved_object.name.startswith(involved_object)]
    events.sort(key=lambda e: e.last_timestamp or e.event_time or 0, reverse=True)
    lines = [
        f"{e.type} {e.reason} {e.involved_object.kind}/{e.involved_object.name}: {e.message}"
        for e in events[:limit]
    ]
    return sanitize("\n".join(lines) or "(no events)", source="kubectl events")


@mcp.tool()
def get_pod_logs(namespace: str | None = None, pod: str = "",
                 container: str | None = None, tail_lines: int = 100,
                 previous: bool = False) -> str:
    """Last N log lines of a pod container. Set previous=True for the
    container instance that crashed before the current one."""
    ns = _default_ns(namespace)
    check_namespace(ns)
    if not pod:
        raise ValueError("pod name is required")
    tail_lines = max(1, min(tail_lines, 200))
    core, _, _ = _apis()
    logs = core.read_namespaced_pod_log(
        pod, ns, container=container, tail_lines=tail_lines,
        previous=previous, _request_timeout=TOOL_TIMEOUT_S,
    )
    return sanitize(logs or "(empty)", source="pod logs (UNTRUSTED)")


@mcp.tool()
def get_rollout_history(namespace: str | None = None, deployment: str = "") -> str:
    """Deployment revision history: revision, replica count and change cause."""
    ns = _default_ns(namespace)
    check_namespace(ns)
    if not deployment:
        raise ValueError("deployment name is required")
    _, apps, _ = _apis()
    rs_list = apps.list_namespaced_replica_set(
        ns, label_selector=f"app={deployment}", _request_timeout=TOOL_TIMEOUT_S
    ).items
    revisions = []
    for rs in rs_list:
        rev = (rs.metadata.annotations or {}).get("deployment.kubernetes.io/revision")
        if not rev:
            continue
        desired = rs.spec.replicas or 0
        current = rs.status.ready_replicas or 0
        revisions.append((int(rev), rs.metadata.name, desired, current))
    revisions.sort()
    lines = [
        f"rev {rev}: {name} (desired={d}, ready={r})" for rev, name, d, r in revisions
    ]
    return sanitize("\n".join(lines) or "(no revisions found)", source="rollout history")


@mcp.tool()
def diff_rollout_revisions(namespace: str | None = None, deployment: str = "",
                           revision_a: int | None = None,
                           revision_b: int | None = None) -> str:
    """Diff two ReplicaSet pod templates of a deployment (defaults to the two
    newest revisions). Compares images, commands, env var names, resources,
    ports and probes."""
    ns = _default_ns(namespace)
    check_namespace(ns)
    if not deployment:
        raise ValueError("deployment name is required")
    _, apps, _ = _apis()
    rs_list = apps.list_namespaced_replica_set(
        ns, label_selector=f"app={deployment}", _request_timeout=TOOL_TIMEOUT_S
    ).items
    by_rev: dict[int, object] = {}
    for rs in rs_list:
        rev = (rs.metadata.annotations or {}).get("deployment.kubernetes.io/revision")
        if rev:
            by_rev[int(rev)] = rs
    if len(by_rev) < 1:
        return sanitize("(no revisions found)", source="rollout diff")
    revs = sorted(by_rev, reverse=True)
    a = revision_a if revision_a is not None else (revs[1] if len(revs) > 1 else revs[0])
    b = revision_b if revision_b is not None else revs[0]

    def container_map(rs):  # noqa: ANN001, ANN202
        return {c.name: c for c in rs.spec.template.spec.containers}

    ca, cb = container_map(by_rev[a]), container_map(by_rev[b])
    out = [f"diff rev{a} -> rev{b} of deployment {ns}/{deployment}"]
    for name in sorted(set(ca) | set(cb)):
        if name not in ca:
            out.append(f"[{name}] container added in rev{b}")
            continue
        if name not in cb:
            out.append(f"[{name}] container removed in rev{b}")
            continue
        x, y = ca[name], cb[name]
        if x.image != y.image:
            out.append(f"[{name}] image: {x.image} -> {y.image}")
        if (x.command or []) != (y.command or []):
            out.append(f"[{name}] command: {x.command} -> {y.command}")
        env_a = {e.name for e in x.env or []}
        env_b = {e.name for e in y.env or []}
        if env_a != env_b:
            out.append(f"[{name}] env vars: {sorted(env_a)} -> {sorted(env_b)}")
        if x.resources.limits != y.resources.limits:
            out.append(f"[{name}] limits: {x.resources.limits} -> {y.resources.limits}")
        if x.readiness_probe is not None and y.readiness_probe is not None:
            pa = x.readiness_probe.http_get
            pb = y.readiness_probe.http_get
            if (pa and pb) and (pa.port != pb.port or pa.path != pb.path):
                out.append(f"[{name}] readiness: port {pa.port}{pa.path or ''} -> {pb.port}{pb.path or ''}")
    if len(out) == 1:
        out.append("(no template differences between these revisions)")
    return sanitize("\n".join(out), source="rollout diff")


@mcp.tool()
def get_resource_usage(namespace: str | None = None, pod: str | None = None) -> str:
    """Current CPU (millicores) and memory (MiB) per pod via metrics.k8s.io."""
    ns = _default_ns(namespace)
    check_namespace(ns)
    _, _, metrics = _apis()
    data = metrics.list_namespaced_custom_object(
        "metrics.k8s.io", "v1beta1", ns, "pods", _request_timeout=TOOL_TIMEOUT_S
    )
    lines = ["POD\tCPU(m)\tMEM(MiB)"]
    for item in data.get("items", []):
        name = item["metadata"]["name"]
        if pod and pod not in name:
            continue
        cpu_m = 0.0
        mem_mi = 0.0
        for c in item.get("containers", []):
            usage = c.get("usage", {})
            cpu_m += _quantity_to_m(usage.get("cpu", "0"))
            mem_mi += _quantity_to_mi(usage.get("memory", "0"))
        lines.append(f"{name}\t{cpu_m:.0f}\t{mem_mi:.1f}")
    return sanitize("\n".join(lines), source="pod metrics")


def _quantity_to_m(q: str) -> float:
    if q.endswith("n"):
        return float(q[:-1]) / 1e6
    if q.endswith("u"):
        return float(q[:-1]) / 1e3
    if q.endswith("m"):
        return float(q[:-1])
    return float(q) * 1000


def _quantity_to_mi(q: str) -> float:
    if q.endswith("Ki"):
        return float(q[:-2]) / 1024
    if q.endswith("Mi"):
        return float(q[:-2])
    if q.endswith("Gi"):
        return float(q[:-2]) * 1024
    return float(q) / (1024 * 1024)


@mcp.tool()
def get_configmap(namespace: str | None = None, name: str = "") -> str:
    """Inspect a ConfigMap: keys with value sizes only - values themselves are
    redacted (they may contain credentials)."""
    ns = _default_ns(namespace)
    check_namespace(ns)
    if not name:
        raise ValueError("configmap name is required")
    core, _, _ = _apis()
    cm = core.read_namespaced_config_map(name, ns, _request_timeout=TOOL_TIMEOUT_S)
    lines = [f"ConfigMap {ns}/{name}"]
    for key, value in (cm.data or {}).items():
        lines.append(f"  {key}: <{len(value)} chars, value redacted>")
    return sanitize("\n".join(lines), source="configmap metadata")


if __name__ == "__main__":
    mcp.run()
