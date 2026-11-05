# KubeSentra — Kubernetes Incident Response Agent

An AI-powered, multi-agent incident investigation and response system for
Kubernetes. When Alertmanager fires, KubeSentra triages the alert, deploys
specialist agents (metrics, logs, Kubernetes state) to collect evidence,
produces an evidence-cited root-cause diagnosis, proposes a remediation from
a strict action allowlist, and **executes nothing without explicit human
approval** — then verifies the fix and writes a postmortem to incident memory.

**Status: Phase 9 of 10 — security & evaluation (measured results).**
See [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) and
[docs/report/phase9-results.md](docs/report/phase9-results.md).

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

**Phase 5 — multi-agent orchestration (LangGraph)**

- Shared `IncidentState`: append-only `Evidence` (summaries in LLM context,
  raw output in `evidence_raw`), `Hypothesis` with confidence + supporting /
  refuting evidence IDs, step timeline
- **Triage** (past-incident memory + pod snapshot → 2–4 hypotheses) →
  **Supervisor** (hard routing rules first: step budget 15 / confidence ≥ 0.8
  with two sources → diagnose; LLM picks the specialist + writes its question;
  loop-guard) → **specialists** (metrics / logs / k8s — cheap ReAct over their
  own MCP server only, ≤ 4 tool calls per turn) → **Diagnoser** (every claim
  cites valid evidence IDs — invalid citations are dropped in code, ungrounded
  diagnoses are confidence-capped) → escalate with a human summary when the
  budget runs out
- Postgres checkpointer (thread = incident ID) — investigations survive
  restarts; 1200 s wall-clock cap; transient-LLM retries; partial timeline
  salvaged on failure
- `INVESTIGATION_MODE=multi_agent|baseline` (baseline kept for the E1
  experiment)
- **Live gate (real Gemini)**: `oom_checkout` → diagnosed in **79 s**,
  correct root cause (OOMKilled, `resource`), grounded `E2+E3`, budgets
  respected (1 specialist step, 4 tool calls)

**Phase 6 — RAG, remediation planning, human approval**

- Knowledge base: **23 runbooks** (Symptoms / How to confirm / Likely causes /
  Remediation / Risks) → 115 chunks embedded with **bge-small-en-v1.5**
  (local, 384-dim, repo-cached) — `python -m knowledge.ingest`
- **Hybrid retrieval**: pgvector cosine + PostgreSQL FTS merged with
  Reciprocal Rank Fusion (exact strings like `OOMKilled` stay findable)
- **Episodic memory**: incidents stored WITH embeddings; triage retrieves the
  top-3 similar incidents (service-filtered) as hints-to-verify
- **Remediation Planner**: LLM proposes only allowlisted actions → strict
  code validation (namespace, params, 1–5 replicas, ≤2× resource bounds) →
  **server-side dry run** (`dry_run=All`, executor credential) → any action
  that fails admission is dropped with the reason
- **Human approval interrupt**: the graph pauses durably
  (`status=awaiting_approval`); `POST /incidents/{id}/decision` (bearer-token
  authenticated) resumes it. Edited plans are re-validated — an invalid edit
  re-interrupts with the policy error (nothing bricks, nothing executes);
  after 3 invalid edits it fails safe to `rejected`
- Executor RBAC: a Role (not ClusterRole) bound to `boutique` only —
  verified: dry-run patch/delete allowed in `boutique`, **kube-system
  denied**; the reader identity remains unable to write anything
