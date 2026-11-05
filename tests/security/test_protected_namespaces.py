"""SEC-3: protected namespaces are unreachable for writes - enforced at
BOTH layers: application validation (write server) and Kubernetes RBAC
(executor ServiceAccount). Requires the live kind lab."""

import subprocess

import pytest

from agent.guardrails import PlanRejected
from mcp_servers.k8s_write import server as ws

pytestmark = pytest.mark.integration

PROTECTED = ["kube-system", "monitoring", "chaos-mesh", "kubesentra-system"]


@pytest.mark.parametrize("ns", PROTECTED)
def test_write_server_rejects_protected(ns):
    with pytest.raises(PlanRejected):
        ws.rollout_restart(namespace=ns, deployment="anything")
    with pytest.raises(PlanRejected):
        ws.delete_pod(namespace=ns, pod="anything")


def _can_i(verb, resource, namespace, as_sa):
    out = subprocess.run(
        ["kubectl", "auth", "can-i", verb, resource, "-n", namespace,
         "--as", f"system:serviceaccount:kubesentra-system:{as_sa}"],
        capture_output=True, text=True, timeout=30)
    return out.stdout.strip().lower() == "yes"


def test_rbac_executor_cannot_write_any_protected_namespace():
    for ns in PROTECTED:
        assert not _can_i("delete", "pods", ns, "kubesentra-executor"), ns
        assert not _can_i("patch", "deployments", ns, "kubesentra-executor"), ns


def test_rbac_executor_can_write_only_boutique():
    assert _can_i("patch", "deployments", "boutique", "kubesentra-executor")
    assert _can_i("delete", "pods", "boutique", "kubesentra-executor")


def test_rbac_reader_cannot_write_anywhere():
    for ns in ["boutique"] + PROTECTED:
        assert not _can_i("patch", "deployments", ns, "kubesentra-reader"), ns
        assert not _can_i("delete", "pods", ns, "kubesentra-reader"), ns


def test_reader_cannot_read_secrets():
    assert not _can_i("get", "secrets", "boutique", "kubesentra-reader")
