# KubeSentra — Viva / Interview Preparation

*Answers keyed to THIS system's measured results. Claim only what the
evidence log supports.*

**Q: Why multi-agent instead of one agent with all the tools?**
Specialists get small, focused toolsets and prompts; a Supervisor keeps the
investigation hypothesis-driven with hard code rules (budget 15 steps,
confidence ≥0.8 + two evidence sources to exit). Measured (E1, n=1):
multi-agent 78 s with evidence-cited output vs single ReAct 129 s with no
grounding. Honest caveat: n is small; the harness exists to scale it.

**Q: How do you stop it from doing something dangerous?**
Nine layers (docs/security.md): untrusted-data wrapping → read-only
investigation (write server not even loadable) → 5-action allowlist →
code-level parameter policy (namespace, 1–5 replicas, ≤2× live limits,
absolute caps) → server-side dry-run → durable human interrupt
(token + genuinely-paused check; edits re-validated, invalid edits
re-interrupt) → fail-closed executor (state AND DB approval row AND fresh
preflight) → RBAC blast radius (executor Role exists only in `boutique`) →
audit + a testable DB invariant.

**Q: What about prompt injection through logs?**
Logs are wrapped as data with delimiters. But the real defence is
architectural: tool output can never directly cause a write — writes come
only from a structured plan that passes code validation and a human gate.
Demonstrated live (E5): an attacker pod flooded the agent's Loki stream;
0 unauthorized writes across the whole campaign (DB invariant query).

**Q: How do you know your accuracy numbers are real?**
Ground-truth-labelled scenarios; results stored as JSON per run; an LLM
judge with a strict rubric (with a labelled fallback); errors recorded as
errors. B0 baseline provides the comparison point. Quota-bounded sample —
stated, never extrapolated.

**Q: How does memory help, and what if a past diagnosis was wrong?**
Past incidents are embedded and retrieved at triage as *hints to verify* —
never answers; every diagnosis must cite fresh evidence IDs. (E2 switch
implemented to measure exactly this at scale.)

**Q: How did you handle huge logs?**
Pattern-based compression before the LLM (numbers/IDs/IPs/quoted strings →
placeholders, top-N patterns with one example each), enforced at the Loki
tool layer; raw output goes to `evidence_raw`, only summaries enter context.

**Q: Hardest failures?**
Windows event-loop trilemma (psycopg-async vs MCP stdio subprocesses) →
sync saver + thread-offloading adapter; LangGraph's checkpointed resume
values (raising on an invalid edit would brick the thread) → re-interrupt
pattern; alert flapping closing an active incident; approval-record
ordering (the executor refused correctly — the safety property held);
one fault fanning out into 12 fingerprint incidents (top future work).

**Q: What would change for production?**
Per-user auth + short-lived tokens; in-cluster Helm deployment; multi-
cluster; PagerDuty/Slack approvals; continuous evaluation on real incident
history; cross-alert-name incident grouping.

**Q: Demo flow (5 minutes)?**
Follow [demo.md](demo.md): dashboard overview → inject OOM fault → watch
triage/specialists/diagnosis live → approve (or edit to rollout_undo) →
executor's real rollout_undo → verifier RESOLVED → postmortem with
evidence IDs → incident appears in memory for the next triage.
