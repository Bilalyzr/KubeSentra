# KubeSentra — Architecture

*Everything in this document is implemented and verified; phase-gate
evidence lives in [DEVELOPMENT_STATUS.md](../DEVELOPMENT_STATUS.md).*

## High-level view

```
Alertmanager ──firing alert──▶ FastAPI webhook (POST /alerts)
                                   │ dedupe (fingerprint+window) ──▶ incidents table
                                   ▼
                        LangGraph investigation graph
   triage ─▶ supervisor ─▶ metrics / logs / k8s specialists (loop)
                        └─▶ diagnose ─▶ remediate ─▶ APPROVAL INTERRUPT ⏸
                                                        │ human decision
                                                        ▼ (approved/edited)
                                              execute (k8s-write MCP) ─▶ verify ─▶ postmortem
```

- **Alert ingestion** (`api/routes/webhook.py`, `api/dedupe.py`): parses
  Alertmanager v2 payloads, ignores protected/namespace-less alerts,
  deduplicates by `alertname|namespace|service` within a 10-minute window
  (occurrence counter), resolves on `resolved` notifications — but never
  closes an incident that is investigating or awaiting approval.
- **Investigation** (`agent/graph.py`): the state machine below, checkpointed
  to PostgreSQL (thread = incident id), 1200 s wall clock, hard step budget.
- **Human gate**: the graph pauses at `interrupt()` with the diagnosis,
  validated plan and per-action dry-run results; only
  `POST /incidents/{id}/decision` (token-authenticated, paused-thread
  checked) resumes it. Edited plans are re-validated; invalid edits
  re-interrupt with the policy error (3 strikes → rejected).
- **Execution** (`agent/nodes/executor.py`): fail-closed (approval state AND
  approvals row), per-action revalidation + fresh dry-run, one MCP call per
  action via the write server, duplicate-execution guard.
- **Verification** (`agent/nodes/verifier.py`): deterministic — pods-ready
  poll, original-alert-cleared, restart pre/post comparison →
  RESOLVED / PARTIALLY_RESOLVED / NOT_RESOLVED / VERIFICATION_FAILED.
- **Memory**: postmortem + embedding written back to the incidents row;
  triage retrieves the top-3 similar past incidents as hints-to-verify.

## Agent workflow (state machine)

Nodes: `triage → supervisor → {metrics_agent | logs_agent | k8s_agent} →
supervisor … → diagnose → remediate → approval ⏸ → execute → verify →
postmortem → END` (rejected/escalated paths skip to postmortem).

Supervisor **hard rules run before any LLM call** (pure, unit-tested):
- steps ≥ 15 → diagnose (if any hypothesis ≥ 0.5) else escalate
- top hypothesis ≥ 0.8 with supporting evidence from ≥ 2 sources → diagnose
- loop-guard: a specialist chosen 3× consecutively is rotated out

Evidence is append-only in state (`operator.add` reducer); raw tool output
goes to `evidence_raw`, only summaries enter LLM context. Diagnoser
citations are validated in code — invalid IDs are dropped; an ungrounded
diagnosis is confidence-capped at 0.5.

## MCP integration (the tool layer)

| Server | Tools | Credential | Writes? |
|---|---|---|---|
| `mcp_servers/k8s_read` | list_pods, describe_pod, get_events, get_pod_logs, get_rollout_history, diff_rollout_revisions, get_resource_usage, get_configmap (redacted) | `kubesentra-reader` SA (get/list/watch; **no Secrets**) | never |
| `mcp_servers/prometheus` | 16 named query templates, validated free-form range, firing alerts | read-only HTTP | never |
| `mcp_servers/loki` | raw LogQL query, pattern-grouped error extraction | read-only HTTP | never |
| `mcp_servers/knowledge` | hybrid runbook search (RRF), similar incidents (pgvector), keyword incident search, embedded save | DB only | DB rows only |
| `mcp_servers/k8s_write` | **exactly five allowlisted actions** | `kubesentra-executor` SA — Role in `boutique` ONLY | **the only cluster-write path** |

Every tool validates inputs, enforces namespace policy, redacts secrets,
caps output (4 KB) and wraps untrusted content in `<untrusted-data>`
delimiters before anything reaches an LLM.

Investigation agents load ONLY the four read servers (`agent/tools.py`,
enforced by a security test). The write server is invoked exclusively by
the executor, programmatically per approved action — never as an LLM tool.

## Component map (repository)

```
api/        FastAPI: webhook, incidents, decisions, stats, runbooks
agent/      state, graph, nodes (triage/supervisor/specialists/diagnose/
            remediation/approval/executor/verifier/postmortem), guardrails
mcp_servers/  the five MCP servers above
knowledge/  23 runbooks + ingest (bge-small-en-v1.5, 115 chunks)
database/   psycopg pool, migrations 0001-0004, services
dashboard/  Streamlit (9 pages) — reads only through the API
eval/       scenario runner, LLM judge, aggregator, charts
scripts/    lab_up/lab_down, inject/cleanup faults, gates, kubeconfigs
deploy/     kind config, RBAC (reader+executor), alert rules, helm values
```

## Database architecture

PostgreSQL 16 + pgvector. Migrations (versioned SQL, `python -m
database.migrate`): 0001 extensions · 0002 core tables (runbook_chunks with
generated tsv + HNSW, incidents, evidence_raw, audit_log) · 0003 incident
workflow columns · 0004 approvals. LangGraph checkpoints live in the same
database (thread = incident id). Full details: [database.md](database.md).

## Approval workflow (safety architecture)

Layered, each layer independently tested:
1. Alert labels/logs/events = untrusted data (delimiters + tests)
2. Planner may only propose from the 5-action allowlist
3. `validate_plan` (code): namespace, params (scale 1–5, quantities,
   ≤2× live state, absolute caps, name ≤253), plan ≤3 actions
4. Server-side dry-run (`dry_run=All`) per action via the executor Role
5. Durable human interrupt; token-authenticated decision endpoint with
   paused-thread verification; edits re-validated (re-interrupt on failure)
6. Executor fail-closed (state + approvals row) + preflight re-dry-run
7. RBAC blast radius: executor Role exists only in `boutique`
8. Every write audited; DB invariant tested: **zero write events without a
   prior approval record** — measured 0 violations across the campaign

Details: [security.md](security.md). Measured results:
[phase9-results.md](report/phase9-results.md).
