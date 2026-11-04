"""Unit tests: plan validation guardrails (policy enforced in code)."""

import pytest

from agent.guardrails import (PlanRejected, _parse_quantity, validate_action,
                              validate_plan)


def _action(**over) -> dict:
    base = {"name": "rollout_undo", "namespace": "boutique",
            "target": "checkoutservice", "params": {}, "risk": "low",
            "rationale": "restore previous revision"}
    base.update(over)
    return base


def test_valid_actions_pass():
    validate_action(_action())
    validate_action(_action(name="scale", params={"replicas": 3}, risk="medium"))
    validate_action(_action(name="set_resources",
                            params={"limits": {"memory": "256Mi",
                                               "cpu": "500m"}}, risk="medium"))
    validate_action(_action(name="rollout_restart", risk="medium"))
    validate_action(_action(name="delete_pod",
                            target="checkoutservice-6fd54f5c78-gdtds"))


def test_unknown_action_rejected():
    with pytest.raises(PlanRejected, match="allowlist"):
        validate_action(_action(name="kubectl_apply"))


def test_wrong_namespace_rejected():
    with pytest.raises(PlanRejected, match="application namespace"):
        validate_action(_action(namespace="production"))


def test_protected_namespace_rejected():
    with pytest.raises(PlanRejected, match="namespace"):
        validate_action(_action(namespace="kube-system"))


def test_malformed_target_rejected():
    with pytest.raises(PlanRejected, match="target"):
        validate_action(_action(target="CheckoutService/../etc"))


@pytest.mark.parametrize("replicas", [0, 6, -1, "3", 2.5, True])
def test_scale_bounds_rejected(replicas):
    with pytest.raises(PlanRejected):
        validate_action(_action(name="scale", params={"replicas": replicas}))


def test_bad_quantity_rejected():
    with pytest.raises(PlanRejected, match="invalid quantity"):
        validate_action(_action(name="set_resources",
                                params={"limits": {"memory": "lots"}}))


def test_invalid_risk_rejected():
    with pytest.raises(PlanRejected, match="risk"):
        validate_action(_action(risk="extreme"))


def test_empty_plan_rejected():
    with pytest.raises(PlanRejected, match="empty"):
        validate_plan([])


def test_plan_size_capped():
    with pytest.raises(PlanRejected, match="at most 3"):
        validate_plan([_action() for _ in range(4)])


def test_quantity_parsing():
    assert _parse_quantity("100m") == pytest.approx(0.1)
    assert _parse_quantity("128Mi") == pytest.approx(128 * 1024 ** 2)
    assert _parse_quantity("1Gi") == pytest.approx(1024 ** 3)
    assert _parse_quantity("2") == 2.0
