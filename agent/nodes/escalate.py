"""Escalate: budget exhausted without a confident hypothesis. Everything
found so far is preserved for a human."""

from __future__ import annotations

import json

from agent.state import IncidentState


async def escalate_node(state: IncidentState) -> dict:
    hypotheses = state.get("hypotheses", [])
    evidence = state.get("evidence", [])
    ranked = sorted(hypotheses, key=lambda h: h.confidence, reverse=True)[:3]
    summary_lines = [
        "Investigation budget exhausted without a confident diagnosis.",
        f"Evidence collected: {len(evidence)} items. Leading hypotheses:",
    ] + [f"- ({h.confidence:.2f}) {h.cause}" for h in ranked]
    outcome = {
        "escalated": True,
        "reason": "budget_exhausted_no_confident_hypothesis",
        "steps_used": state.get("steps_used", 0),
        "leading_hypotheses": [h.model_dump() for h in ranked],
        "human_summary": "\n".join(summary_lines),
    }
    return {"outcome": outcome,
            "timeline": [{"agent": "escalate", "steps_used": outcome["steps_used"],
                          "json": json.dumps(outcome["leading_hypotheses"])}]}
