"""Diagnoser: rank root causes from ALL evidence; every claim must cite
valid evidence IDs (grounding invariant enforced in code)."""

from __future__ import annotations

import json
import re

from agent.llm import ainvoke_with_retry, build_llm
from agent.state import (CATEGORY, DiagnosisReport, IncidentState,
                         evidence_ids, filter_valid_ids)
from pydantic import ValidationError

DIAGNOSE_PROMPT = """You are the Diagnoser for a Kubernetes incident.

Alert: {alert}
Service: {service} in namespace {namespace}

ALL evidence gathered (IDs are final):
{evidence}

Hypotheses with current confidences:
{hypotheses}

Produce the final diagnosis:
- choose the most likely root cause; cite ONLY real evidence IDs above
- explain WHY it is most likely and why each alternative is less likely
- if the evidence is weak, say so with a lower confidence - never invent

Reply with ONLY this JSON:
{{"root_cause": "...",
 "category": "resource|config|application|image|network|dependency|change|other",
 "confidence": 0.0,
 "supporting_evidence": ["E2"],
 "alternative_causes": [{{"cause": "...", "why_less_likely": "..."}}],
 "explanation": "3-6 sentences",
 "evidence_cited": ["E1", "E2"]}}"""


def parse_diagnosis(text: str) -> DiagnosisReport:
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start = cleaned.find("{")
    depth = 0
    for i, ch in enumerate(cleaned[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                data = json.loads(cleaned[start:i + 1])
                report = DiagnosisReport(**data)
                if report.category not in CATEGORY:
                    report = report.model_copy(update={"category": "other"})
                return report
    raise ValueError("no valid DiagnosisReport JSON found")


async def diagnose_node(state: IncidentState) -> dict:
    valid = evidence_ids(state)
    evidence = state.get("evidence", [])
    hypotheses = state.get("hypotheses", [])

    prompt = DIAGNOSE_PROMPT.format(
        alert=json.dumps(state.get("alert", {})),
        service=state.get("service", ""), namespace=state.get("namespace", ""),
        evidence="\n".join(f"{e.id} [{e.source}] {e.summary}" for e in evidence),
        hypotheses=json.dumps([h.model_dump() for h in hypotheses], indent=1),
    )
    text = await ainvoke_with_retry(build_llm("primary"), prompt)
    report = parse_diagnosis(text)

    # grounding: invalid citations are dropped; an ungrounded diagnosis is
    # capped at 0.5 confidence and flagged in the explanation
    supporting = filter_valid_ids(report.supporting_evidence, valid)
    cited = filter_valid_ids(report.evidence_cited, valid)
    capped = False
    if not supporting:
        capped = True
    report = report.model_copy(update={
        "supporting_evidence": supporting,
        "evidence_cited": cited or supporting,
    })
    if capped:
        report = report.model_copy(update={
            "confidence": min(report.confidence, 0.5),
            "explanation": report.explanation
            + " [NOTE: no valid evidence IDs were cited; confidence capped]",
        })

    return {"report": report,
            "timeline": [{"agent": "diagnose", "citations": report.supporting_evidence,
                          "confidence": report.confidence}]}