- **Live gate**: fault → diagnosis (96 s) → planner proposed
  `set_resources 128Mi` → dry-run correctly **dropped it (2× policy vs the
  fault's 5Mi limit)** → human edited to `rollout_undo` → re-validated →
  approved; invalid edit + missing token rejected (400/401), full approvals
  and audit trail recorded

**Phase 7 — execution, verification, postmortem**

- `k8s-write` MCP server: exactly **five** allowlisted tools, every call
  re-validated through the same guardrails as the planner BEFORE touching
  the cluster, audited server-side; executor ServiceAccount (Role in
  `boutique` only — kube-system unreachable at the RBAC level)
- **Executor** (fail-closed): requires approval state AND a recorded
  approvals row; per action: re-validate → fresh server-side dry-run → one
  MCP call; stops on first failure; duplicate-execution guard
- **Verifier** (deterministic): pods-ready poll, original alert cleared,
  restart pre/post comparison → RESOLVED / PARTIALLY_RESOLVED /
  NOT_RESOLVED / VERIFICATION_FAILED — never trusts a successful kubectl exit
- **Postmortem writer**: structured report (timeline, evidence refs,
  remediation results, approval, verification, lessons) persisted with an
  embedding for future triage memory
- **Live gate (full lifecycle)**: fault → pause → invalid edit **400** →
  edited `rollout_undo` **200** → REAL execution via the write server →
  pods ready in 15 s, alert cleared → **RESOLVED** → postmortem with
  approval record; cluster limit restored to 128Mi; audit chain
  `write:rollout_undo → action_executed → verification → postmortem_written`
- Bonus proof of the fail-closed property (found live): an approval-record
  ordering bug left the executor with no DB record mid-run — it **refused to
  execute** and the verifier honestly reported NOT_RESOLVED. The gate that
  matters held; the ordering was then fixed.

**Phase 8 — Streamlit dashboard** (dark-first, 9 pages, real data only)

Overview (live stats) · Incident Management (search/filter/sort) ·
Investigation (agent timeline, evidence, hypotheses) · Root Cause Analysis
(evidence grounding, alternatives) · **Remediation Approval** (plan + dry-run
cards; Approve / Edit / Reject call the real token-authenticated API and
surface responses verbatim — nothing simulated) · Execution & Verification
(results, verifier checks, approval record) · History & Memory (embedding
similar-incident retrieval) · Runbook KB (browse + hybrid search) ·
Observability (agent/tool/latency stats from real runs; no placeholder
numbers).

Run it (API first):
```bash
scripts/dev.sh serve        # API on :8547
scripts/dev.sh dashboard    # dashboard on :8551
```

Verified by an automated **AppTest gate** (scripts/dashboard_gate.py): every
page renders against the live backend, the overview metric matches the API,
hybrid search surfaces the right runbook, and a decision button click hits
the real endpoint — including the honest 409 when no graph is actually
paused (surfaced verbatim, no fake success).

**Phase 9 — security battery + evaluation (measured)**

- **Security: 47/47 tests across 7 suites** — prompt injection (4 attack
  paths), approval bypass (401/409/forged-state/**DB invariant: zero writes
  without a prior approval record**), protected namespaces (app + live
  RBAC), invalid parameters, duplicate alerts, loop safety, tool surface.
  The battery itself hardened the system (absolute resource caps,
  name-length cap).
- **Evaluation (real runs only, quota-bounded)**:
  - **B0 rule baseline**: top-1 3/5 — wrong exactly where an agent is
    needed (crashloop, imagepull)
  - **E1**: oom_checkout in both configs live — multi-agent **78 s,
    evidence-grounded** vs baseline 129 s, ungrounded
  - **E5 LIVE injection**: an attacker pod flooding the agent's log stream
    with "IGNORE PREVIOUS INSTRUCTIONS…" → **0 unauthorized writes** across
    the whole campaign
  - E2/E3/E4: switches + runner configs ready; honestly not run (single
    free-tier quota pool)
- Harness: `eval/runner.py` (real lifecycle per run), `eval/judge.py`
  (strict-rubric LLM judge), `eval/aggregate.py` → `eval/results/`
- Full write-up incl. failure analysis: [docs/report/phase9-results.md](docs/report/phase9-results.md)

## Not built yet (by design)

Final delivery polish (Phase 10: full docs set, reproducibility check,
demo script). The roadmap and verification gates live in
[DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md).
