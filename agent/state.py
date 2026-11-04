"""Shared multi-agent investigation state (implementation document 4.2).

Two invariants the whole system depends on:
- evidence is APPEND-ONLY during an investigation (Annotated reducer),
- every hypothesis / diagnosis may only cite evidence IDs that exist.
The citation invariant is enforced by `filter_valid_ids` at every hop.
"""

from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field, ValidationError

EvidenceSource = Literal["metrics", "logs", "k8s", "change", "memory", "runbook"]
CATEGORY = ("resource", "config", "application", "image", "network",
            "dependency", "change", "other")


class Evidence(BaseModel):
    id: str                                  # "E1", "E2", ...
    source: EvidenceSource
    summary: str                             # 1-2 sentences, LLM-facing
    raw_ref: str                             # pointer to full output (DB)
    incident_id: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Hypothesis(BaseModel):
    cause: str
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting: list[str] = []               # evidence IDs
    refuting: list[str] = []


class Action(BaseModel):
    """Allowlisted remediation action (execution arrives in Phase 6/7)."""
    name: Literal["rollout_restart", "rollout_undo", "scale", "delete_pod",
                  "set_resources"]
    namespace: str
    target: str
    params: dict = {}
    risk: Literal["low", "medium", "high"]
    rationale: str
    runbook_ref: str | None = None


class DiagnosisReport(BaseModel):
    root_cause: str
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = []      # evidence IDs - validated
    alternative_causes: list[dict] = []      # {cause, why_less_likely}
    explanation: str
    evidence_cited: list[str] = []


class IncidentState(TypedDict, total=False):
    incident_id: str
    alert: dict
    namespace: str
    service: str
    evidence: Annotated[list[Evidence], operator.add]   # append-only
    hypotheses: list[Hypothesis]
    similar_incidents: list[dict]
    next_agent: str                           # set by supervisor
    next_question: str
    steps_used: int
    cost_usd: float
    timeline: Annotated[list[dict], operator.add]       # per-step audit trail
    report: DiagnosisReport | None
    plan: list[Action]                        # Phase 6
    approval: str | None                      # Phase 6
    outcome: dict | None                      # Phase 7


# --- grounding helpers ---------------------------------------------------------


def evidence_ids(state_or_list) -> set[str]:
    """All valid evidence IDs (accepts a state dict or evidence list)."""
    items = (state_or_list.get("evidence", []) if isinstance(state_or_list, dict)
             else state_or_list)
    return {e.id for e in items}


def filter_valid_ids(ids: list[str], valid: set[str]) -> list[str]:
    """Drop citations that do not reference real evidence (grounding rule)."""
    return [i for i in (ids or []) if i in valid]


def parse_hypotheses(text: str) -> list[Hypothesis]:
    """Parse an LLM hypothesis list; invalid entries are dropped, citations
    are filtered against the known-valid set by the caller."""
    import json
    import re

    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON list found in hypothesis output")
    data = json.loads(cleaned[start:end + 1])
    out: list[Hypothesis] = []
    for item in data:
        try:
            h = Hypothesis(**item)
            if h.category not in CATEGORY:
                h = h.model_copy(update={"category": "other"})
            out.append(h)
        except (ValidationError, TypeError):
            continue
    if not out:
        raise ValueError("no valid hypotheses parsed")
    return out
