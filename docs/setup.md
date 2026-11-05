# KubeSentra — Setup Guide

One-time prerequisites (Windows dev machine, Git Bash; same flow works on
Linux/macOS): Python 3.11+, Docker Desktop, Git; `kind` and `helm` in
`~/bin` (installed once — see scripts). ~16 GB RAM recommended (the lab
runs on 15.7 GB with reduced-resource values).

## 1. Environment + database (5 min)

```bash
git clone https://github.com/Bilalyzr/KubeSentra.git && cd KubeSentra
scripts/dev.sh env            # venv + pinned dependencies
cp .env.example .env          # then edit: LLM key (below), APPROVAL_TOKEN
docker compose up -d postgres
scripts/dev.sh migrate        # migrations 0001-0004
scripts/dev.sh test           # unit tests (no cluster needed)
```

LLM (`.env`): for Gemini use the **native** provider (Gemini-3 thought
signatures break multi-turn tool loops through the OpenAI-compat layer):

```ini
LLM_PROVIDER=google
LLM_API_KEY=AIza…            # or a current AQ…-format key
LLM_PRIMARY_MODEL=gemini-flash-latest   # resolves to the current flash
LLM_CHEAP_MODEL=gemini-flash-lite-latest
```

OpenAI-compatible endpoints and Anthropic are also supported
(`agent/llm.py` has copy-paste examples). Without a key the system fails
honestly (`LLMNotConfigured`) — nothing is simulated.

## 2. Kubernetes laboratory (20–30 min first run: image pulls)

```bash
scripts/lab_up.sh             # kind cluster + Boutique + monitoring +
                              # Loki/Alloy + Chaos Mesh + metrics-server +
                              # RBAC + kubeconfigs; waits until healthy
scripts/lab_health.sh         # 7/7 checks must pass
```

Stable endpoints (kind port mappings): Prometheus :9090 · Alertmanager
:9093 · Grafana :3000 (admin/kubesentra) · Loki :13100. Alertmanager is
pre-wired to POST to `http://host.docker.internal:8547/alerts`.

## 3. Knowledge base (one command, model auto-downloads to .models/)

```bash
.venv/Scripts/python -m knowledge.ingest   # 23 runbooks → 115 embedded chunks
```

## 4. Run

```bash
scripts/dev.sh serve          # API on :8547
scripts/dev.sh dashboard      # Streamlit on :8551
```

Try it end-to-end (real alert → investigation → approval):
```bash
scripts/inject_fault.sh oom_checkout
scripts/gate_watch.py         # waits for the pause, submits decisions
```

## Fault scenarios

`eval/scenarios/*.yaml` (5, with ground truth):
`oom_checkout`, `crashloop_frontend`, `imagepull_currency`,
`readiness_recommendation`, `cpu_adservice`. Inject/cleanup:
`scripts/inject_fault.sh <id>` / `scripts/cleanup_fault.sh <id>` (cleanup
re-applies the original manifest — deterministic). Faults only ever touch
the `boutique` namespace.

## Teardown / troubleshooting

- `scripts/lab_down.sh` deletes the kind cluster (Postgres is untouched).
- Lab flaky after a Docker restart: `helm upgrade monitoring
  prometheus-community/kube-prometheus-stack --version 92.17.1 -n monitoring
  -f deploy/values/prometheus-values.yaml` re-renders stale static targets.
- Slow first runbook search (~50 s) is the embedding model cold-load; the
  API warms it in the background at startup.
- Port conflicts: 8547 (API) and 13100 (Loki) were chosen because 8000 and
  3100 are commonly taken on dev machines.
