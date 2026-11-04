"""prometheus MCP server: metric queries via named templates.

LLMs write invalid PromQL surprisingly often, so the primary tool is
``query_template`` with ~15 predefined, tested queries. Free-form PromQL is
available through ``query_range`` as a fallback with basic syntax validation.

Run: python -m mcp_servers.prometheus.server  (stdio transport)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from mcp.server.fastmcp import FastMCP

from common.config import get_settings
from common.safety import TOOL_TIMEOUT_S, cap, redact

mcp = FastMCP("prometheus")

MAX_SERIES = 20

# Named PromQL templates. The tokens <namespace>, <pod_regex>, <deploy_regex>
# and <window> are substituted by query_template (plain string replace - the
# queries contain literal PromQL braces, so str.format is not usable).
# Templates 15/16 query app HTTP metrics which Online Boutique v0.10.7 does
# not export - they return empty until the application instruments them
# (kept for forward compatibility).
TEMPLATES: dict[str, dict[str, str]] = {
    "pod_restart_count": {
        "d": "Restart count increase per pod over the window.",
        "q": 'increase(kube_pod_container_status_restarts_total{namespace="<namespace>",pod=~"<pod_regex>"}[<window>])',
    },
    "pod_not_ready": {
        "d": "Pods currently in NotReady state (1 = not ready).",
        "q": 'kube_pod_status_ready{condition="false",namespace="<namespace>",pod=~"<pod_regex>"} == 1',
    },
    "oomkilled_last_state": {
        "d": "Pods whose container last terminated with reason OOMKilled.",
        "q": 'kube_pod_container_status_last_terminated_reason{reason="OOMKilled",namespace="<namespace>",pod=~"<pod_regex>"}',
    },
    "container_waiting_reason": {
        "d": "Waiting reasons (CrashLoopBackOff, ImagePullBackOff, ...).",
        "q": 'kube_pod_container_status_waiting_reason{namespace="<namespace>",pod=~"<pod_regex>"}',
    },
    "deployment_replicas_available": {
        "d": "Available replicas per deployment.",
        "q": 'kube_deployment_status_replicas_available{namespace="<namespace>",deployment=~"<deploy_regex>"}',
    },
    "deployment_replicas_unavailable": {
        "d": "Unavailable replicas per deployment (non-zero = trouble).",
        "q": 'kube_deployment_status_replicas_unavailable{namespace="<namespace>",deployment=~"<deploy_regex>"}',
    },
    "cpu_usage": {
        "d": "CPU cores used per pod (rate over window).",
        "q": 'sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="<namespace>",pod=~"<pod_regex>",container!=""}[<window>]))',
    },
    "memory_usage": {
        "d": "Working-set memory bytes per pod.",
        "q": 'sum by (pod) (container_memory_working_set_bytes{namespace="<namespace>",pod=~"<pod_regex>",container!=""})',
    },
    "memory_vs_limit": {
        "d": "Fraction of memory limit used per pod (0..1+, >1 means OOM imminent).",
        "q": 'sum by (pod) (container_memory_working_set_bytes{namespace="<namespace>",pod=~"<pod_regex>",container!=""}) / on (pod) group_left sum by (pod) (kube_pod_container_resource_limits{resource="memory",namespace="<namespace>",pod=~"<pod_regex>"})',
    },
    "cpu_throttling_ratio": {
        "d": "Fraction of throttled CPU periods per pod (0..1).",
        "q": 'sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{namespace="<namespace>",pod=~"<pod_regex>",container!=""}[<window>])) / on (pod) group_left sum by (pod) (rate(container_cpu_cfs_periods_total{namespace="<namespace>",pod=~"<pod_regex>",container!=""}[<window>]))',
    },
    "cpu_limit": {
        "d": "CPU limits per pod (cores).",
        "q": 'sum by (pod) (kube_pod_container_resource_limits{resource="cpu",namespace="<namespace>",pod=~"<pod_regex>"})',
    },
    "pod_status_phase": {
        "d": "Pod phase gauge (Running/Pending/Failed/Succeeded = 1).",
        "q": 'kube_pod_status_phase{namespace="<namespace>",pod=~"<pod_regex>"}',
    },
    "node_memory_available_ratio": {
        "d": "Fraction of memory available per node.",
        "q": "node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes",
    },
    "node_load1": {
        "d": "1-minute load average per node.",
        "q": "node_load1",
    },
    "http_error_rate": {
        "d": "HTTP 5xx rate per job. NOTE: returns empty until the app exports http_server_request_duration_seconds (boutique v0.10.7 does not).",
        "q": 'sum by (job) (rate(http_server_request_duration_seconds_count{status_code=~"5.."}[<window>]))',
    },
    "p95_latency": {
        "d": "p95 request latency per job. NOTE: empty until app HTTP metrics exist (see http_error_rate).",
        "q": "histogram_quantile(0.95, sum by (job, le) (rate(http_server_request_duration_seconds_bucket[<window>])))",
    },
}


def render_template(name: str, namespace: str, pod_regex: str,
                    deploy_regex: str, window: str) -> str:
    """Substitute the <tokens> in a template (no str.format: PromQL braces)."""
    return (TEMPLATES[name]["q"]
            .replace("<namespace>", namespace)
            .replace("<pod_regex>", pod_regex)
            .replace("<deploy_regex>", deploy_regex)
            .replace("<window>", window))


def _client() -> httpx.Client:
    return httpx.Client(base_url=get_settings().prometheus_url, timeout=TOOL_TIMEOUT_S)


def _validate_promql(query: str) -> None:
    query = query.strip()
    if not query or len(query) > 500:
        raise ValueError("empty or overly long PromQL")
    if ";" in query or "\n" in query:
        raise ValueError("suspicious PromQL content rejected")
    for a, b in (("(", ")"), ("{", "}"), ("[", "]")):
        if query.count(a) != query.count(b):
            raise ValueError(f"unbalanced {a}{b} in PromQL")


def _fmt_value(v: float) -> str:
    return f"{v:.6g}" if abs(v) < 1e6 else f"{v:.3e}"


def _format_instant(result: dict) -> str:
    rtype = result.get("resultType")
    out_lines = [f"resultType: {rtype}"]
    results = result.get("result", [])
    if rtype == "vector":
        for s in results[:MAX_SERIES]:
            labels = ",".join(f"{k}={v}" for k, v in s["metric"].items() if k != "__name__")
            out_lines.append(f"{{{labels}}} = {_fmt_value(float(s['value'][1]))}")
        if len(results) > MAX_SERIES:
            out_lines.append(f"... {len(results) - MAX_SERIES} more series omitted")
    elif rtype == "scalar":
        out_lines.append(f"value = {_fmt_value(float(results[1]))}")
    elif not results:
        out_lines.append("(no data)")
    else:  # matrix
        for s in results[:MAX_SERIES]:
            labels = ",".join(f"{k}={v}" for k, v in s["metric"].items() if k != "__name__")
            out_lines.append(f"{{{labels}}}: {len(s['values'])} samples, last={_fmt_value(float(s['values'][-1][1]))}")
    return cap(redact("\n".join(out_lines)), 2500)


@mcp.tool()
def list_query_templates() -> str:
    """List the available named PromQL query templates with descriptions."""
    return "\n".join(f"{name}: {t['d']}" for name, t in TEMPLATES.items())


@mcp.tool()
def query_template(name: str, service: str | None = None,
                   namespace: str | None = None, window: str = "5m") -> str:
    """Run a named PromQL query template.

    Args:
        name: template name (see list_query_templates).
        service: service/deployment name used to filter pods (e.g. checkoutservice).
        namespace: defaults to the application namespace.
        window: range window like 5m, 10m, 1h.
    """
    if name not in TEMPLATES:
        raise ValueError(f"unknown template {name!r}; call list_query_templates")
    ns = namespace or get_settings().app_namespace
    pod_regex = f"{service}.*" if service else ".*"
    deploy_regex = f"{service}.*" if service else ".*"
    query = render_template(name, ns, pod_regex, deploy_regex, window)
    with _client() as http:
        resp = http.get("/api/v1/query", params={"query": query})
        resp.raise_for_status()
        body = resp.json()
    if body.get("status") != "success":
        raise ValueError(f"prometheus error: {body.get('error')}")
    return f"query: {query}\n" + _format_instant(body["data"])


@mcp.tool()
def query_range(query: str, duration_minutes: int = 30, step_seconds: int = 60,
                namespace_hint: str | None = None) -> str:
    """Run a free-form range PromQL query (fallback when no template fits).
    Basic syntax is validated locally; invalid queries fail at Prometheus with
    a clear error."""
    _validate_promql(query)
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=max(1, min(duration_minutes, 24 * 60)))
    with _client() as http:
        resp = http.get(
            "/api/v1/query_range",
            params={
                "query": query,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "step": max(15, min(step_seconds, 600)),
            },
        )
        resp.raise_for_status()
        body = resp.json()
    if body.get("status") != "success":
        raise ValueError(f"prometheus error: {body.get('error')}")
    return _format_instant(body["data"])


@mcp.tool()
def list_firing_alerts() -> str:
    """Currently FIRING alerts known to Prometheus (name, labels, since when)."""
    with _client() as http:
        resp = http.get("/api/v1/alerts")
        resp.raise_for_status()
        body = resp.json()
    firing = [
        a for a in body["data"]["alerts"]
        if a.get("state") in ("firing", "pending")
    ]
    if not firing:
        return "(no firing or pending alerts)"
    lines = [
        f"[{a['state']}] {a['labels'].get('alertname')} "
        f"ns={a['labels'].get('namespace', '-')} pod={a['labels'].get('pod', '-')} "
        f"since={a.get('activeAt', '-')}"
        for a in firing[:30]
    ]
    return cap(redact("\n".join(lines)))


if __name__ == "__main__":
    mcp.run()
