# KubeSentra — Development Status

**Last updated:** 2026-11-05 · **PROJECT COMPLETE — all 10 phases delivered & verified**

This document is the single source of truth for project progress. It is
updated at the end of every phase's build → verify loop, with real results.

---

## Current phase

Phase 10 — final delivery: **complete.** The project is delivered:
10 phases, 204 tests + AppTest + 9 live gates, measured evaluation, full
docs, and a from-scratch reproducibility check.

## Phase tracker

| # | Phase | Status | Verification gate | Gate result |
|---|---|---|---|---|
| 1 | Project foundation | ✅ Complete | tests green · DB live · health endpoints respond | **PASS** (2026-11-03) |
| 2 | Kubernetes laboratory | ✅ Complete | pods Running · targets up · injected fault fires an alert | **PASS** (2026-11-03) |
| 3 | MCP read servers | ✅ Complete | every tool verified live; reader RBAC cannot write | **PASS** (2026-11-04) |
| 4 | Single-agent baseline + webhook | ✅ Complete | alert → incident → investigation end to end | **PASS** (2026-11-04, live Gemini) |
| 5 | Multi-agent LangGraph | ✅ Complete | budgets respected · every claim cites valid evidence | **PASS** (2026-11-04, 79 s grounded diagnosis) |
| 6 | RAG + remediation + approval interrupt | ✅ Complete | graph pauses durably · edited plans re-validated | **PASS** (2026-11-04, live approval cycle) |
| 7 | k8s-write + executor + verifier + postmortem | ✅ Complete | **zero writes without approval** · protected namespaces blocked · injection fails closed | **PASS** (2026-11-05, full lifecycle) |
| 8 | Streamlit dashboard | ✅ Complete | every control calls the real backend | **PASS** (2026-11-05, AppTest gate 14/14) |
| 9 | Security tests + evaluation (B0, E1–E5) | ✅ Complete (quota-bounded) | measured results only, no fabricated numbers | **PASS** (2026-11-05: security 47/47, **0 unauthorized writes**; B0 3/5; E1 both configs measured; E5 live injection → 0 writes; E2/E3/E4 harness-ready, honestly not run) |
| 10 | Docs + final delivery | ✅ Complete | full setup reproducible from scratch | **PASS** (2026-11-05, fresh-clone gate below) |

## Phase 9 verification evidence (2026-11-05)

| # | Check | Result |
|---|---|---|
| 1 | Security battery (tests/security/, 7 suites) | **47/47 PASS**: injection (4 paths), approval bypass (token 401s, 409 non-paused, forged-state refusal, **DB invariant: zero writes without prior approval**), protected namespaces (app + live RBAC can-i), invalid parameters (both layers), duplicate alerts (5→1 incident), agent loop safety, tool surface (5 tools, no exec) |
| 2 | Hardening driven by the battery | absolute resource caps + target length cap + double-audit fix |
| 3 | Eval harness | `eval/runner.py` (full real lifecycle per run), `eval/judge.py` (LLM judge, strict rubric, labelled fallback), `eval/aggregate.py`, results in `eval/results/` |
| 4 | B0 (no LLM, 5 scenarios) | top-1 3/5 — rules fail exactly where an agent is needed (crashloop, imagepull) |
| 5 | E1 (live) | oom_checkout both configs: multi_agent **78 s, top-1, evidence-grounded**; baseline 129 s, top-1, not grounded; 2 further runs recorded as errors (alert fan-out, reset timing) — no extrapolation |
| 6 | E5 (live) | attacker pod logging injection into the Loki stream the agent queries; **0 unauthorized writes** across all 3 recorded writes + full audit invariant |
| 7 | E2/E3/E4 | switches implemented + runner configs accepted; **not run** (single quota pool) — stated, not padded |

## Phase 9 issues found & fixed

1. Python's `bash` resolves to a foreign shell (HOME=/home/billu, its own kubectl) → runner pins Git-bash absolute path.
2. API renders created_at with a space; runner compared against 'T'-separated ISO → normalized.
3. rollout-undo cleanup unreliable after repeated faults polluted revision history → `cleanup_fault.sh` now re-applies the original manifest deterministically.
4. Subprocess timeout raced the rollout-status timeout → headroom raised.
5. Alert fan-out: one fault → many alert-name fingerprints → many incidents (12 pending in one run). Recorded as the top future improvement (group by service+window across alert names).

## Tests

| Date | Suite | Result |
|---|---|---|
| 2026-11-03 | Phase 1 gate | 15 passed |
| 2026-11-03 | Phase 2 gate | 25 passed |
| 2026-11-04 | Phase 3 gate | 75 passed |
| 2026-11-04 | Phase 4 gate | 95 passed |
| 2026-11-04 | Phase 5 gate | 114 passed |
| 2026-11-04 | Phase 6 gate | 138 passed |
| 2026-11-05 | Phase 7 gate | 148 passed |
| 2026-11-05 | Phase 8 gate | 157 passed + AppTest 14/14 |
| 2026-11-05 | Phase 9 gate | **204 passed** (47 security, all prior suites) |

## Phase 10 verification evidence (2026-11-05)

