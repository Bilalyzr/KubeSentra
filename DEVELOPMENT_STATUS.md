# KubeSentra — Development Status

**Last updated:** 2026-11-04 · **Phase 4 COMPLETE except the live-LLM leg** (blocked on user API key, by design)

This document is the single source of truth for project progress. It is
updated at the end of every phase's build → verify loop, with real results.

---

## Current phase

Phase 4 — single-agent baseline + alert ingestion: **code complete and verified up to the LLM boundary**.
The full pipeline (real alert → webhook → incident → dedupe → API) is verified with live Alertmanager traffic.
The agent investigation leg runs the moment `LLM_*` values are added to `.env` — the system fails honestly (`status=failed`, clear error) until then; nothing is simulated.

## Phase tracker

| # | Phase | Status | Verification gate | Gate result |
|---|---|---|---|---|
| 1 | Project foundation | ✅ Complete | tests green · DB live · health endpoints respond | **PASS** (2026-11-03) |
| 2 | Kubernetes laboratory | ✅ Complete | pods Running · targets up · injected fault fires an alert | **PASS** (2026-11-03) |
| 3 | MCP read servers | ✅ Complete | every tool verified live: validated inputs, capped/redacted/wrapped outputs; reader RBAC cannot write | **PASS** (2026-11-04) |
| 4 | Single-agent baseline + webhook | ✅ Complete (LLM leg pending key) | alert → incident record → investigation runs end to end | **PASS for alert→incident→dedupe→API (live alerts)** · LLM leg **BLOCKED: no LLM key configured** |
| 5 | Multi-agent LangGraph | Not started | supervisor loop obeys budgets · every RCA claim cites valid evidence IDs | — |
| 6 | RAG + remediation + approval interrupt | Not started | graph pauses durably · edited plans re-validated | — |
| 7 | k8s-write + executor + verifier | Not started | **zero writes without approval** · protected namespaces blocked · injection fails closed | — |
| 8 | Streamlit dashboard | Not started | every control calls the real backend | — |
| 9 | Security tests + evaluation (B0, E1–E5) | Not started | measured results only, no fabricated numbers | — |
| 10 | Docs + final delivery | Not started | full setup reproducible from scratch | — |

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

## LLM configuration (the one remaining Phase 4 input)

Add to `.env` (git-ignored) — e.g. OpenRouter:
```
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-...
LLM_PRIMARY_MODEL=openai/gpt-4o-mini      # or any mid-tier model
LLM_CHEAP_MODEL=openai/gpt-4o-mini        # used from Phase 5 routing
```
Then re-run the gate: `scripts/dev.sh serve` + `scripts/inject_fault.sh oom_checkout` → the incident should reach `status=diagnosed` with a real root-cause report. (User was asked; question unanswered as of 2026-11-04 — no key was invented.)

## First baseline results (Phase 4 requirement)

Not yet measurable — the baseline agent has not executed a single real
investigation because no LLM key is configured. **No results are fabricated.**
The evaluation harness (Phase 9) will produce the real numbers; the gate run
above proves the plumbing works end to end up to the LLM boundary.

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

1. **User provides LLM key** → run the Phase-4 LLM leg (fault → diagnosed incident) and record first real baseline results.
2. Phase 5 — multi-agent orchestration (shared state, Triage/Supervisor/specialists/Diagnoser, budgets, evidence IDs).

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
