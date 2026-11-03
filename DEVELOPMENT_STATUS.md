# KubeSentra — Development Status

**Last updated:** 2026-11-03 · **Phase 1 COMPLETE** (verification gate passed)

This document is the single source of truth for project progress. It is
updated at the end of every phase's build → verify loop, with real results.

---

## Current phase

Phase 1 — Project foundation: **complete and verified**. Next: Phase 2 (Kubernetes laboratory).

## Phase tracker

| # | Phase | Status | Verification gate | Gate result |
|---|---|---|---|---|
| 1 | Project foundation | ✅ Complete | tests green · DB live · health endpoints respond | **PASS** (2026-11-03, evidence below) |
| 2 | Kubernetes laboratory | Not started | kind/helm installed · pods Running · Prometheus targets up · injected fault fires an alert · lab-up reproducible | — |
| 3 | MCP read servers | Not started | every tool returns validated, capped, redacted output against the live cluster | — |
| 4 | Single-agent baseline + webhook | Not started | alert → incident → investigation runs end to end | — |
| 5 | Multi-agent LangGraph | Not started | supervisor loop obeys budgets · every RCA claim cites valid evidence IDs | — |
| 6 | RAG + remediation + approval interrupt | Not started | graph pauses durably · edited plans re-validated | — |
| 7 | k8s-write + executor + verifier | Not started | **zero writes without approval** · protected namespaces blocked · injection fails closed | — |
| 8 | Streamlit dashboard | Not started | every control calls the real backend | — |
| 9 | Security tests + evaluation (B0, E1–E5) | Not started | measured results only, no fabricated numbers | — |
| 10 | Docs + final delivery | Not started | full setup reproducible from scratch | — |

## Phase 1 verification evidence (2026-11-03)

| # | Check | Result |
|---|---|---|
| 1 | venv (Python 3.11.11) + `pip install -e ".[dev]"` with exact pins | OK — fastapi 0.162.0, uvicorn 0.54.0, pydantic 2.14.2, pydantic-settings 2.16.2, psycopg 3.3.7, psycopg-pool 3.3.3, httpx 0.28.1, pytest 9.2.0, pytest-asyncio 1.4.1.post1 |
| 2 | Import check (`common.config`, `database.*`, `api.main`) | OK |
| 3 | `docker compose config` valid; `up -d postgres` | container `kubesentra-postgres` **healthy** in ~9 s; `pg_isready` accepting connections |
| 4 | Migrations run #1 | applied 0001_extensions, 0002_core_tables |
| 5 | Migrations run #2 (idempotency) | 0 applied — no duplicates, no errors |
| 6 | `pytest -v` | **15/15 passed** (8 unit + 7 integration incl. pgvector VECTOR(384) roundtrip, generated tsv column, JSONB audit insert) in 2.27 s |
| 7 | Live endpoints on port 8547 | `GET /health` → 200 `{"status":"ok","app":"KubeSentra",...}` · `GET /ready` → 200 `{"status":"ready","database":"connected"}` (real DB query) |
| 8 | Issue found & fixed during verification | Port **8000 is occupied** by another local project (uvicorn `Errno 10048`; a different service answered there). KubeSentra default moved to **8547** in `.env`, `.env.example`, `Makefile`, `scripts/dev.sh`, `README.md` |

## Completed modules (Phase 1)

- Repository scaffolding: `pyproject.toml` (pinned deps), `docker-compose.yml`,
  `Makefile`, `scripts/dev.sh`, `.env.example` → `.env`, `.gitignore`, this tracker
- `common/config.py` — pydantic-settings configuration (env vars override `.env`)
- `database/connection.py` — psycopg3 pool + readiness query
- `database/migrate.py` — versioned SQL migration runner (transactional, one-time)
- `database/migrations/` — 0001 pgvector extension; 0002 core schema
  (`runbook_chunks`, `incidents`, `evidence_raw`, `audit_log`) with HNSW vector,
  GIN full-text and lookup indexes
- `api/main.py` — FastAPI `/health` (liveness) + `/ready` (real dependency check)
- Tests: 4 config, 4 API, 7 database-integration (auto-skip when DB down)

## Pending modules

- Phase 2: kind cluster, Online Boutique, kube-prometheus-stack, Loki + Alloy,
  Chaos Mesh, custom alert rules, 5 initial fault scenarios

## Known issues / environment notes

- **Port 8000 is taken by another local project** — KubeSentra API uses **8547**
- Docker Desktop daemon is not auto-started — start Docker Desktop before docker/compose
- Docker Hub pulls on this network are flaky (TLS timeouts / `unexpected EOF`);
  retrying `docker pull` until success works — expect retries in Phase 2 image pulls
- `kind` and `helm` are **not installed** — Phase 2 installs them first
- 15.7 GB RAM → reduced-resource configs (short Prometheus retention, trimmed
  Online Boutique) per the implementation document
- Windows: use Git Bash; `make` is **not available** here → `scripts/dev.sh <cmd>`

## Tests

| Date | Suite | Result |
|---|---|---|
| 2026-11-03 | pytest (8 unit + 7 integration) | **15 passed, 0 failed** (2.27 s) |

## Next task

**Phase 2 — Kubernetes laboratory**, starting with: install `kind` + `helm`,
create the kind cluster (1 control plane + 2 workers, reduced resources),
deploy Online Boutique into `boutique` namespace, then kube-prometheus-stack
→ Loki/Alloy → Chaos Mesh, with the gate: *an injected fault actually fires
an alert*.
