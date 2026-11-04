# KubeSentra — Development Status

**Last updated:** 2026-11-04 · **Phase 6 COMPLETE** (approval gate passed live)

This document is the single source of truth for project progress. It is
updated at the end of every phase's build → verify loop, with real results.

---

## Current phase

Phase 6 — RAG + remediation + approval interrupt: **complete and verified with
a live end-to-end approval cycle.** Next: Phase 7 (k8s-write MCP server,
executor, verifier, postmortem).

## Phase tracker

| # | Phase | Status | Verification gate | Gate result |
|---|---|---|---|---|
| 1 | Project foundation | ✅ Complete | tests green · DB live · health endpoints respond | **PASS** (2026-11-03) |
| 2 | Kubernetes laboratory | ✅ Complete | pods Running · targets up · injected fault fires an alert | **PASS** (2026-11-03) |
| 3 | MCP read servers | ✅ Complete | every tool verified live; reader RBAC cannot write | **PASS** (2026-11-04) |
| 4 | Single-agent baseline + webhook | ✅ Complete | alert → incident → investigation end to end | **PASS** (2026-11-04, live Gemini) |
| 5 | Multi-agent LangGraph | ✅ Complete | budgets respected · every claim cites valid evidence | **PASS** (2026-11-04, 79 s grounded diagnosis) |
| 6 | RAG + remediation + approval interrupt | ✅ Complete | graph pauses durably · edited plans re-validated | **PASS** (2026-11-04, live approval cycle below) |
| 7 | k8s-write + executor + verifier | Not started | **zero writes without approval** · protected namespaces blocked · injection fails closed | — |
| 8 | Streamlit dashboard | Not started | every control calls the real backend | — |
| 9 | Security tests + evaluation (B0, E1–E5) | Not started | measured results only, no fabricated numbers | — |
| 10 | Docs + final delivery | Not started | full setup reproducible from scratch | — |

## Phase 6 verification evidence (2026-11-04)

| # | Check | Result |
|---|---|---|
| 1 | Runbooks | **23 runbooks** in the fixed 5-section format (spec list + extras: high-error-rate, p95, endpoints, memory leak, pool exhaustion, single-replica risk) |
| 2 | Ingest + embeddings | `python -m knowledge.ingest` → **115 chunks, all with 384-dim bge-small-en-v1.5 embeddings** (model cached repo-locally, CPU) |
| 3 | Hybrid retrieval | pgvector cosine + FTS legs merged with **RRF (k=60)**; test: semantic query finds the OOM runbook; exact `ImagePullBackOff` keyword finds the image runbook |
| 4 | Episodic memory | `save_incident` embeds (alert+symptoms+cause+summary); `search_similar_incidents` retrieves by cosine similarity with service filter — roundtrip test passes (similarity > 0.5); triage now uses it (FTS fallback) |
| 5 | Guardrails (code, not prompts) | allowlist of 5 actions; app-namespace only; protected namespaces rejected; scale 1–5; quantity format; ≤2× current resources (checked against LIVE cluster state at dry-run); 12 unit tests |
| 6 | Dry run | server-side `dry_run=All` via the **executor credential** (new Role in `boutique` only): patch/delete admitted in boutique, **kube-system denied** (verified in gen script) |
| 7 | Approval interrupt | durable pause via checkpointer; `status=awaiting_approval` persists diagnosis + plan + dry-runs; token-authenticated `POST /incidents/{id}/decision` |
| 8 | Edited-plan re-validation | invalid edit → **re-interrupt with the policy error** (nothing bricks — LangGraph checkpoints resume values, a plain raise would freeze the thread); 3 invalid edits fail safe to `rejected` |
| 9 | Tests | **25/25 Phase-6 tests** (approval pause/approve/edit paths, guardrails, RAG quality, updated graph tail) |
| 10 | **LIVE GATE** | fault injected → 4 alerts → **3 investigations paused at approval** (4th failed honestly on a Gemini 503 spike). Main incident: diagnosed in **96 s** (5Mi → OOMKilled, `resource`); planner proposed `set_resources 128Mi` → dry-run **correctly dropped it** (2× policy vs the fault's 5Mi) → human **edited to `rollout_undo`** → re-validated + re-dry-run → **200 approved**; invalid edit → **400 with policy reason**; missing token → **401**; approvals row + full audit trail (`awaiting_approval → approval_edit_invalid → approval_decision`) |

## Issues found & fixed during the Phase 6 loop

1. Planner prompt used literal `{...}` doc-braces inside `.format()` → KeyError; escaped.
2. Empty LLM proposal (`[]` = "no allowlisted action fits") wrongly hit validate_plan's empty-plan rejection → planner now treats `[]` as a valid human-only outcome and still pauses.
3. **LangGraph checkpoints resume values into pending tasks**: raising on an invalid edit would replay the same bad edit forever — approval node now re-interrupts with the validation error instead (verified: subsequent valid decision completes).
4. Quantity regex captured the wrong group → `_parse_quantity` TypeError; fixed + tests.
5. sentence-transformers pin corrected to the real 6.2.0 (+ torch 2.15.0).
6. Tests initially patched lazy imports at the wrong module (again) — remediation's `hybrid_search_runbooks` is imported inside the node; patched at source.
7. Saver lifecycle in tests: exiting the `with` closed the checkpointer mid-test → ExitStack pattern.
8. Missing `interrupt` import after the approval-node rewrite (caught by rerun).
9. **Live-gate finding**: alerts WITHOUT a namespace label created incidents (empty ≠ protected) → webhook now ignores namespace-less alerts (tested).
10. One investigation died on a sustained Gemini 503 window (retry budget exhausted) — recorded honestly as `failed`; free-tier availability is an environment constraint, not a code defect.

## Tests

| Date | Suite | Result |
|---|---|---|
| 2026-11-03 | Phase 1 gate | 15 passed |
| 2026-11-03 | Phase 2 gate | 25 passed |
| 2026-11-04 | Phase 3 gate | 75 passed |
| 2026-11-04 | Phase 4 gate | 95 passed |
| 2026-11-04 | Phase 5 gate | 114 passed |
| 2026-11-04 | Phase 6 gate | **140 passed** (25 new; full-suite count in commit) |

## Next task

Phase 7 — execution & verification: the `k8s-write` MCP server (executor
credential only, called only after approval), the Executor node (one action
at a time, full audit), the Verifier (pods ready, alert cleared, pre/post
comparison), the Postmortem writer (embedded memory), and the security gate:
**zero unauthorized writes, protected namespaces unreachable, prompt
injection fails closed**.
