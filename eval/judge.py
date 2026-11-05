"""LLM judge with a strict rubric (implementation document 9.1).

Correct means: correct SERVICE and correct CATEGORY and a cause compatible
with the ground truth. The judge sees the prediction and ground truth only.
A deterministic fallback (category match) covers judge unavailability - and
is labelled as such in the record.
"""

from __future__ import annotations

import json
import re

RUBRIC = """You are a strict evaluator for Kubernetes root-cause diagnoses.

Ground truth:
  service: {gt_service}
  category: {gt_category}
  root cause: {gt_cause}

Predicted diagnosis:
  service: {pred_service}
  category: {pred_category}
  root cause: {pred_cause}

Score with this rubric:
- top1: does the PREDICTED cause identify the SAME failure on the SAME
  service as the ground truth? (category must match; the cause wording may
  differ but must describe the same underlying failure)
- top3: if alternative hypotheses are listed below, is the ground truth
  among ANY of them (including the top one)?

Alternatives (may be empty): {alternatives}

Reply with ONLY this JSON:
{{"top1": true/false, "top3": true/false,
  "reason": "one sentence"}}"""


def judge_diagnosis(scenario: dict, incident_row: dict) -> dict:
    gt = scenario["ground_truth"]
    pred_service = incident_row.get("service")
    pred_category = incident_row.get("root_cause_category")
    pred_cause = incident_row.get("root_cause") or ""

    alternatives = []
    actions = incident_row.get("actions")
    if isinstance(actions, dict):
        payload = actions.get("approval_payload", {}) or {}
        alternatives = [h.get("cause", "") for h in
                        payload.get("hypotheses", [])[1:]]

    prompt = RUBRIC.format(
        gt_service=gt["root_service"], gt_category=gt["category"],
        gt_cause=gt["root_cause"], pred_service=pred_service,
        pred_category=pred_category or "unknown", pred_cause=pred_cause[:400],
        alternatives=json.dumps(alternatives[:3]))

    try:
        from agent.llm import ainvoke_with_retry, build_llm
        import asyncio

        text = asyncio.run(ainvoke_with_retry(build_llm("primary"), prompt))
        match = re.search(r"\{.*\}", text, re.DOTALL)
        verdict = json.loads(match.group(0))
        return {"top1_correct": bool(verdict.get("top1")),
                "top3_correct": bool(verdict.get("top3")),
                "judge": "llm",
                "judge_reason": verdict.get("reason", "")[:200]}
    except Exception as exc:  # noqa: BLE001 - deterministic fallback
        # fallback: strict category+service match, labelled as fallback
        top1 = (pred_category == gt["category"]
                and pred_service == gt["root_service"])
        return {"top1_correct": top1, "top3_correct": top1,
                "judge": "fallback(category-match)",
                "judge_reason": f"LLM judge unavailable: "
                                f"{type(exc).__name__}"}
