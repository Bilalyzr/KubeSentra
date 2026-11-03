#!/usr/bin/env bash
# Health check for the KubeSentra laboratory. Verifies every layer that the
# later phases depend on. Exits non-zero if any check fails.
# Usage: scripts/lab_health.sh [--wait]  (--wait retries for up to 5 min)
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/bin:$PATH"

WAIT="${1:-}"
deadline=$((SECONDS + 300))
while true; do
  fails=0

  # 1. cluster nodes
  ready=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready " || true)
  total=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
  [ "$ready" = "3" ] && [ "$total" = "3" ] && echo "PASS nodes: $ready/$total Ready" || { echo "FAIL nodes: $ready/$total Ready"; fails=1; }

  # 2. boutique deployments
  btotal=$(kubectl -n boutique get deploy --no-headers 2>/dev/null | wc -l)
  bavail=$(kubectl -n boutique get deploy --no-headers 2>/dev/null | awk '{split($2,a,"/"); if (a[1]>=a[2]) print}' | wc -l)
  [ "$bavail" = "$btotal" ] && [ "$btotal" -gt 0 ] && echo "PASS boutique: $bavail/$btotal deployments available" || { echo "FAIL boutique: $bavail/$btotal deployments available"; fails=1; }

  # 3. prometheus targets
  up=$(curl -s --max-time 5 http://127.0.0.1:9090/api/v1/targets | grep -o '"health":"up"' | wc -l)
  [ "$up" -ge 5 ] && echo "PASS prometheus: $up targets up" || { echo "FAIL prometheus: $up targets up"; fails=1; }

  # 4. alertmanager reachable
  am=$(curl -s --max-time 5 http://127.0.0.1:9093/-/ready || true)
  echo "$am" | grep -q "OK" && echo "PASS alertmanager: ready" || { echo "FAIL alertmanager: $am"; fails=1; }

  # 5. loki serving
  loki=$(curl -s --max-time 5 http://127.0.0.1:13100/ready || true)
  echo "$loki" | grep -q -E "ready|OK" && echo "PASS loki: ready" || { echo "FAIL loki: $loki"; fails=1; }

  # 6. loki has ingested boutique logs
  labels=$(curl -s --max-time 5 'http://127.0.0.1:13100/loki/api/v1/labels?limit=50' | grep -o '"namespace"' | head -1)
  [ -n "$labels" ] && echo "PASS loki ingestion: namespace label present" || { echo "FAIL loki ingestion: no labels yet"; fails=1; }

  # 7. chaos-mesh controller
  cm=$(kubectl -n chaos-mesh get deploy chaos-controller-manager -o jsonpath='{.status.availableReplicas}' 2>/dev/null || true)
  [ -n "$cm" ] && [ "$cm" -ge 1 ] && echo "PASS chaos-mesh: controller available" || { echo "FAIL chaos-mesh: controller not available"; fails=1; }

  [ "$fails" = "0" ] && { echo "[lab-health] ALL CHECKS PASSED"; exit 0; }
  if [ "$WAIT" != "--wait" ] || [ $SECONDS -ge $deadline ]; then break; fi
  sleep 15
done
echo "[lab-health] FAILED - lab not fully healthy"
exit 1
