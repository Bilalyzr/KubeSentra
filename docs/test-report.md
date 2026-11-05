# KubeSentra — Test Report

*Every number below is a real pytest/AppTest/live-gate result. Full history:
[DEVELOPMENT_STATUS.md](../DEVELOPMENT_STATUS.md).*

## Totals (final, 2026-11-05)

| Layer | Tests | Result |
|---|---|---|
| Unit (config, schemas, safety, PromQL, log patterns, guardrails, write-server validation, dashboard client, scenarios, alert parsing, report parsing) | 71 | all pass |
| Integration — DB (migrations, pgvector, incident roundtrips) | 7+ | all pass |
| Integration — live lab (nodes/targets/rules/Loki/chaos) | 7 | all pass |
| Integration — MCP protocol (every tool called over real stdio sessions) | 15 | all pass |
| Integration — webhook/dedupe lifecycle | 4 | all pass |
| Integration — graph flows with fake LLMs (diagnosis grounding, escalation budget, approval pause/edit paths, execution flow) | 10 | all pass |
| Integration — RAG quality (semantic + exact-keyword legs, episodic roundtrip) | 4 | all pass |
| Integration — dashboard API endpoints | 6 | all pass |
| Security battery (7 suites) | 47 | all pass |
| **pytest total** | **204** | **204 passed** |
| Streamlit AppTest gate (all 9 pages vs live API + real decision click) | 14 | 14 pass |
| Live phase gates (Phases 2–9) | 9 gates | all pass |

## What the security battery proved

- Prompt injection through logs, events, alert labels and write-server
  arguments: contained as data; **cannot become a write action**
- Approval bypass: 401 (no/wrong token), 409 (not genuinely paused),
  refusal on forged state, and the **DB invariant — zero `write:%` audit
  events without a prior approvals row**
- Protected namespaces: rejected at application validation AND at live
  Kubernetes RBAC (`kubectl auth can-i` matrix, both identities)
- Invalid parameters rejected at BOTH the validator and the write server;
  duplicates deduplicated (5-alert burst → 1 incident); loop budgets are
  hard code, not prompts; investigation tool surface cannot reach the
  write server

## Bugs the test loops caught and fixed (selection, all documented)

1. kube-state-metrics' own `service` label overrode incident service
   derivation (live)
2. Alert flapping closed an awaiting-approval incident (live)
3. Approval-record ordering left the executor without its record — it
   refused correctly (fail-closed proved live), wiring then fixed
4. LangGraph checkpoints resume values → raising on an invalid edit would
   brick a thread; approval re-interrupts instead
5. Windows event-loop vs psycopg-async vs MCP stdio subprocesses → sync
   PostgresSaver behind a thread-offloading adapter
6. Gemini-3 thought signatures break OpenAI-compat tool loops → native
   provider branch
7. torch inside stdio MCP servers deadlocked → protocol tests run
   embedding-free
8. Absolute resource caps + name-length caps were missing (found by the
   security battery itself)
9. Python's bare `bash` resolved to a foreign shell during evaluation →
   pinned Git-bash path

## Known open issues

- One fault can fan out into several alert-name fingerprints → multiple
  incidents (top future improvement: cross-alert-name grouping)
- Gemini free-tier 503 windows occasionally fail an investigation despite
  retries (recorded honestly as `failed`; retryable)
- E2/E3/E4 evaluation configurations are implemented but not yet run
  (single free-tier quota pool)
