# KubeSentra — Development Status

**Last updated:** 2026-11-05 · **Phase 7 COMPLETE** (full incident lifecycle closed live)

This document is the single source of truth for project progress. It is
updated at the end of every phase's build → verify loop, with real results.

---

## Current phase

Phase 7 — execution & verification: **complete.** The full incident lifecycle
(alert → investigation → diagnosis → approved remediation → execution →
verification → postmortem → memory) has run live, end to end.
Next: Phase 8 (Streamlit dashboard).

## Phase tracker

| # | Phase | Status | Verification gate | Gate result |
|---|---|---|---|---|
| 1 | Project foundation | ✅ Complete | tests green · DB live · health endpoints respond | **PASS** (2026-11-03) |
| 2 | Kubernetes laboratory | ✅ Complete | pods Running · targets up · injected fault fires an alert | **PASS** (2026-11-03) |
| 3 | MCP read servers | ✅ Complete | every tool verified live; reader RBAC cannot write | **PASS** (2026-11-04) |
| 4 | Single-agent baseline + webhook | ✅ Complete | alert → incident → investigation end to end | **PASS** (2026-11-04, live Gemini) |
| 5 | Multi-agent LangGraph | ✅ Complete | budgets respected · every claim cites valid evidence | **PASS** (2026-11-04, 79 s grounded diagnosis) |
| 6 | RAG + remediation + approval interrupt | ✅ Complete | graph pauses durably · edited plans re-validated | **PASS** (2026-11-04, live approval cycle) |
| 7 | k8s-write + executor + verifier + postmortem | ✅ Complete | **zero writes without approval** · protected namespaces blocked · injection fails closed | **PASS** (2026-11-05, full lifecycle below) |
| 8 | Streamlit dashboard | Not started | every control calls the real backend | — |
| 9 | Security tests + evaluation (B0, E1–E5) | Not started | measured results only, no fabricated numbers | — |
| 10 | Docs + final delivery | Not started | full setup reproducible from scratch | — |

## Phase 7 verification evidence (2026-11-05)

| # | Check | Result |
|---|---|---|
| 1 | `k8s-write` MCP server | exactly **five** allowlisted tools (tested); every call re-validated through the SAME guardrails as planner/approval BEFORE any cluster interaction (protected/wrong namespace, bad params all rejected pre-client); each call audited server-side |
| 2 | Executor RBAC | executor Role in `boutique` only: `can-i list replicasets` in boutique **yes**, kube-system **no** (live-checked); rollout_undo required adding read-only replicasets (revision history) — minimal, documented widening |
| 3 | Executor node | fail-closed: requires approval state AND a DB approvals row; per action: re-validate → fresh server-side dry-run → ONE MCP stdio call to the write server; stops the plan on first failure; duplicate-execution guard; refusal audited |
| 4 | Verifier | deterministic: pods-ready poll (≤240 s), original-alert-cleared, restart pre/post comparison → RESOLVED / PARTIALLY_RESOLVED / NOT_RESOLVED / VERIFICATION_FAILED; never trusts a successful kubectl exit |
| 5 | Postmortem writer | structured report (timeline, evidence refs, remediation results, approval, verification, LLM lessons w/ fallback) persisted to the incident + embedding update |
| 6 | Graph | approval →(approved/edited)→ execute → verify → postmortem → END; rejected/escalated → postmortem → END |
| 7 | Tests | 13 Phase-7 tests: write-server validation (8, incl. "exactly five tools"), executor fail-closed refusal, full approved path with stubbed writes (execute→verify→postmortem, verdict RESOLVED), rejected path skips execution |
| 8 | **LIVE GATE (full cycle)** | fault → pause (diagnosis) → **invalid edit → 400** (policy reason) → **valid edited `rollout_undo` → 200** → executor ran the REAL rollout_undo via the write MCP server → verifier: pods ready in 15 s, alert cleared → **RESOLVED** → postmortem written with approval + lessons. Cluster truth: pod 1/1 Running, limit restored **128Mi**. Audit chain: `write:rollout_undo` → `action_executed` → `verification RESOLVED` → `postmortem_written` |

## Issues found & fixed during the Phase 7 loop

1. **Approval-record ordering bug (found live, proved the fail-closed property)**: the approvals row was written AFTER the resumed graph ran, so the executor's DB cross-check found nothing mid-run and correctly refused to execute; the verifier then honestly reported NOT_RESOLVED. Fix: record the approval BEFORE resuming; revoke it if the edit turns out invalid (re-interrupt path). A second live cycle then executed for real.
2. **Alert flapping can clobber active workflows**: after ~15 min of CrashLoop backoff the restart RATE fell below the alert threshold → Alertmanager "resolved" closed an `awaiting_approval` incident. Fix: resolved notifications only close incidents in `open/diagnosed/escalated/failed` - never `investigating/awaiting_approval` (the Verifier owns the final verdict).
3. Executor needed read-only `replicasets` (revision history) for rollout_undo - added to the boutique-scoped Role after live RBAC verification.
4. Refusal-audit FK crash on synthetic incident IDs → best-effort audit.
5. Phase-6 approval tests now continue into the Phase-7 tail → stubbed at the graph-binding site (`agent.graph.*`).

## Tests

| Date | Suite | Result |
|---|---|---|
| 2026-11-03 | Phase 1 gate | 15 passed |
| 2026-11-03 | Phase 2 gate | 25 passed |
| 2026-11-04 | Phase 3 gate | 75 passed |
| 2026-11-04 | Phase 4 gate | 95 passed |
| 2026-11-04 | Phase 5 gate | 114 passed |
| 2026-11-04 | Phase 6 gate | 138 passed |
| 2026-11-05 | Phase 7 gate | **151 passed** (13 new; full-suite count in commit) |

## Next task

Phase 8 — Streamlit dashboard: incident list, investigation timeline,
evidence, hypotheses with citations, approval page (real decisions through
the token-authenticated API), execution/verification results, history,
runbook browser, observability. Every control must call the real backend.
