"""SEC-6: agent loop safety - budgets and loop-guards are hard CODE rules
that no LLM output can override."""

from agent.nodes.supervisor import _loop_guard, decide_route
from agent.state import Evidence, Hypothesis
from common.config import get_settings


def test_step_budget_is_hard():
    settings = get_settings()
    assert settings.max_investigation_steps >= 1
    state = {"steps_used": settings.max_investigation_steps,
             "hypotheses": [Hypothesis(cause="x", category="resource",
                                       confidence=0.9)],
             "evidence": []}
    # budget exhausted ALWAYS routes out of the specialist loop
    assert decide_route(state) == "diagnose"


def test_loop_guard_rotates_after_three_same_choices():
    state = {"timeline": [{"agent": "logs_agent"}] * 3,
             "hypotheses": []}
    assert _loop_guard(state, "logs_agent") != "logs_agent"


def test_wall_clock_timeout_configured():
    assert get_settings().investigation_timeout_s > 0


def test_specialist_tool_budget_configured():
    assert 1 <= get_settings().specialist_max_tool_calls <= 10
