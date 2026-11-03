"""Versioned SQL migration runner.

Migrations are plain .sql files in database/migrations named
``NNNN_description.sql``. Each file is applied exactly once, inside a
transaction, and recorded in the ``schema_migrations`` table.

Usage:
    python -m database.migrate            # apply pending migrations
    python -m database.migrate --status   # show applied/pending migrations
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import psycopg

from common.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_FILE_RE = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")


def discover_migrations() -> list[tuple[str, Path]]:
    """Return (version, path) pairs sorted by version, validating names."""
    found: list[tuple[str, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _FILE_RE.match(path.name)
        if match is None:
            sys.exit(f"[migrate] unparsable migration filename: {path.name}")
        found.append((match.group("version"), path))
    versions = [version for version, _ in found]
    if len(versions) != len(set(versions)):
        sys.exit("[migrate] duplicate migration version numbers detected")
    if not found:
        sys.exit(f"[migrate] no migrations found in {MIGRATIONS_DIR}")
    return found


def ensure_tracking_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.commit()


def applied_versions(conn: psycopg.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def run(apply_pending: bool = True) -> int:
    migrations = discover_migrations()
    with psycopg.connect(get_settings().database_url) as conn:
        ensure_tracking_table(conn)
        done = applied_versions(conn)

        pending = [(v, p) for v, p in migrations if v not in done]
        applied = [(v, p) for v, p in migrations if v in done]

        if not apply_pending:
            for version, path in migrations:
                state = "applied" if version in done else "pending"
                print(f"  {version}  {path.stem:40s} [{state}]")
            return 0

        for version, path in pending:
            sql = path.read_text(encoding="utf-8")
            conn.execute(sql)  # single call; each file is one transaction below
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                (version, path.stem),
            )
            conn.commit()  # commit per migration: partial runs never half-apply
            print(f"[migrate] applied {version} {path.stem}")

        print(f"[migrate] done: {len(applied) + len(pending)} total, "
              f"{len(pending)} applied this run, {len(applied)} previously applied")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply KubeSentra SQL migrations")
    parser.add_argument("--status", action="store_true", help="list migrations without applying")
    args = parser.parse_args()
    try:
        sys.exit(run(apply_pending=not args.status))
    except psycopg.OperationalError as exc:
        print(f"[migrate] cannot reach PostgreSQL: {exc}", file=sys.stderr)
        print("[migrate] start it first: docker compose up -d postgres", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
