"""Unit tests: baseline agent report parsing (no LLM needed)."""

import pytest

from agent.baseline import BaselineReport, parse_report

VALID = (
    '{"suspected_root_cause": "memory limit too low", "category": "resource",'
    ' "confidence": 0.8, "key_findings": ["restarts rising", "OOMKilled"],'
    ' "summary": "checkoutservice is OOMKilled repeatedly."}'
)


def test_parse_plain_json():
    report = parse_report(VALID)
    assert report.suspected_root_cause == "memory limit too low"
    assert report.category == "resource"
    assert report.confidence == 0.8
    assert len(report.key_findings) == 2


def test_parse_json_in_markdown_fences():
    report = parse_report(f"```json\n{VALID}\n```")
    assert report.category == "resource"


def test_parse_json_with_surrounding_text():
    report = parse_report(f"Here is my conclusion:\n{VALID}\nDone.")
    assert report.confidence == 0.8


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_report("I could not determine the root cause, sorry.")


def test_parse_rejects_bad_category():
    bad = VALID.replace('"resource"', '"made-up-category"')
    with pytest.raises(ValueError):
        parse_report(bad)


def test_parse_rejects_out_of_range_confidence():
    bad = VALID.replace("0.8", "1.5")
    with pytest.raises(ValueError):
        parse_report(bad)


def test_baseline_report_model_validates():
    with pytest.raises(Exception):
        BaselineReport(suspected_root_cause="x", category="resource",
                       confidence=2.0, key_findings=[], summary="")
