# KubeSentra — Kubernetes Incident Response Agent

An AI-powered, multi-agent incident investigation and response system for
Kubernetes. When Alertmanager fires, KubeSentra triages the alert, deploys
specialist agents (metrics, logs, Kubernetes state) to collect evidence,
produces an evidence-cited root-cause diagnosis, proposes a remediation from
a strict action allowlist, and **executes nothing without explicit human
approval** — then verifies the fix and writes a postmortem to incident memory.

**Status: Phase 1 of 10 — project foundation.**
See [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) for the phase plan,
verification gates and current state.

## Requirements

- Python 3.11+
- Docker Desktop (Postgres + pgvector via Compose; the kind cluster arrives in Phase 2)
- Git Bash (Windows) or any POSIX shell

## Quickstart

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip    # Linux: .venv/bin/python
.venv/Scripts/python.exe -m pip install -e ".[dev]"

docker compose up -d postgres          # Postgres 16 + pgvector
.venv/Scripts/python.exe -m database.migrate   # apply SQL migrations

.venv/Scripts/python.exe -m pytest -v  # run tests

.venv/Scripts/python.exe -m uvicorn api.main:app --port 8547
curl http://127.0.0.1:8547/health      # liveness
curl http://127.0.0.1:8547/ready       # readiness (real DB query)
```

Or use `make env up migrate test` / `scripts/dev.sh <command>` on Windows
Git Bash (where `make` is often unavailable).

## What works now (Phase 1)

- Validated configuration from environment / `.env` (pydantic-settings)
- PostgreSQL 16 + pgvector in Docker Compose with a healthcheck
- Versioned SQL migrations: pgvector extension + core schema
  (`runbook_chunks`, `incidents`, `evidence_raw`, `audit_log`) with HNSW
  vector and GIN full-text indexes
- FastAPI `/health` + `/ready` (readiness performs a real database query)
- Unit tests + integration tests against the live database

## Not built yet (by design)

kind lab, monitoring stack, MCP tool servers, LangGraph agents, approval
workflow, Streamlit dashboard, fault injection and evaluation — each phase
builds and **verifies** one layer before the next begins. The roadmap and
its verification gates live in [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md).
