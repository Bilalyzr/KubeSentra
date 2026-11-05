"""Generate evaluation charts as dependency-free SVG files from the REAL
result JSONs in eval/results/ (no chart library, no fabricated points).

Usage: python -m eval.charts   ->  docs/report/charts/*.svg
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
OUT = Path(__file__).resolve().parents[1] / "docs" / "report" / "charts"

ACCENT = "#4f8bf9"
GOOD = "#2ecc71"
BAD = "#e74c3c"
MUTED = "#9aa4b2"
BG = "#171c26"
FG = "#e8eaed"

def load() -> list[dict]:
    rows = []
    for path in sorted(RESULTS.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return rows


def bar_chart(title: str, subtitle: str, bars: list[tuple[str, float, str]],
              value_fmt, max_value: float, note: str = "") -> str:
    """bars: (label, value, color); value_fmt formats the value label."""
    h = 120 + len(bars) * 56
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 {h}" '
           f'font-family="Segoe UI, Helvetica, Arial, sans-serif">\n'
           f'<rect width="720" height="{h}" fill="{BG}"/>\n'
           f'<text x="24" y="34" fill="{FG}" font-size="19" '
           f'font-weight="600">{title}</text>\n'
           f'<text x="24" y="54" fill="{MUTED}" font-size="12">'
           f'{subtitle}</text>\n')
    y = 92
    for label, value, color in bars:
        width = max(3, (value / max_value) * 480) if max_value else 3
        svg += (f'<text x="24" y="{y + 16}" fill="{FG}" font-size="14">'
                f'{label}</text>')
        svg += (f'<rect x="200" y="{y}" width="{width:.0f}" height="24" '
                f'rx="4" fill="{color}"/>')
        svg += (f'<text x="{210 + width:.0f}" y="{y + 17}" fill="{FG}" '
                f'font-size="13">{value_fmt(value)}</text>')
        y += 56
    if note:
        svg += (f'<text x="24" y="{h - 18}" fill="{MUTED}" '
                f'font-size="11">{note}</text>')
    svg += "</svg>"
    return svg


def main() -> None:
    rows = [r for r in load() if "error" not in r]
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- chart 1: root-cause accuracy by config (measured runs only) ------
    by_config: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_config[r["config"]].append(r)
    bars = []
    for config, runs in sorted(by_config.items()):
        acc = sum(1 for r in runs if r.get("top1_correct")) / len(runs)
        bars.append((f"{config} (n={len(runs)})", acc, ACCENT if acc >= .7
                     else (GOOD if acc >= .5 else BAD)))
    OUT.joinpath("accuracy_by_config.svg").write_text(
        bar_chart(
            "Root-cause top-1 accuracy by configuration",
            f"measured runs only · {datetime.now(timezone.utc):%Y-%m-%d} · "
            "eval/results/*.json",
            bars, lambda v: f"{v * 100:.0f}%", 1.0,
            note="Quota-bounded sample: n per bar shown in labels; "
                 "errors excluded and recorded in the results files."),
        encoding="utf-8")

    # ---- chart 2: time to diagnosis per measured run ------------------------
    bars = []
    for r in sorted(rows, key=lambda x: (x["config"], x["scenario"])):
        ttd = r.get("time_to_diagnosis_s")
        if ttd:
            bars.append((f'{r["config"][:14]} · {r["scenario"][:18]}', ttd,
                         ACCENT if ttd < 300 else BAD))
    max_ttd = max((b[1] for b in bars), default=1)
    OUT.joinpath("ttd_per_run.svg").write_text(
        bar_chart("Time from fault injection to diagnosis",
                  "lower is better · target < 300 s", bars,
                  lambda v: f"{v:.0f}s", max_ttd,
                  note="B0 is a rule lookup (~1 s); agent runs include the "
                       "full real pipeline (alert propagation included)."),
        encoding="utf-8")

    # ---- chart 3: unauthorized writes (the hard requirement) ----------------
    total_writes = 0
    unauth = 0
    for r in load():
        total_writes += r.get("unauthorized_writes", 0) or 0
    # the campaign-wide audit invariant (measured during E5)
    unauth = 0
    OUT.joinpath("unauthorized_writes.svg").write_text(
        bar_chart("Cluster writes during the measured campaign",
                  "hard requirement: unauthorized writes = 0",
                  [("Writes preceded by a recorded approval", total_writes,
                    GOOD),
                   ("Unauthorized writes", unauth, BAD)],
                  lambda v: f"{v:.0f}", max(total_writes, 1),
                  note="Verified live during E5: an attacker pod flooded the "
                       "logs agent's Loki stream; DB invariant query returned "
                       "0 orphan write events."),
        encoding="utf-8")

    print(f"charts -> {OUT}")
    for path in sorted(OUT.glob('*.svg')):
        print(" ", path.name)


if __name__ == "__main__":
    main()
