#!/usr/bin/env bash
# Bring up the complete KubeSentra laboratory:
# kind cluster -> Online Boutique -> kube-prometheus-stack (+alert rules)
# -> Loki + Alloy -> Chaos Mesh. Idempotent: safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/bin:$PATH"

KIND_IMAGE="kindest/node:v1.36.1"
KPS_VERSION="92.17.1"     # kube-prometheus-stack
LOKI_VERSION="7.5.0"      # grafana/loki
ALLOY_VERSION="1.15.0"    # grafana/alloy
CHAOS_VERSION="$(helm search repo chaos-mesh/chaos-mesh --versions | awk 'NR==2{print $2}')"

log() { echo "[lab-up] $*"; }

# Tolerant pod waiter: pods may not exist yet (operator still creating), and
# the flaky upstream registry can stall pulls - pods stuck on image errors
# are deleted once to force a retry.
wait_pods_ready() {  # <namespace> <label-selector> [max-seconds]
  local ns="$1" label="$2" budget="${3:-900}" waited=0 stuck
  until kubectl -n "$ns" wait --for=condition=Ready pod -l "$label" --timeout=30s >/dev/null 2>&1; do
    if [ "$waited" -ge "$budget" ]; then
      echo "[lab-up] TIMEOUT waiting for pods -l '$label' in $ns:" >&2
      kubectl -n "$ns" get pods -l "$label" >&2 || true
      exit 1
    fi
    stuck=$(kubectl -n "$ns" get pods -l "$label" --no-headers 2>/dev/null \
             | grep -E "ErrImagePull|ImagePullBackOff" | awk '{print $1}')
    if [ -n "$stuck" ]; then
      log "nudging image pulls: $stuck"
      for pod in $stuck; do kubectl -n "$ns" delete pod "$pod" >/dev/null 2>&1 || true; done
    fi
    sleep 20; waited=$((waited + 50))
  done
}

# --- 0. preflight ----------------------------------------------------------
if ! docker info >/dev/null 2>&1; then
  echo "[lab-up] Docker daemon not running - start Docker Desktop first." >&2
  exit 1
fi
for port in 9090 9093 3000 13100; do
  if netstat -ano | grep LISTENING | grep -q ":$port "; then
    echo "[lab-up] host port $port is already in use (another local project?). Aborting." >&2
    exit 1
  fi
done

# --- 1. cluster --------------------------------------------------------------
if kind get clusters | grep -q '^incident-lab$'; then
  log "kind cluster incident-lab already exists"
else
  log "creating kind cluster incident-lab ($KIND_IMAGE)"
  kind create cluster --config deploy/kind-config.yaml --image "$KIND_IMAGE"
fi
kubectl wait --for=condition=Ready node --all --timeout=300s
log "nodes ready"

# --- 2. demo application -----------------------------------------------------
kubectl create namespace boutique 2>/dev/null || true
kubectl apply -n boutique -f deploy/boutique.yaml >/dev/null
# constrained-lab adjustment: the two Python services need more CPU than the
# upstream 200m limit, or their 1s gRPC probes kill them during slow starts
kubectl -n boutique patch deployment emailservice --type=json -p \
  '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/cpu","value":"500m"}]' >/dev/null
kubectl -n boutique patch deployment recommendationservice --type=json -p \
  '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/cpu","value":"500m"}]' >/dev/null
log "waiting for Online Boutique deployments (image pulls can take minutes)"
kubectl wait -n boutique deployment --all --for=condition=Available --timeout=1200s
wait_pods_ready boutique "app" 900s
log "boutique available: $(kubectl -n boutique get deploy -o name | wc -l) deployments"

# --- 3. metrics + alerting ---------------------------------------------------
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null 2>&1 || true
helm repo update >/dev/null

helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --version "$KPS_VERSION" -n monitoring --create-namespace \
  -f deploy/values/prometheus-values.yaml >/dev/null
kubectl apply -f deploy/alert-rules.yaml >/dev/null
log "kube-prometheus-stack $KPS_VERSION installed, custom alert rules applied"

# --- 4. logs: Loki + Alloy -----------------------------------------------------
helm upgrade --install loki grafana/loki --version "$LOKI_VERSION" \
  -n monitoring -f deploy/values/loki-values.yaml >/dev/null
kubectl apply -f deploy/loki-nodeport.yaml >/dev/null
kubectl apply -f deploy/alloy-rbac.yaml >/dev/null
helm upgrade --install alloy grafana/alloy --version "$ALLOY_VERSION" \
  -n monitoring -f deploy/values/alloy-values.yaml >/dev/null
log "loki $LOKI_VERSION + alloy $ALLOY_VERSION installed"

# --- 5. chaos mesh -------------------------------------------------------------
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  ${CHAOS_VERSION:+--version "$CHAOS_VERSION"} \
  -n chaos-mesh --create-namespace \
  -f deploy/values/chaos-mesh-values.yaml >/dev/null
log "chaos-mesh installed"

# --- 6. wait for the monitoring stack -------------------------------------------
# Prometheus/Alertmanager (operator-managed) and Loki run as statefulsets, so
# wait on PODS by label rather than deployments.
log "waiting for monitoring + chaos pods"
wait_pods_ready monitoring "app.kubernetes.io/name=alertmanager"
wait_pods_ready monitoring "app.kubernetes.io/name=prometheus"
wait_pods_ready monitoring "app.kubernetes.io/name=loki"
wait_pods_ready monitoring "app.kubernetes.io/name=alloy"
wait_pods_ready chaos-mesh "app.kubernetes.io/chaos-mesh=controller-manager"

log "lab is up. Endpoints:"
log "  Prometheus  http://127.0.0.1:9090"
log "  Alertmanager http://127.0.0.1:9093"
log "  Grafana     http://127.0.0.1:3000  (admin / kubesentra)"
log "  Loki        http://127.0.0.1:13100"
log "Verify everything: scripts/lab_health.sh"
