# KubeSentra — Development Status

**Last updated:** 2026-11-04 · **Phase 4 COMPLETE** (full gate passed with live Gemini diagnoses)

This document is the single source of truth for project progress. It is
updated at the end of every phase's build → verify loop, with real results.

---

## Current phase

Phase 4 — single-agent baseline + alert ingestion: **complete and verified end to end with a live LLM.**
Next: Phase 5 (multi-agent orchestration).

## Phase tracker

| # | Phase | Status | Verification gate | Gate result |
|---|---|---|---|---|
| 1 | Project foundation | ✅ Complete | tests green · DB live · health endpoints respond | **PASS** (2026-11-03) |
| 2 | Kubernetes laboratory | ✅ Complete | pods Running · targets up · injected fault fires an alert | **PASS** (2026-11-03) |
| 3 | MCP read servers | ✅ Complete | every tool verified live: validated inputs, capped/redacted/wrapped outputs; reader RBAC cannot write | **PASS** (2026-11-04) |
| 4 | Single-agent baseline + webhook | ✅ Complete | alert → incident record → investigation runs end to end | **PASS** (2026-11-04, live LLM: both live incidents DIAGNOSED correctly, see below) |
| 5 | Multi-agent LangGraph | Not started | supervisor loop obeys budgets · every RCA claim cites valid evidence IDs | — |
| 6 | RAG + remediation + approval interrupt | Not started | graph pauses durably · edited plans re-validated | — |
| 7 | k8s-write + executor + verifier | Not started | **zero writes without approval** · protected namespaces blocked · injection fails closed | — |
| 8 | Streamlit dashboard | Not started | every control calls the real backend | — |
| 9 | Security tests + evaluation (B0, E1–E5) | Not started | measured results only, no fabricated numbers | — |
| 10 | Docs + final delivery | Not started | full setup reproducible from scratch | — |

## Phase 4 FINAL gate evidence (2026-11-04, live Gemini)

**Gate: injected fault → real alert → webhook → agent investigates → `status=diagnosed` with a real root cause.**

| Incident | Outcome | TTD | Agent tool path |
|---|---|---|---|
| `PodRestarting` (injected `oom_checkout`) | **DIAGNOSED, CORRECT**: "memory limit set extremely low (5Mi) in revision 16 … repeatedly OOMKilled" (category `resource` — matches ground truth; agent even identified the faulty deployment revision) | **51 s** | describe_pod → get_resource_usage → get_rollout_history → diff_rollout_revisions |
| `CPUThrottlingHigh` (organic alert on frontend) | **DIAGNOSED, CORRECT**: "CPU limit 200m too low, 28.51% throttling" (category `resource`) | **33 s** | describe_pod → get_resource_usage → get_events |

Both far under the 5-minute TTD target. Full pipeline verified with real
Alertmanager webhooks (fingerprint dedupe, protected-namespace filtering,
audit trail) — see the earlier Phase 4 evidence rows below for the
webhook/dedupe/API half.

### First baseline results (informal — NOT the E1 evaluation)

2 of 2 live incidents diagnosed with the correct root cause and category by
the single-agent baseline (gemini-flash-lite-latest). Sample size 2; one
scenario was organic rather than from the catalogue. The real, repeated-run
numbers come from the Phase 9 harness. No results are extrapolated from this.

### Gemini integration notes (found during the loop)

- Key format `AQ.…` is a valid current AI-Studio key (older docs say `AIza…`).
- `gemini-2.5-*` models are **404 for new keys** ("no longer available to new users"); current generations: gemini-3.x.
- **Gemini 3 thought signatures**: function calls carry signatures that must round-trip on multi-turn tool loops. The OpenAI-compat endpoint silently drops them via langchain → `400 … missing thought_signature` on the second round trip. Fixed by adding a native `google` provider branch (`langchain-google-genai`), which preserves them. Keep `LLM_PROVIDER=google` for Gemini.
- Free-tier quota: `gemini-3-flash-preview` hit 429 (RESOURCE_EXHAUSTED) during testing; `gemini-flash-lite-latest` / `gemini-3.1-flash-lite` have working quota. Current `.env`: primary `gemini-flash-lite-latest`, cheap `gemini-3.1-flash-lite`. Flip primary back to `gemini-3-flash-preview` when quota resets (it tested OK).
- Gemini returns content as blocks; `baseline.py` already handles list content.

