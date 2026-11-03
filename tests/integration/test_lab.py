"""Integration tests against the live kind laboratory (Phase 2).

Skipped automatically when the incident-lab cluster is not running.
Bring it up first: scripts/lab_up.sh
"""

import subprocess

import httpx
import pytest

pytestmark = pytest.mark.integration


def _kubectl(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kubectl", *args], capture_output=True, text=True, timeout=timeout
    )


def _lab_available() -> bool:
    try:
        ctx = _kubectl(["config", "current-context"], timeout=30).stdout.strip()
        if ctx != "kind-incident-lab":
            return False
        return _kubectl(["get", "nodes"], timeout=30).returncode == 0
    except Exception:  # noqa: BLE001
        return False


if not _lab_available():
    pytest.skip("kind cluster incident-lab not running - start it with scripts/lab_up.sh",
                allow_module_level=True)


def kout(args: list[str]) -> str:
    result = _kubectl(args)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_three_nodes_ready():
    lines = [line for line in kout(["get", "nodes", "--no-headers"]).splitlines() if line]
    assert len(lines) == 3, f"expected 3 nodes, got {len(lines)}"
    not_ready = [line for line in lines if line.split()[1] != "Ready"]
    assert not not_ready, f"nodes not Ready: {not_ready}"


def test_boutique_deployments_available():
    rows = [line.split() for line in
            kout(["-n", "boutique", "get", "deploy", "--no-headers"]).splitlines() if line]
    assert len(rows) >= 10, f"expected >=10 boutique deployments, got {len(rows)}"
    unavailable = []
    for row in rows:
        current, total = row[1].split("/")
        if int(current) < int(total):
            unavailable.append(row[0])
    assert not unavailable, f"unavailable deployments: {unavailable}"


def test_prometheus_targets_up():
    resp = httpx.get("http://127.0.0.1:9090/api/v1/targets", timeout=10)
    assert resp.status_code == 200
    up = [t for t in resp.json()["data"]["activeTargets"] if t["health"] == "up"]
    assert len(up) >= 5, f"only {len(up)} targets up"


def test_custom_alert_rules_loaded():
    resp = httpx.get("http://127.0.0.1:9090/api/v1/rules", timeout=10)
    assert resp.status_code == 200
    names = {rule["name"]
             for group in resp.json()["data"]["groups"]
             for rule in group["rules"]}
    required = {"PodRestarting", "PodNotReady", "DeploymentReplicasUnavailable"}
    missing = required - names
    assert not missing, f"custom rules not loaded: {missing}"


def test_alertmanager_ready():
    resp = httpx.get("http://127.0.0.1:9093/-/ready", timeout=10)
    assert resp.status_code == 200


def test_loki_ready_and_ingesting():
    ready = httpx.get("http://127.0.0.1:13100/ready", timeout=10)
    assert ready.status_code == 200
    labels = httpx.get(
        "http://127.0.0.1:13100/loki/api/v1/labels",
        params={"limit": 100}, timeout=10,
    )
    assert labels.status_code == 200
    assert "namespace" in labels.json()["data"], "Alloy has not shipped any logs yet"


def test_chaos_mesh_controller_available():
    out = kout(["-n", "chaos-mesh", "get", "deployment", "chaos-controller-manager",
                "-o", "jsonpath={.status.availableReplicas}"])
    assert int(out) >= 1
