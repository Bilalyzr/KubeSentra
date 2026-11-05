# KubeSentra — Project Report (skeleton with measured content)

*Structure per the project specification (17 sections). Sections marked
▶ already have verified content; the student fills personal-institution
details and prose where indicated. Never replace a measured number with an
estimate.*

1. **Introduction** — problem (§1.1 of the implementation document:
   on-call engineers spend their time gathering evidence; incident
   knowledge evaporates), what KubeSentra does, why it matters for AIOps.
2. **Problem statement** — alerts are noisy and repeated; investigation is
   manual; LLM agents are powerful but unsafe to give cluster write access.
3. **Objectives** — evidence-cited diagnosis; strict allowlist + human
   approval; incident memory; measurable evaluation; zero unauthorized
   writes (hard requirement).
4. **Existing system** — rule-based alerting (B0 baseline: top-1 3/5 on the
   5-scenario catalogue — fails crashloop & imagepull where reasoning is
   needed); generic AI copilots without safety gates.
5. **Proposed system** — multi-agent investigation + layered guardrails;
   contrast table vs existing.
6. **Literature review** — LLM agents for ops (LangGraph/orchestration),
   RAG for runbooks, human-in-the-loop ML, prompt-injection defences.
7. **Requirements** — functional (from the 9-phase plan) and non-functional
   (TTD < 5 min, unauthorized writes = 0, 16 GB laptop, free-tier LLM).
8. **System architecture** — use [docs/architecture.md](../architecture.md)
   (diagram, component map, state machine).
9. **Module descriptions** — one subsection per module mirroring the repo
   layout (webhook/dedupe; triage/supervisor/specialists/diagnoser/
   remediation-planner/approval/executor/verifier/postmortem; 5 MCP servers;
   RAG/memory; dashboard; evaluation).
10. **Database design** — [docs/database.md](../database.md) (4 core tables
    + approvals + checkpoints; hybrid retrieval with RRF).
11. **Implementation** — phase-by-phase with the loop-engineering method and
    the live gates (DEVELOPMENT_STATUS.md is the evidence log); notable
    implementations: grounding filter, interrupt/re-interrupt pattern,
    sync-saver adapter, dry-run pipeline, episodic memory.
12. **Testing** — [docs/test-report.md](../test-report.md): 204 pytest +
    14 AppTest + 9 live gates; security battery findings.
13. **Evaluation** — [phase9-results.md](phase9-results.md) +
    [charts/](charts/): B0 3/5; E1 multi-agent 78 s grounded vs baseline
    129 s ungrounded (n=1, stated); E5 live injection → 0 unauthorized
    writes; E2/E3/E4 implemented-not-run (quota). Include the failure
    analysis — examiners value it.
14. **Results** — reproduce the summary table from `eval/results/summary.md`
    (do not extrapolate); targets-vs-measured table from phase9-results.md.
15. **Limitations** — quota-bounded n; shared approval token; long-lived SA
    tokens; alert fan-out; single cluster.
16. **Future enhancements** — cross-alert-name incident grouping; E2–E4
    full-grid runs; per-user auth; in-cluster Helm deployment; PagerDuty/
    Slack approval UX; continuous evaluation on real history.
17. **Conclusion** — a full lifecycle (alert → diagnosis → approved
    execution → verified resolution → remembered postmortem) built and
    verified phase-by-phase, with the safety property demonstrated by
    attack: zero unauthorized writes.
