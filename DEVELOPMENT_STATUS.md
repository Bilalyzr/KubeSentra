# KubeSentra — Development Status

**Last updated:** 2026-11-03 · **Phase 2 COMPLETE** (verification gate passed)

This document is the single source of truth for project progress. It is
updated at the end of every phase's build → verify loop, with real results.

---

## Current phase

Phase 2 — Kubernetes laboratory: **complete and verified**. Next: Phase 3 (MCP read servers).

## Phase tracker

| # | Phase | Status | Verification gate | Gate result |
|---|---|---|---|---|
| 1 | Project foundation | ✅ Complete | tests green · DB live · health endpoints respond | **PASS** (2026-11-03) |
| 2 | Kubernetes laboratory | ✅ Complete | kind/helm installed · pods Running · Prometheus targets up · injected fault fires an alert | **PASS** (2026-11-03, evidence below) |
| 3 | MCP read servers | Not started | every tool returns validated, capped, redacted output against the live cluster | — |
| 4 | Single-agent baseline + webhook | Not started | alert → incident → investigation runs end to end | — |
| 5 | Multi-agent LangGraph | Not started | supervisor loop obeys budgets · every RCA claim cites valid evidence IDs | — |
| 6 | RAG + remediation + approval interrupt | Not started | graph pauses durably · edited plans re-validated | — |
| 7 | k8s-write + executor + verifier | Not started | **zero writes without approval** · protected namespaces blocked · injection fails closed | — |
| 8 | Streamlit dashboard | Not started | every control calls the real backend | — |
| 9 | Security tests + evaluation (B0, E1–E5) | Not started | measured results only, no fabricated numbers | — |
| 10 | Docs + final delivery | Not started | full setup reproducible from scratch | — |

## Phase 2 verification evidence (2026-11-03)

| # | Check | Result |
|---|---|---|
| 1 | kind v0.33.0 + helm v4.3.1 installed to `~/bin` | both on PATH, working |
| 2 | kind cluster `incident-lab` (kindest/node:v1.36.1, matches kubectl) | 3/3 nodes Ready |
| 3 | Online Boutique v0.10.7 (vendored `deploy/boutique.yaml`) | 12/12 deployments Available, all pods 1/1 Running |
| 4 | kube-prometheus-stack 92.17.1 (pinned; reduced resources; NodePorts 9090/9093/3000) | Prometheus 2/2, Alertmanager 2/2, Grafana 3/3 Running; **22 targets up** |
| 5 | Custom alert rules (`deploy/alert-rules.yaml`) | PodRestarting / PodNotReady / DeploymentReplicasUnavailable / HighErrorRate / HighP95Latency loaded in Prometheus `/api/v1/rules` |
| 6 | Loki 7.5.0 single-binary + Alloy 1.15.0 (API-based tailing) | Loki 2/2 Running; labels `namespace`/`pod`/`container`; real boutique log lines queryable at `http://127.0.0.1:13100` |
| 7 | Chaos Mesh 2.8.7 (containerd socket) | controller ×3 + daemons ×2 + dns-server Running |
| 8 | `scripts/lab_health.sh` | **ALL 7 CHECKS PASSED** |
| 9 | **GATE**: `inject_fault.sh oom_checkout` → checkoutservice restarts (OOMKilled, restarts 1→6, CrashLoopBackOff) → **PodRestarting alert fired in Alertmanager** (`state=active`, labels namespace/pod/severity captured) | **PASS** — alert appeared at t+140s of polling |
| 10 | `cleanup_fault.sh oom_checkout` | rollout undone; fresh pod 1/1 Running, 0 restarts |
| 11 | Full pytest suite | **25/25 passed** (7 lab integration + 7 DB integration + 11 unit) |

## Issues found & fixed during the Phase 2 loop

1. **Port 3100 occupied** by another local project (`sashalms-nginx-1`, which also owns 8000/4100) → Loki host port moved to **13100**; port preflight added to `lab_up.sh`.
2. **NodePort range violation** — first kind config mapped 33100 (>32767 max) → corrected to 32100; cluster recreated (doubles as from-scratch reproducibility run).
3. **Loki chart v7 single-binary validation** — requires `write/read/backend.replicas: 0` and shipped memcached caches despite single-binary mode → values fixed, caches disabled.
4. **Alertmanager never created** — operator error `undefined receiver "null" used in route`: chart templates reference a `"null"` receiver that my replaced config didn't define → added no-op `"null"` receiver; Alertmanager reconciled within 20s.
5. **Boutique Python services CrashLooping** — 200m CPU limit + 1s gRPC probes kill them during slow start → CPU limits raised to 500m for emailservice/recommendationservice in `lab_up.sh` (documented constrained-lab adjustment).
6. **Alloy shipped no logs** — file-based tailing from a Deployment can't read other nodes' `/var/log/pods` → switched to `loki.source.kubernetes` (API-based) + `pods/log` RBAC, single replica.
7. **OOM fault thresholds** — Kubernetes rejected limit < request (20Mi vs 64Mi request); then 20Mi and 8Mi limits did not OOM (Go cgroup-aware GC compresses to ~6.8MiB) → final: requests 2Mi / limit 5Mi → reliable OOMKilled loop.
8. **Flaky registries** — Docker Hub TLS timeouts / unexpected EOF (grafana, kindest/node) → retry loops + pod-deletion nudges in `wait_pods_ready`.
9. `charts.chaos-mesh.org` DNS failure on first add → transient; succeeded on retry.

## Lab endpoints (stable, via kind extraPortMappings)

- Prometheus `http://127.0.0.1:9090` · Alertmanager `http://127.0.0.1:9093`
- Grafana `http://127.0.0.1:3000` (admin / kubesentra) · Loki `http://127.0.0.1:13100`
- Alertmanager webhook → `http://host.docker.internal:8547/alerts` (Phase 4 target; deliveries fail until then — expected)

## Fault scenarios defined (5, with ground truth)

`oom_checkout` (verified end-to-end), `crashloop_frontend`, `imagepull_currency`,
`readiness_recommendation`, `cpu_adservice` — see `eval/scenarios/*.yaml`.

## Known issues / environment notes

- Ports 8000/3100/4100 are owned by another local project — KubeSentra uses 8547 (API) and 13100 (Loki)
- Docker Desktop daemon must be started manually; Docker Hub pulls may need retries
- Boutique CPU bump for the two Python services is a documented lab deviation (upstream manifest unchanged)
- `kubectl rollout undo` vs `kubectl apply` annotation warning on fault cleanup is benign (documented)
- 15.7 GB RAM: lab runs comfortably; keep Prometheus retention at 24h

## Tests

| Date | Suite | Result |
|---|---|---|
| 2026-11-03 | pytest (11 unit + 7 DB integration) | 15 passed (Phase 1 gate) |
| 2026-11-03 | pytest (+ 7 lab integration + 3 scenario unit) | **25 passed, 0 failed** |

## Next task

**Phase 3 — MCP read servers**: `k8s-read`, `prometheus`, `loki`, `knowledge`
(FastMCP, validated inputs, capped/redacted outputs, recorded-fixture unit
tests) against the live lab. Gate: every tool call verified against the
running cluster.
