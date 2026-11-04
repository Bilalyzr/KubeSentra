"""Integration tests: every MCP tool is called through the real MCP stdio
protocol against the live laboratory (Phase 3 gate).

Skipped when the lab is down. Run: pytest tests/integration/test_mcp_servers.py -v
"""

import os
import re
import uuid
from pathlib import Path

import httpx
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
VENV_PY = str(ROOT / ".venv/Scripts/python.exe")


def _lab_available() -> bool:
    try:
        resp = httpx.get("http://127.0.0.1:9090/-/ready", timeout=3)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


if not _lab_available():
    pytest.skip("lab not running - start it with scripts/lab_up.sh",
                allow_module_level=True)


def _server_params(module: str) -> StdioServerParameters:
    env = dict(os.environ)
    # absolute paths so the subprocess resolves them regardless of cwd
    env["K8S_READER_KUBECONFIG"] = str(ROOT / ".secrets/k8s-read.kubeconfig")
    # keep protocol tests fast/deterministic: no torch inside stdio servers
    env["KUBESENTRA_NO_EMBEDDINGS"] = "1"
    return StdioServerParameters(command=VENV_PY, args=["-m", module], env=env,
                                 cwd=str(ROOT))


async def call_tool(module: str, tool: str, args: dict) -> tuple[bool, str]:
    """Start the server, open an MCP session, call one tool. Returns (ok, text)."""
    async with stdio_client(_server_params(module)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            text = "\n".join(
                c.text for c in result.content if hasattr(c, "text")
            )
            return not result.isError, text


# --- k8s-read ----------------------------------------------------------------


async def test_k8s_list_pods():
    ok, text = await call_tool("mcp_servers.k8s_read.server", "list_pods", {})
    assert ok, text
    assert "NAME" in text and "checkoutservice" in text
    assert "<untrusted-data" in text


async def test_k8s_list_pods_protected_namespace_rejected():
    ok, text = await call_tool(
        "mcp_servers.k8s_read.server", "list_pods", {"namespace": "kube-system"}
    )
    assert not ok, "protected namespace must be rejected"
    assert "protected" in text


async def test_k8s_describe_pod():
    ok, listing = await call_tool("mcp_servers.k8s_read.server", "list_pods", {})
    assert ok
    pod = next(line.split("\t")[0] for line in listing.splitlines()
               if line.startswith("checkoutservice"))
    ok, text = await call_tool(
        "mcp_servers.k8s_read.server", "describe_pod", {"pod": pod}
    )
    assert ok, text
    assert "image=" in text


async def test_k8s_events_and_logs():
    ok, events = await call_tool("mcp_servers.k8s_read.server", "get_events", {})
    assert ok, events
    ok, logs = await call_tool(
        "mcp_servers.k8s_read.server", "get_pod_logs",
        {"pod": "frontend-58b4dc4d4d-mgzvg"},
    )
    # frontend pod name may differ across lab rebuilds: fall back to listing
    if not ok:
        ok2, listing = await call_tool("mcp_servers.k8s_read.server", "list_pods", {})
        assert ok2
        pod = next(line.split("\t")[0] for line in listing.splitlines()
                   if line.startswith("frontend"))
        ok, logs = await call_tool(
            "mcp_servers.k8s_read.server", "get_pod_logs", {"pod": pod}
        )
    assert ok, logs
    assert "<untrusted-data" in logs  # logs are always wrapped


async def test_k8s_rollout_history_and_diff():
    ok, hist = await call_tool(
        "mcp_servers.k8s_read.server", "get_rollout_history",
        {"deployment": "checkoutservice"},
    )
    assert ok, hist
    assert "rev" in hist
    ok, diff = await call_tool(
        "mcp_servers.k8s_read.server", "diff_rollout_revisions",
        {"deployment": "checkoutservice"},
    )
    assert ok, diff
    assert "rev" in diff


async def test_k8s_resource_usage():
    ok, text = await call_tool(
        "mcp_servers.k8s_read.server", "get_resource_usage", {}
    )
    assert ok, text
    assert "CPU(m)" in text and "MEM(MiB)" in text


async def test_k8s_configmap_redacted():
    ok, text = await call_tool(
        "mcp_servers.k8s_read.server", "get_configmap",
        {"name": "kube-root-ca.crt"},
    )
    assert ok, text
    assert "redacted" in text
    assert "BEGIN CERTIFICATE" not in text


# --- prometheus ----------------------------------------------------------------


async def test_prometheus_templates_list_and_query():
    ok, listing = await call_tool(
        "mcp_servers.prometheus.server", "list_query_templates", {}
    )
    assert ok, listing
    assert "pod_restart_count" in listing

    ok, result = await call_tool(
        "mcp_servers.prometheus.server", "query_template",
        {"name": "cpu_usage", "service": "checkoutservice"},
    )
    assert ok, result
    assert "resultType" in result
    assert "checkoutservice" in result


async def test_prometheus_unknown_template_rejected():
    ok, text = await call_tool(
        "mcp_servers.prometheus.server", "query_template",
        {"name": "drop_all_tables"},
    )
    assert not ok


async def test_prometheus_freeform_and_alerts():
    ok, rng = await call_tool(
        "mcp_servers.prometheus.server", "query_range",
        {"query": 'up{namespace="monitoring"}', "duration_minutes": 10,
         "step_seconds": 60},
    )
    assert ok, rng
    ok, alerts = await call_tool(
        "mcp_servers.prometheus.server", "list_firing_alerts", {}
    )
    assert ok, alerts  # text whether or not alerts are firing


# --- loki ----------------------------------------------------------------------


async def test_loki_query_logs():
    ok, text = await call_tool(
        "mcp_servers.loki.server", "query_logs",
        {"logql": '{namespace="boutique", pod=~"frontend.*"}', "limit": 5},
    )
    assert ok, text
    assert "<untrusted-data" in text


async def test_loki_query_logs_rejects_non_selector():
    ok, text = await call_tool(
        "mcp_servers.loki.server", "query_logs",
        {"logql": "rm -rf /"},
    )
    assert not ok


async def test_loki_error_patterns():
    ok, text = await call_tool(
        "mcp_servers.loki.server", "error_patterns",
        {"service": "loadgenerator", "since": "30m"},
    )
    assert ok, text
    # either patterns or an explicit no-errors message - never a crash
    assert ("error_lines=" in text) or ("no error-like lines" in text)


# --- knowledge -------------------------------------------------------------------
# requires the Postgres container (docker compose up -d postgres)


async def test_knowledge_incident_roundtrip():
    token = f"phase3-{uuid.uuid4().hex[:8]}"
    ok, saved = await call_tool(
        "mcp_servers.knowledge.server", "save_incident",
        {
            "alert_name": "PodRestarting", "namespace": "boutique",
            "service": "checkoutservice",
            "symptoms": f"restarts climbing {token}",
            "root_cause": f"memory limit too low {token}",
            "root_cause_category": "resource",
            "resolved": True,
            "summary": f"phase 3 integration test incident {token}",
        },
    )
    assert ok, saved
    inc_id = re.search(r"[0-9a-f-]{36}", saved).group(0)

    ok, found = await call_tool(
        "mcp_servers.knowledge.server", "search_incidents",
        {"query": token},
    )
    assert ok, found
    assert token in found

    ok, single = await call_tool(
        "mcp_servers.knowledge.server", "get_incident", {"incident_id": inc_id}
    )
    assert ok, single
    assert "root_cause" in single

    # cleanup: remove the test row
    from database.connection import get_pool
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM incidents WHERE id = %s", (uuid.UUID(inc_id),))


async def test_knowledge_runbooks_search():
    """Since Phase 6 the KB is populated. Embeddings are disabled in
    protocol tests, so this exercises the FTS leg with an exact Kubernetes
    token (single-word 'crashloop' does not stem-match the compound token
    'CrashLoopBackOff' - the semantic leg handles such queries; see
    test_rag.py)."""
    ok, text = await call_tool(
        "mcp_servers.knowledge.server", "search_runbooks",
        {"query": "CrashLoopBackOff"},
    )
    assert ok, text
    assert ("CrashLoopBackOff" in text) or ("knowledge.ingest" in text)
