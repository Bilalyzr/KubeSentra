# KubeSentra — Kubernetes Incident Response Agent

An AI-powered, multi-agent incident investigation and response system for
Kubernetes. When Alertmanager fires, KubeSentra triages the alert, deploys
specialist agents (metrics, logs, Kubernetes state) to collect evidence,
produces an evidence-cited root-cause diagnosis, proposes a remediation from
a strict action allowlist, and **executes nothing without explicit human
approval** — then verifies the fix and writes a postmortem to incident memory.

**Status: Phase 2 of 10 — Kubernetes laboratory.**
See [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) for the phase plan,
verification gates and current state.

## Requirements

- Python 3.11+
- Docker Desktop
- Git Bash (Windows) or any POSIX shell
- `kind` and `helm` on PATH (installed to `~/bin` on this machine — see docs)

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

## What works now

**Phase 1 — foundation**
- Validated configuration from environment / `.env` (pydantic-settings)
- PostgreSQL 16 + pgvector in Docker Compose with a healthcheck
- Versioned SQL migrations: pgvector extension + core schema
  (`runbook_chunks`, `incidents`, `evidence_raw`, `audit_log`) with HNSW
  vector and GIN full-text indexes
- FastAPI `/health` + `/ready` (readiness performs a real database query)

**Phase 2 — Kubernetes laboratory**
- Reproducible kind cluster (`incident-lab`, 1 control plane + 2 workers,
  v1.36.1) via `scripts/lab_up.sh` — idempotent, safe to re-run
- Google Online Boutique v0.10.7 (11 microservices) in the `boutique` namespace
- kube-prometheus-stack (Prometheus + Alertmanager + Grafana) with custom
  fast-firing alert rules (`PodRestarting`, `PodNotReady`,
  `DeploymentReplicasUnavailable`, `HighErrorRate`, `HighP95Latency`)
- Loki (single-binary) + Grafana Alloy log collection
- Chaos Mesh (containerd runtime)
- 5 fault scenarios with inject/cleanup scripts and ground-truth labels
- Alertmanager webhook is pre-configured to POST to
  `http://host.docker.internal:8547/alerts` (the KubeSentra ingestion
  endpoint, implemented in Phase 4)

### Lab commands

```bash
scripts/lab_up.sh                       # create/refresh the whole lab
scripts/lab_health.sh [--wait]          # verify every layer
scripts/inject_fault.sh oom_checkout    # inject a fault scenario
scripts/cleanup_fault.sh oom_checkout   # roll the target back to healthy
scripts/lab_down.sh                     # delete the cluster (Postgres kept)
```

Lab endpoints: Prometheus `http://127.0.0.1:9090` · Alertmanager
`http://127.0.0.1:9093` · Grafana `http://127.0.0.1:3000` (admin / kubesentra)
· Loki `http://127.0.0.1:13100`

Fault scenarios (see `eval/scenarios/`): `oom_checkout`,
`crashloop_frontend`, `imagepull_currency`, `readiness_recommendation`,
`cpu_adservice`.

## Not built yet (by design)

MCP tool servers, LangGraph agents, approval workflow, Streamlit dashboard,
expanded fault catalogue and evaluation — each phase builds and **verifies**
one layer before the next begins. The roadmap and its verification gates live
in [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md).
