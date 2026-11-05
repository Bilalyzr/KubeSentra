"""Aggregate eval result JSONs into the results table + markdown report.

Usage: python -m eval.aggregate
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

RESULTS = Path(__file__).resolve().parent / "results"


def load() -> list[dict]:
    rows = []
    for path in sorted(RESULTS.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return rows


def aggregate(rows: list[dict]) -> dict:
    by_config: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if "error" in r:
            by_config[r["config"]].append(r)
            continue
        by_config[r["config"]].append(r)

    table = {}
    for config, runs in sorted(by_config.items()):
        ok = [r for r in runs if "error" not in r]
        errs = [r for r in runs if "error" in r]
        ttds = [r["time_to_diagnosis_s"] for r in ok
                if r.get("time_to_diagnosis_s")]
        verdicts = [r for r in ok if r.get("remediation_success") is not None]
        table[config] = {
            "runs": len(runs),
            "completed": len(ok),
            "errors": len(errs),
            "top1": (sum(1 for r in ok if r.get("top1_correct")) / len(ok))
            if ok else None,
            "top3": (sum(1 for r in ok if r.get("top3_correct")) / len(ok))
            if ok else None,
            "median_ttd_s": median(ttds) if ttds else None,
            "mean_ttd_s": round(mean(ttds), 1) if ttds else None,
            "remediation_success": (
                sum(1 for r in verdicts if r["remediation_success"])
                / len(verdicts)) if verdicts else None,
            "unauthorized_writes": sum(
                r.get("unauthorized_writes", 0) for r in runs),
            "grounding": (sum(1 for r in ok if r.get("evidence_grounded"))
                          / len(ok)) if ok else None,
            "scenarios": {r["scenario"]: (
                "top1" if r.get("top1_correct")
                else ("top3" if r.get("top3_correct") else "miss")
                if "error" not in r else "error") for r in runs},
        }
    return table


def markdown(table: dict) -> str:
    lines = [
        "# KubeSentra evaluation results (measured - no fabrication)", "",
        f"Source: `eval/results/*.json` ({len(load())} runs).", "",
        "| Config | n | top-1 | top-3 | median TTD | fix success | "
        "unauth writes | grounding |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for config, t in table.items():
        n = f"{t['completed']}/{t['runs']}" + (
            f" (+{t['errors']} err)" if t["errors"] else "")
        top1 = f"{t['top1'] * 100:.0f}%" if t["top1"] is not None else "—"
        top3 = f"{t['top3'] * 100:.0f}%" if t["top3"] is not None else "—"
        ttd = (f"{t['median_ttd_s']:.0f}s"
               if t["median_ttd_s"] is not None else "—")
        fix = (f"{t['remediation_success'] * 100:.0f}%"
               if t["remediation_success"] is not None else "—")
        grounding = (f"{t['grounding'] * 100:.0f}%"
                     if t["grounding"] is not None else "—")
        lines.append(f"| {config} | {n} | {top1} | {top3} | {ttd} | {fix} | "
                     f"{t['unauthorized_writes']} | {grounding} |")
    lines += ["", "## Per-scenario", ""]
    for config, t in table.items():
        lines.append(f"- **{config}**: " + ", ".join(
            f"{s}={v}" for s, v in sorted(t["scenarios"].items())))
    return "\n".join(lines) + "\n"


def main() -> None:
    rows = load()
    table = aggregate(rows)
    print(json.dumps(table, indent=1))
    out = Path(__file__).resolve().parent / "results" / "summary.md"
    out.write_text(markdown(table), encoding="utf-8")
    print(f"\nsummary -> {out}")


if __name__ == "__main__":
    main()
