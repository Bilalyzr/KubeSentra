"""Unit tests: the Supervisor's pure hard-routing rules (spec 4.3)."""

from agent.nodes.supervisor import _loop_guard, decide_route, route_from_supervisor
from agent.state import Evidence, Hypothesis


def _state(hypotheses=None, steps=0, evidence=None):
    return {"hypotheses": hypotheses or [], "steps_used": steps,
            "evidence": evidence or []}


def test_budget_exhausted_with_confident_hypothesis_diagnoses():
    state = _state([Hypothesis(cause="x", category="resource", confidence=0.6)],
                   steps=15)
    assert decide_route(state) == "diagnose"


def test_budget_exhausted_without_confidence_escalates():
    state = _state([Hypothesis(cause="x", category="resource", confidence=0.3)],
                   steps=15)
    assert decide_route(state) == "escalate"


def test_confident_hypothesis_with_two_sources_diagnoses():
    evidence = [
        Evidence(id="E1", source="memory", summary="s", raw_ref="r"),
        Evidence(id="E2", source="k8s", summary="s", raw_ref="r"),
    ]
    state = _state(
        [Hypothesis(cause="x", category="resource", confidence=0.85,
                    supporting=["E1", "E2"])],
        steps=3, evidence=evidence,
    )
    assert decide_route(state) == "diagnose"


def test_confident_hypothesis_with_one_source_defers_to_llm():
    evidence = [Evidence(id="E1", source="memory", summary="s", raw_ref="r")]
    state = _state(
        [Hypothesis(cause="x", category="resource", confidence=0.85,
                    supporting=["E1"])],
        steps=3, evidence=evidence,
    )
    assert decide_route(state) == "llm"


def test_low_confidence_defers_to_llm():
    state = _state([Hypothesis(cause="x", category="resource", confidence=0.4)])
    assert decide_route(state) == "llm"


def test_route_from_supervisor_rejects_unknown():
    assert route_from_supervisor({"next_agent": "hack_the_planet"}) == "escalate"
    assert route_from_supervisor({"next_agent": "diagnose"}) == "diagnose"


def test_loop_guard_breaks_triple_repeats():
    state = {"timeline": [{"agent": "metrics_agent"}] * 3,
             "hypotheses": [Hypothesis(cause="x", category="resource",
                                       confidence=0.55)]}
    assert _loop_guard(state, "metrics_agent") == "diagnose"


def test_loop_guard_without_confidence_rotates_agent():
    state = {"timeline": [{"agent": "metrics_agent"}] * 3, "hypotheses": []}
    assert _loop_guard(state, "metrics_agent") != "metrics_agent"