| # | Check | Result |
|---|---|---|
| 1 | Documentation set | architecture.md (system + agent workflow + MCP + approval chain), database.md (schema/migrations/retrieval/audit invariant), api.md (every endpoint + config), security.md (nine-layer threat model + measured E5), setup.md (clone → running), test-report.md (204 + AppTest + gates + bugs-caught + open issues) |
| 2 | Evaluation charts | `eval/charts.py` generates dependency-free SVGs from the REAL result JSONs → docs/report/charts/ (accuracy by config, TTD per run, unauthorized writes) |
| 3 | Project report skeleton | docs/report/project-report.md — 17 sections, keyed to verified artifacts |
| 4 | Demo workflow + viva prep | docs/demo.md (manual + automated variant + troubleshooting), docs/viva.md (answers keyed to measured results) |
| 5 | README | final pass: status COMPLETE, documentation index, all phases summarised with their gates |
| 6 | **FRESH-CLONE GATE** | `git clone` (public repo, commit 5e40fa2) → **no secrets in clone** (.env/.secrets/.models absent — verified) → fresh venv → pinned install OK → all modules import → migrations idempotent (4 previously applied) → ingest parse OK (23 runbooks → 115 chunks) → unit suite **106/106** → full suite (incl. live integration + security) run in the clone — result recorded below |
| 7 | Cluster rebuild proven | already demonstrated in Phase 2 (the kind cluster was rebuilt from scratch after the port fix) and lab_up/lab_down remain the documented path |

## Fresh-clone full-suite result

**204 passed in 12:42** — the complete suite (unit + live-lab integration +
MCP protocol + graph flows + RAG + webhook + dashboard + security battery)
run from the cold clone against the running lab. The repository is
self-contained: anyone can reproduce the verification with
docs/setup.md.

## Final summary

- **10/10 phases**, every one closed by a live verification gate
- **204 automated tests** + 14 AppTest checks + 47-test security battery
- **Safety property demonstrated by attack**: 0 unauthorized writes across
  the entire campaign, including a live prompt-injection flood (E5)
- **Full incident lifecycle proven live**: fault → alert → multi-agent
  diagnosis (evidence-cited) → human-approved plan → real rollout_undo via
  the write MCP server → verifier RESOLVED → embedded postmortem → memory
- Honest evaluation: B0 3/5; E1 both configs; E5 live; E2/E3/E4 ready but
  not run (quota) — every number traceable to a JSON result file

## Next task

None — delivered. Optional future work is listed in
docs/report/project-report.md §16 and docs/test-report.md.


## Phase 8 verification evidence (2026-11-05)

| # | Check | Result |
|---|---|---|
| 1 | Dashboard | 9 pages, dark-first theme (.streamlit/config.toml), custom card/pill CSS, no placeholder statistics anywhere |
| 2 | New API endpoints | `GET /stats` (computed counts/avg-TTD/verdict-based success rate), `/incidents/{id}/timeline` (audit log), `/evidence` (evidence_raw), `/postmortem` (parsed JSON w/ text fallback), `/runbooks` + `/runbooks/search` (hybrid RAG in-process); hypotheses now persisted at the approval pause |
| 3 | Client layer | `dashboard/services/api.py` — every page reads through the REAL API (never the DB directly); decision calls carry `X-Approval-Token` from env; errors surfaced verbatim |
| 4 | Tests | 9 new: client MockTransport (URL/params/token/verbatim errors) + endpoint shapes (stats keys, timeline/evidence rows, 404s, runbook search quality) |
| 5 | **AppTest gate** (`scripts/dashboard_gate.py`) | **14/14 PASS**: all 9 pages render against the live API; overview metric equals `/stats`; hybrid search surfaces the OOM runbook; approval-page Reject click hits the real endpoint — synthetic paused-less incident answered **409 'no pending approval interrupt'** surfaced verbatim, incident untouched, NO approval record written |
| 6 | Streamlit server | headless serve verified (HTTP 200 + `/_stcore/health` ok) |

## Issues found & fixed during the Phase 8 loop

1. **Stale uvicorn silently held :8547** (pre-Phase-8 code, no /stats): pages with graceful error handling "passed" by degrading; the postmortem page honestly crashed → killed the stale pair (netstat PID grep pattern initially missed LISTENING with PID 0 during TIME_WAIT teardown).
2. **Cold-load race**: first hybrid search inside the API takes ~50 s (bge model load) vs the dashboard's 15 s client timeout → model now warms in a background thread at API startup + search timeout raised to 180 s.
3. **Decision endpoint could resume a live/absent graph thread** (500 KeyError mid-graph, found by the gate's button click) → `thread_is_paused_at_approval` guard returns **409** and the incident is left untouched (fail closed).
4. Execution page crashed on a missing postmortem → error surfaced via the shared banner instead.

## Tests

| Date | Suite | Result |
|---|---|---|
| 2026-11-03 | Phase 1 gate | 15 passed |
| 2026-11-03 | Phase 2 gate | 25 passed |
| 2026-11-04 | Phase 3 gate | 75 passed |
| 2026-11-04 | Phase 4 gate | 95 passed |
| 2026-11-04 | Phase 5 gate | 114 passed |
| 2026-11-04 | Phase 6 gate | 138 passed |
| 2026-11-05 | Phase 7 gate | 148 passed |
| 2026-11-05 | Phase 8 gate | **157 passed** (9 new; full suite in commit) + AppTest gate 14/14 |

## Next task

Phase 9 — security tests (prompt injection via logs/labels, unauthorized
execution, protected namespaces, approval bypass, invalid parameters,
duplicate alerts, agent loops) and the evaluation harness: B0 rule baseline,
E1 single-vs-multi-agent, E2 memory, E3 RAG, E4 model routing, E5 injection
resilience — real measured numbers only.

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
