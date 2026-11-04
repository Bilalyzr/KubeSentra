"""Unit tests for the Prometheus query templates and PromQL validation."""

import pytest

from mcp_servers.prometheus.server import TEMPLATES, _validate_promql


def test_sixteen_templates_defined():
    assert len(TEMPLATES) == 16
    expected = {
        "pod_restart_count", "pod_not_ready", "oomkilled_last_state",
        "container_waiting_reason", "cpu_usage", "memory_usage",
        "memory_vs_limit", "cpu_throttling_ratio", "deployment_replicas_available",
        "deployment_replicas_unavailable", "http_error_rate", "p95_latency",
    }
    assert expected <= set(TEMPLATES)


def test_templates_have_description_and_query():
    for name, t in TEMPLATES.items():
        assert t.get("d"), f"{name} missing description"
        assert t.get("q"), f"{name} missing query"


def test_templates_substitute_cleanly():
    from mcp_servers.prometheus.server import render_template
    for name in TEMPLATES:
        rendered = render_template(name, "boutique", "checkoutservice.*",
                                   "checkoutservice.*", "5m")
        assert "<namespace>" not in rendered
        assert "<pod_regex>" not in rendered
        assert "<deploy_regex>" not in rendered
        assert "<window>" not in rendered
        if name not in ("node_memory_available_ratio", "node_load1",
                        "http_error_rate", "p95_latency"):
            assert "checkoutservice" in rendered


@pytest.mark.parametrize("bad", [
    "rate(foo[5m",       # unbalanced
    "sum(by(pod){",      # unbalanced
    "query; DROP TABLE", # semicolon
    "line1\nline2",      # newline
    "",                  # empty
    "x" * 501,           # too long
])
def test_validate_promql_rejects(bad):
    with pytest.raises(ValueError):
        _validate_promql(bad)


def test_validate_promql_accepts_valid():
    _validate_promql('sum(rate(container_cpu_usage_seconds_total{namespace="boutique"}[5m])) by (pod)')