## Phase 4 verification evidence (2026-11-04)

| # | Check | Result |
|---|---|---|
| 1 | Agent stack pinned | langchain 1.4.8, langchain-openai 1.7.3, langchain-anthropic 1.7.9, langchain-mcp-adapters 0.3.2, langgraph 1.2.19, langfuse 5.1.0 |
| 2 | `agent/llm.py` provider interface | OpenAI-compatible (OpenAI/OpenRouter/DeepSeek/Groq/Ollama via `LLM_BASE_URL`) + native Anthropic; `LLMNotConfigured` with example `.env` entries — never a simulated model |
| 3 | `agent/tools.py` | loads the 4 read-only MCP servers via langchain-mcp-adapters (stdio); write server not reachable from investigation code |
| 4 | `agent/baseline.py` | ReAct agent (langgraph prebuilt) + `BaselineReport` structured output with strict parsing (fences/trailing text/rejected categories) |
| 5 | Migration 0003 | `incidents.status` workflow (`open→investigating→diagnosed/failed/resolved`), `alert_labels` JSONB (fingerprint/occurrences), `error` column, fingerprint index |
| 6 | Webhook + dedupe + API | `POST /alerts` (Alertmanager v2 schema), fingerprint = alertname+namespace+derived-service with 10-min window, occurrences counter, resolved handling, `GET /incidents[/{id}]`, full audit trail |
| 7 | Webhook tests | 20/20 new tests (schema parsing incl. prompt-injection labels as data, report parsing, full lifecycle with stub runner, **honest LLM-failure path with real runner**) |
| 8 | **Live gate run 1** | injected `oom_checkout` → real PodRestarting alert → Alertmanager POST → incident created (~4 min) — but service mis-derived (`monitoring-kube-state-metrics`) and stale infra alerts leaked in (16 noise incidents) |
| 9 | Fixes from live findings | service derivation now pod→deployment→service (kube-state-metrics' own `service` label is ignored); webhook ignores protected namespaces (verified: non-boutique incidents = NONE after re-render); monitoring re-rendered to clear stale control-plane targets; noise rows purged |
| 10 | **Live gate run 2** | injected `oom_checkout` → incident created with `service=checkoutservice`, `occurrences` incrementing, status `failed` with the honest `LLMNotConfigured` message, zero protected-ns incidents; cleanup healthy |
| 11 | Full suite | see Tests table below |

## LLM configuration (live since 2026-11-04)

`.env` (git-ignored; key never committed) — Gemini via the **native** google provider:

```
LLM_PROVIDER=google                      # native client (thought signatures!)
LLM_API_KEY=AQ.…                         # AI Studio key
LLM_PRIMARY_MODEL=gemini-flash-lite-latest
LLM_CHEAP_MODEL=gemini-3.1-flash-lite
```

(OpenAI-compatible endpoints and Anthropic remain supported — see `agent/llm.py`.)

## Issues found & fixed during the Phase 4 loop

1. mcp/langchain pins: stayed on `mcp<2` (v2 breaking); langchain 1.x resolved cleanly.
2. Decorator-before-definition import bug in `baseline.py` (caught by import check).
3. `dict(Json(...))` typo and `str.join` misuse in dedupe (caught by tests).
4. Pod-hash guard assumed legacy 5-char hashes; modern ReplicaSet hashes are 10.
5. **Live-gate finding**: kube-state-metrics stamps `service=monitoring-kube-state-metrics` on every alert — pod label must win service derivation.
6. **Live-gate finding**: stale control-plane alerts (Docker-restart artifact) flooded the webhook → protected-namespace filter added + monitoring re-render; verified in gate run 2.
7. FastAPI `on_event` deprecated → lifespan.

## Tests

| Date | Suite | Result |
|---|---|---|
| 2026-11-03 | Phase 1 gate | 15 passed |
| 2026-11-03 | Phase 2 gate | 25 passed |
| 2026-11-04 | Phase 3 gate | 75 passed |
| 2026-11-04 | Phase 4 gate | **95 passed, 0 failed** (incl. 20 new Phase-4 tests) in 28m52s |

## Next task

Phase 5 — multi-agent orchestration: shared `IncidentState`, Triage →
Supervisor → specialist loop (metrics/logs/k8s) → Diagnoser, step and tool
budgets, evidence-ID grounding. The E1 comparison against the Phase-4
baseline becomes measurable.

## Phase 3 verification evidence (2026-11-04)

| # | Check | Result |
|---|---|---|
| 1 | SDKs pinned | `mcp==1.30.0` (v1 API), `kubernetes==37.0.1` |
| 2 | `common/safety.py` | namespace guard (protected/malformed rejected), redaction (Authorization value, key=value secrets, Bearer, JWT, AWS keys, conn strings), 4000-char cap, untrusted-data wrapper — 46 unit tests cover all helpers |
| 3 | 4 servers, 20 tools import & register cleanly | `k8s-read` (8), `prometheus` (4, incl. 16 PromQL templates), `loki` (2, incl. pattern-grouped `error_patterns`), `knowledge` (4, live PostgreSQL FTS + persistence) |
| 4 | **Live MCP protocol tests** (stdio `ClientSession` → server subprocess → tool call) | **15/15 passed** — every tool called against the live lab, incl. protected-namespace rejection, log untrusted-wrapping, ConfigMap value redaction, invalid template/LogQL rejection, incident save→search→get roundtrip |
| 5 | Reader RBAC (`deploy/rbac.yaml`) | dedicated `kubesentra-reader` ServiceAccount: get/list/watch only, **Secrets unreadable**; `.secrets/k8s-read.kubeconfig` generated by `scripts/gen_mcp_kubeconfigs.sh`; **negative test: delete-pod correctly DENIED (403)** |
| 6 | metrics-server v0.9.1 (+`--kubelet-insecure-tls` for kind) | `kubectl top pods` and `get_resource_usage` return live CPU/memory |
| 7 | Full suite | **75/75 passed** (46 unit + 15 MCP + 7 DB + 7 lab) in 3m14s |
| 8 | Reproducibility | `lab_up.sh` now installs metrics-server + RBAC + kubeconfig and waits on them |

## Issues found & fixed during the Phase 3 loop

1. **mcp 2.3.0 breaking change** — `FastMCP` renamed to `MCPServer`; too fresh vs the spec's code and the LangChain adapter ecosystem → pinned `mcp<2` (1.30.0); v2 migration noted as future work.
2. **`str.format` vs PromQL braces** — template rendering would have crashed on every selector query at runtime; caught by a unit test before integration → token-based `<placeholder>` substitution.
3. **Redaction gap** — `Authorization: Bearer <token>` matched the key:value rule, consuming only the scheme word and *leaving the token visible* → dedicated Authorization rule now masks the whole value.
4. **kubernetes 37.x kwarg validation** — `timeout_seconds` is a list-call query param only; read calls reject it (pydantic) → switched all calls to `_request_timeout`.
5. **psycopg NULL parameter typing** — `(%s IS NULL OR ...)` ambiguous → explicit `::text` cast.
6. **Lab overnight shutdown** — Docker Desktop must be started manually; kind containers auto-recover; 6 control-plane Prometheus targets go stale after daemon restart (kind static targets with changed container IPs) — cosmetic, not used by our templates; fixed by re-render (`helm upgrade monitoring`) or lab rebuild.

## Documented deviations from the spec

- `dry_run_action` (spec lists it under k8s-read) is deferred to Phase 7: a server-side dry-run of a *patch* requires the patch verb in RBAC, which belongs with the write server's credential, not the read-only one.
- Online Boutique v0.10.7 exports no HTTP metrics → `http_error_rate`/`p95_latency` templates are documented as returning empty until app metrics exist.
- `knowledge` semantic/hybrid retrieval (pgvector + RRF) arrives in Phase 6 with embeddings + runbook ingestion; full-text leg is live and verified now.

## Tests

| Date | Suite | Result |
|---|---|---|
| 2026-11-03 | Phase 1 gate | 15 passed |
| 2026-11-03 | Phase 2 gate | 25 passed |
| 2026-11-04 | Phase 3 gate | **75 passed, 0 failed** |

## Next task

**Phase 4 — single-agent baseline**: ReAct agent over the MCP tools
(langchain + langchain-mcp-adapters), FastAPI `POST /alerts` webhook with
deduplication, incident records in PostgreSQL, Langfuse tracing, and the
first end-to-end run: injected fault → alert → incident → investigation
summary.
