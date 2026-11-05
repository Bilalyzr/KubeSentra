"""SEC-4: invalid remediation parameters are rejected by CODE at every layer
(planner validation, approval re-validation, write server)."""

import pytest

from agent.guardrails import PlanRejected, validate_plan
from mcp_servers.k8s_write import server as ws


def _ok_action(**over):
    base = {"name": "rollout_undo", "namespace": "boutique",
            "target": "checkoutservice", "params": {}, "risk": "low",
            "rationale": "r"}
    base.update(over)
    return base


@pytest.mark.parametrize("params", [
    {"replicas": 0}, {"replicas": 6}, {"replicas": -1},
    {"replicas": "three"}, {"replicas": 2.5}, {"replicas": True},
    {"replicas": 100},
])
def test_scale_bounds_rejected_everywhere(params):
    action = _ok_action(name="scale", params=params)
    with pytest.raises(PlanRejected):
        validate_plan([action])
    with pytest.raises(PlanRejected):
        ws.scale_deployment(namespace="boutique",
                             deployment="checkoutservice",
                             replicas=params["replicas"])


@pytest.mark.parametrize("limits", [
    {"memory": "a lot"}, {"memory": "999999999Gi"}, {"cpu": "!!"},
    {"memory": ""}, {"memory": "10Mi extra"},
])
def test_bad_quantities_rejected(limits):
    action = _ok_action(name="set_resources", params={"limits": limits})
    with pytest.raises(PlanRejected):
        validate_plan([action])


@pytest.mark.parametrize("target", [
    "", "UPPERCASE", "name/../../etc", "name with spaces", "-leading",
    "a" * 300, "inject; kubectl delete all",
])
def test_malformed_targets_rejected(target):
    with pytest.raises(PlanRejected):
        validate_plan([_ok_action(target=target)])


def test_oversized_plan_rejected():
    with pytest.raises(PlanRejected):
        validate_plan([_ok_action() for _ in range(4)])


def test_cross_namespace_target_rejected():
    with pytest.raises(PlanRejected):
        validate_plan([_ok_action(namespace="kube-system")])
