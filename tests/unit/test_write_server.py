"""Unit tests: k8s-write server rejects out-of-policy calls BEFORE any
cluster interaction (validation runs before the Kubernetes client loads)."""

import pytest

from agent.guardrails import PlanRejected
from mcp_servers.k8s_write import server as ws


def test_protected_namespace_rejected_before_cluster_call():
    with pytest.raises(PlanRejected):
        ws.rollout_restart(namespace="kube-system", deployment="coredns")


def test_monitoring_namespace_rejected():
    with pytest.raises(PlanRejected):
        ws.delete_pod(namespace="monitoring", pod="prometheus-0")


def test_wrong_app_namespace_rejected():
    with pytest.raises(PlanRejected):
        ws.scale_deployment(namespace="production",
                            deployment="checkoutservice", replicas=2)


def test_scale_out_of_bounds_rejected():
    with pytest.raises(PlanRejected):
        ws.scale_deployment(namespace="boutique",
                            deployment="checkoutservice", replicas=9)


def test_set_resources_bad_quantity_rejected():
    with pytest.raises(PlanRejected):
        ws.set_resources(namespace="boutique", deployment="checkoutservice",
                         limits='{"memory": "lots"}')


def test_set_resources_bad_json_rejected():
    with pytest.raises(ValueError):
        ws.set_resources(namespace="boutique", deployment="checkoutservice",
                         limits="not json")


def test_only_five_tools_exposed():
    """No arbitrary command surface: exactly the five allowlisted tools."""
    import mcp_servers.k8s_write.server as s
    import asyncio

    async def tools():
        return [t.name for t in await s.mcp.list_tools()]
    names = asyncio.run(tools())
    assert sorted(names) == ["delete_pod", "rollout_restart", "rollout_undo",
                             "scale_deployment", "set_resources"]
