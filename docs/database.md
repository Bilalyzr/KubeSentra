# KubeSentra — Database Documentation

PostgreSQL 16 + pgvector (Docker Compose service `postgres`,
image `pgvector/pgvector:pg16`). Connection pool: psycopg3
(`database/connection.py`), 1–5 connections.

## Migrations

Versioned plain SQL in `database/migrations/NNNN_name.sql`, applied by
`python -m database.migrate` (transactional, once-only, tracked in
`schema_migrations`; `--status` lists applied/pending). Applied in order:

| Version | Contents |
|---|---|
| 0001 | `CREATE EXTENSION vector` |
| 0002 | core schema (below) + indexes |
| 0003 | incidents workflow columns: `status`, `alert_labels` JSONB, `error`; fingerprint + status indexes |
| 0004 | `approvals` table (every write action needs one) |

## Tables

### runbook_chunks — semantic + keyword knowledge base
| column | type | notes |
|---|---|---|
| id | SERIAL PK | |
| runbook | TEXT | e.g. "OOMKilled / memory limit too low" |
| section | TEXT | Symptoms / How to confirm / Likely causes / Remediation / Risks |
| content | TEXT | section body |
| symptoms | TEXT[] | front-matter tags |
| embedding | VECTOR(384) | bge-small-en-v1.5 (local, repo-cached) |
| tsv | TSVECTOR | **generated column** (`to_tsvector('english', content)`) |

Indexes: HNSW (`embedding vector_cosine_ops`), GIN (`tsv`).
Populated by `python -m knowledge.ingest` — 23 runbooks → 115 chunks, all
embedded. Retrieval is hybrid: pgvector cosine + FTS merged with Reciprocal
Rank Fusion (k=60) — exact strings like `OOMKilled` stay findable even when
semantic similarity is low.

### incidents — one row per incident
Key columns: `id UUID PK`, `created_at`, `alert_name`, `namespace`,
`service`, `symptoms`, `root_cause`, `root_cause_category`, `actions JSONB`
(approval payload: plan/dry-runs/hypotheses + agent timeline), `resolved`,
`time_to_diagnosis_s`, `summary` (postmortem JSON after completion),
`embedding VECTOR(384)` (episodic memory), `status` (open → investigating →
diagnosed → awaiting_approval → approved → resolved | rejected | failed |
escalated), `alert_labels JSONB` (fingerprint, labels, occurrences),
`error`.

Indexes: HNSW on embedding, `(namespace, service)`, `created_at`, status,
fingerprint expression index.

### evidence_raw — full tool output (audit, never LLM context)
PK `(incident_id, id)`; `source` = metrics|logs|k8s|change|memory|runbook.
Summaries live in graph state; raw payloads live here, capped at 200 KB,
secret-redacted.

### audit_log — every meaningful action
`incident_id` (nullable FK), `actor` (alertmanager | system | baseline-agent
| multi-agent | kubesentra-write-server | executor | verifier | postmortem |
human:<name>), `event` (incident_created, investigation_started, step:<agent>,
awaiting_approval, approval_decision, approval_edit_invalid, execution_refused,
action_executed, write:<tool>, verification, postmortem_written,
incident_resolved …), `detail JSONB`, `created_at`.

The **security invariant** is a query over this table: no `write:%` event may
exist without a matching earlier approval row — tested in
`tests/security/test_approval_bypass.py` and measured 0-violations during
the live evaluation campaign.

### approvals — the human record
`id UUID PK`, `incident_id FK`, `approver`, `decision`
(approved|edited|rejected, CHECK-constrained), `plan JSONB`, `created_at`.
Written **before** the graph resumes (the executor reads it mid-run);
revoked if an edited plan turns out invalid.

### schema_migrations + LangGraph checkpoints
`schema_migrations` tracks applied SQL. The Postgres checkpointer creates
its own `checkpoints`/`checkpoint_writes`/`checkpoint_blobs` tables
(`saver.setup()`), one thread per incident id — this is what makes the
approval interrupt durable and resumable.

## Repository layer

`api/services/incident_service.py` owns all incident SQL (list/get/timeline/
evidence/stats/approval records); the knowledge MCP server owns retrieval
SQL. Embeddings are computed locally (`common/embeddings.py`,
model cached in `.models/`, git-ignored) with a BGE query-instruction
prefix for retrieval queries.
