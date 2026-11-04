"""Ingest knowledge/runbooks/*.md into the runbook_chunks table.

Each `## Section` becomes one chunk with:
- runbook name, section title, section content (FTS via the generated tsv)
- front-matter tags as the symptoms array
- a bge-small-en-v1.5 embedding (384 dims) for semantic retrieval

Re-runs are safe: chunks are replaced per runbook.
Usage: python -m knowledge.ingest [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from common.embeddings import embed_texts
from database.connection import get_pool

RUNBOOKS_DIR = Path(__file__).resolve().parent / "runbooks"
SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)
WANTED_SECTIONS = ("symptoms", "how to confirm", "likely causes",
                   "remediation", "risks")


def parse_runbook(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    tags: list[str] = []
    if text.startswith("---"):
        _, front, body = text.split("---", 2)
        try:
            meta = yaml.safe_load(front) or {}
            tags = [str(t) for t in (meta.get("tags") or [])]
        except yaml.YAMLError:
            body = text
    else:
        body = text

    title = ""
    m = re.match(r"\s*#\s+(.+)", body)
    if m:
        title = m.group(1).strip()
    sections: list[tuple[str, str]] = []
    parts = SECTION_RE.split(body)
    # parts: [before-first-header, header1, body1, header2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        sections.append((parts[i].strip(), parts[i + 1].strip()))
    return {"name": title or path.stem, "tags": tags, "sections": sections}


def load_runbooks() -> list[dict]:
    books = []
    for path in sorted(RUNBOOKS_DIR.glob("*.md")):
        parsed = parse_runbook(path)
        parsed["file"] = path.name
        books.append(parsed)
    return books


def run(dry_run: bool = False) -> int:
    books = load_runbooks()
    if not books:
        print(f"[ingest] no runbooks found in {RUNBOOKS_DIR}", file=sys.stderr)
        return 1

    rows = []  # (runbook, section, content, symptoms)
    for book in books:
        for section, content in book["sections"]:
            rows.append((book["name"], section, content, book["tags"]))
    print(f"[ingest] {len(books)} runbooks -> {len(rows)} chunks")

    if dry_run:
        for runbook, section, _, _ in rows[:10]:
            print(f"  {runbook} :: {section}")
        return 0

    vectors = embed_texts([f"{r[0]} - {r[1]}\n{r[2]}" for r in rows])
    assert len(vectors) == len(rows)

    with get_pool().connection() as conn:
        for book in books:
            conn.execute("DELETE FROM runbook_chunks WHERE runbook = %s",
                         (book["name"],))
        for (runbook, section, content, tags), vec in zip(rows, vectors):
            conn.execute(
                "INSERT INTO runbook_chunks (runbook, section, content, "
                "symptoms, embedding) VALUES (%s, %s, %s, %s, %s::vector)",
                (runbook, section, content, tags, str(vec).replace(" ", "")),
            )
    print(f"[ingest] wrote {len(rows)} chunks with 384-dim embeddings")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest runbooks")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and list chunks without writing")
    args = parser.parse_args()
    sys.exit(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
