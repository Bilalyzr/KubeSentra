"""Unit tests: shared state models, hypothesis parsing, grounding filter."""

import pytest
from pydantic import ValidationError

from agent.state import (Action, DiagnosisReport, Evidence, Hypothesis,
                         filter_valid_ids, parse_hypotheses)


def _evidence(eid: str, source: str = "metrics") -> Evidence:
    return Evidence(id=eid, source=source, summary="s", raw_ref="r")  # type: ignore[arg-type]


def test_hypothesis_confidence_bounds():
    with pytest.raises(ValidationError):
        Hypothesis(cause="x", category="resource", confidence=1.5)


def test_action_allowlist_rejects_unknown():
    with pytest.raises(ValidationError):
        Action(name="delete_everything", namespace="boutique", target="x",
               risk="low", rationale="r")


def test_filter_valid_ids_drops_unknown():
    assert filter_valid_ids(["E1", "E9", "E2"], {"E1", "E2"}) == ["E1", "E2"]


def test_parse_hypotheses_from_fenced_json():
    text = """```json
    [{"cause": "memory too low", "category": "resource", "confidence": 0.7,
      "supporting": ["E1"], "refuting": []}]
    ```"""
    hyps = parse_hypotheses(text)
    assert hyps[0].cause == "memory too low"
    assert hyps[0].confidence == 0.7


def test_parse_hypotheses_unknown_category_becomes_other():
    hyps = parse_hypotheses('[{"cause": "x", "category": "weird", "confidence": 0.5}]')
    assert hyps[0].category == "other"


def test_parse_hypotheses_drops_invalid_entries_but_keeps_valid():
    text = ('[{"cause": "ok", "category": "resource", "confidence": 0.5},'
            '{"cause": "no confidence"},'
            '{"cause": "also ok", "category": "config", "confidence": 0.3}]')
    hyps = parse_hypotheses(text)
    assert [h.cause for h in hyps] == ["ok", "also ok"]


def test_parse_hypotheses_garbage_raises():
    with pytest.raises(ValueError):
        parse_hypotheses("I think maybe the memory is low, not sure.")


def test_diagnosis_report_validates_confidence():
    with pytest.raises(ValidationError):
        DiagnosisReport(root_cause="x", category="resource", confidence=2.0)


def test_evidence_sources_are_constrained():
    with pytest.raises(ValidationError):
        _evidence("E1", "gossip")
