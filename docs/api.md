# KubeSentra — API Documentation

Base URL (dev): `http://127.0.0.1:8547` · OpenAPI/Swagger:
`/docs` (served by FastAPI) · start with `scripts/dev.sh serve`.

## Endpoints

### POST /alerts — Alertmanager webhook (unauthenticated, as Alertmanager sends it)
Request: Alertmanager v2 payload (`alerts[]` with `status`, `labels`,
`annotations`). Firing alerts for non-protected, non-empty namespaces are
deduplicated (fingerprint `alertname|namespace|derived-service`, 10-min
window) and create an incident + background investigation; duplicates
attach (occurrence counter); `resolved` alerts close only passively-open
incidents (never investigating/awaiting_approval — the Verifier owns that
verdict).

Response `200`:
```json
{"ok": true, "received": 1, "created": ["<uuid>"], "attached": 0,
 "resolved": 0, "ignored_protected": 0}
```
Errors: none expected — malformed payloads are 422 via Pydantic.

### GET /incidents?status=&limit=
Response: `{"count": n, "incidents": [{id, created_at, alert_name,
namespace, service, status, root_cause, root_cause_category, summary,
actions{approval_payload, timeline}, alert_labels, time_to_diagnosis_s,
resolved, error}, …]}` newest first.

### GET /incidents/{id}
Single incident (above shape) · `404` if unknown.

### GET /incidents/{id}/timeline
Audit events: `[{time, actor, event, detail}, …]` in order.

### GET /incidents/{id}/evidence
Raw evidence payloads: `[{id: "E1", source, raw, created}, …]`.

### GET /incidents/{id}/postmortem
Parsed postmortem JSON (overview, timeline, evidence_references,
remediation results, approval, verification, lessons_learned) or
`{"postmortem": null, "summary_text": …}` before completion.

### POST /incidents/{id}/decision — the human gate
Headers: `X-Approval-Token: <APPROVAL_TOKEN from .env>` (constant-time
compared). Body:
```json
{"status": "approved" | "edited" | "rejected",
 "approver": "name", "plan": [ …only for edited… ]}
```
Behaviour: 401 bad/missing token · 404 unknown incident · 409 not
`awaiting_approval` or **no real paused graph interrupt** (fail closed) ·
400 edited-without-plan · 400 invalid edited plan (re-validation error
surfaced verbatim; graph stays paused; no approval record kept) ·
200 `{"ok": true, "status": "approved|edited|rejected"}` — approved/edited
resume the graph through execute → verify → postmortem.

### GET /stats
Real computed overview metrics (counts by status, avg TTD,
verifier-verdict-based remediation success, recent incidents).

### GET /runbooks · GET /runbooks/search?q=
All 23 runbooks with sections/tags; hybrid RAG search (RRF scores).

### GET /health · GET /ready
Liveness; readiness performs a real DB query (503 + error class on
failure).

## Configuration

Everything via environment / `.env` (see `.env.example`): Postgres
coordinates, `PROMETHEUS_URL`/`LOKI_URL`, `APP_NAMESPACE` +
`PROTECTED_NAMESPACES`, kubeconfig paths, LLM provider
(`LLM_PROVIDER=google` for Gemini via the native client — required for
Gemini-3 thought signatures; OpenAI-compatible + Anthropic also supported),
`INVESTIGATION_MODE` (multi_agent | baseline), budgets
(`MAX_INVESTIGATION_STEPS`, `SPECIALIST_MAX_TOOL_CALLS`,
`INVESTIGATION_TIMEOUT_S`), evaluation switches (`MEMORY_ENABLED`,
`RAG_ENABLED`), `APPROVAL_TOKEN`.
