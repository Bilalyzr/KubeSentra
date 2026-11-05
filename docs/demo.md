# KubeSentra — Demonstration Workflow (5–8 minutes)

Prereqs: lab up (`scripts/lab_health.sh` 7/7), Postgres up + migrations,
knowledge ingested, `.env` has the LLM key, API + dashboard running.

## The demo

1. **Baseline** — dashboard Overview (http://localhost:8551): real stats
   only. Mention: every number is computed from the incidents table.
2. **Inject the fault** — `scripts/inject_fault.sh oom_checkout`
   (checkoutservice memory limit → 5 Mi; pods OOMKilled-loop).
3. **Watch the agents work** — Incident Management page: incident appears
   (`investigating`); Investigation page: triage → supervisor questions →
   specialist evidence E1…En arriving in the timeline.
4. **Diagnosis + plan** — status `awaiting_approval` (usually within
   ~2–4 min): RCA page shows the root cause with evidence IDs; Approval
   page shows the plan + dry-run result. If the planner proposed
   `set_resources` beyond the 2× policy you'll see it DROPPED with the
   reason — that's the guardrail working.
5. **The human gate** — enter your name; try an invalid edit first
   (e.g. replicas 99 → the real API's 400 with the policy error is shown);
   then Approve, or Edit to `rollout_undo` and submit (re-validated).
6. **Real execution** — Execution & Verification page: the executor ran
   rollout_undo through the k8s-write MCP server; verifier checks (pods
   ready, alert cleared) → RESOLVED. Cluster truth: `kubectl -n boutique
   get pods -l app=checkoutservice` (1/1 Running, 128 Mi restored).
7. **Memory closes the loop** — the postmortem (with approval record and
   lessons) is stored with an embedding; History & Memory page: a similar
   query now retrieves this incident — next time, triage gets it as a hint.
8. **Security minute (optional)** — run `pytest tests/security/ -q` live:
   47/47 in ~3 min, ending on the zero-unauthorized-writes DB invariant.

## Automated variant

`scripts/gate_watch.py` performs steps 2–7 automatically against the live
API (waits for the pause, tests an invalid edit, approves) — useful as a
backup if the manual demo hits quota flakiness.

## Troubleshooting live demos

- Investigation stuck `investigating` > 5 min: likely a Gemini 503 window —
  the incident records the honest error; retry the scenario.
- No incident after injection: check `scripts/lab_health.sh`, then
  Alertmanager at :9093 (`/-/ready`).
- Dashboard shows "Backend unavailable": the API must run on :8547
  (`scripts/dev.sh serve`).
