# KubeSentra — Kubernetes Incident Response Agent

An AI-powered, multi-agent incident investigation and response system for
Kubernetes. When Alertmanager fires, KubeSentra triages the alert, deploys
specialist agents (metrics, logs, Kubernetes state) to collect evidence,
produces an evidence-cited root-cause diagnosis, proposes a remediation from
a strict action allowlist, and **executes nothing without explicit human
approval** — then verifies the fix and writes a postmortem to incident memory.

**Status: Phase 4 of 10 — single-agent baseline + alert ingestion.**
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

**Phase 3 — MCP tool servers** (read-only investigation layer)

Four MCP servers (`mcp` SDK 1.x, stdio transport) with validated inputs,
10s timeouts, 4,000-char output caps, secret redaction and untrusted-data
wrapping on every tool:

| Server | Tools |
|---|---|
| `mcp_servers/k8s_read` | `list_pods`, `describe_pod`, `get_events`, `get_pod_logs`, `get_rollout_history`, `diff_rollout_revisions`, `get_resource_usage`, `get_configmap` (values redacted) |
| `mcp_servers/prometheus` | `list_query_templates` (16 tested PromQL templates), `query_template`, `query_range` (validated free-form), `list_firing_alerts` |
| `mcp_servers/loki` | `query_logs`, `error_patterns` (normalized top-N error grouping = log compression) |
| `mcp_servers/knowledge` | `search_incidents`, `get_incident`, `save_incident`, `search_runbooks` (hybrid + RRF arrives with Phase 6 embeddings) |

Run one: `.venv/Scripts/python.exe -m mcp_servers.k8s_read.server`

The k8s-read server uses its **own read-only ServiceAccount**
(`deploy/rbac.yaml`, get/list/watch only — Secrets unreadable, writes
denied, verified by test) via `.secrets/k8s-read.kubeconfig`
(`scripts/gen_mcp_kubeconfigs.sh`). The write server (Phase 7) gets a
separate, narrower credential.

**Phase 4 — alert ingestion + baseline agent**

- `POST /alerts` — Alertmanager webhook (v2 schema): parses firing alerts,
  deduplicates by fingerprint (alertname + namespace + derived service,
  10-minute window, occurrences counter), ignores protected namespaces,
  resolves on `resolved` notifications, audits everything
- `GET /incidents`, `GET /incidents/{id}` — incident queries
- Baseline ReAct agent (`agent/baseline.py`) over the four read-only MCP
  servers with a structured `BaselineReport` output
- Configurable LLM provider (`agent/llm.py`): OpenAI-compatible endpoints
  (OpenAI / OpenRouter / DeepSeek / Groq / Ollama via `LLM_BASE_URL`) or
  Anthropic — set `LLM_*` in `.env`. **Without a key the system fails
  honestly** (incident `status=failed` with a clear error); it never
  simulates an LLM.
- Verified live: injected `oom_checkout` fault → real Alertmanager webhook →
  incident with correct service, dedupe and audit trail (see
  DEVELOPMENT_STATUS.md)

## Not built yet (by design)

LangGraph agents, webhook ingestion, approval workflow, Streamlit dashboard,
expanded fault catalogue and evaluation — each phase builds and **verifies**
one layer before the next begins. The roadmap and its verification gates live
in [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md).
