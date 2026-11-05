#!/usr/bin/env bash
# Clean up a fault scenario by RESTORING THE ORIGINAL vendored manifest.
# (rollout-undo proved unreliable once revision history itself contained
# earlier fault injections - found during the Phase 9 evaluation runs).
# Resets every boutique deployment to its original spec, deletes stuck
# pods and waits for the application to become healthy again.
# Usage: scripts/cleanup_fault.sh <scenario-id>   (id kept for interface
# compatibility with eval/runner.py; the reset is global by design so the
# next scenario always starts from a known-good lab.)
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/bin:$PATH"

scen="${1:?usage: cleanup_fault.sh <scenario-id>}"
echo "[fault] resetting boutique to the original manifest (was: $scen)"

kubectl apply -n boutique --force -f deploy/boutique.yaml >/dev/null 2>&1 || \
  kubectl apply -n boutique -f deploy/boutique.yaml >/dev/null

# restore the constrained-lab CPU adjustments applied by lab_up.sh
kubectl -n boutique patch deployment emailservice --type=json -p \
  '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/cpu","value":"500m"}]' >/dev/null 2>&1 || true
kubectl -n boutique patch deployment recommendationservice --type=json -p \
  '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/cpu","value":"500m"}]' >/dev/null 2>&1 || true

# remove any pods stuck in fault states (they'd block rollouts)
kubectl -n boutique delete pod --field-selector=status.phase!=Running \
  --grace-period=5 >/dev/null 2>&1 || true
for st in CrashLoopBackOff ImagePullBackOff ErrImagePull; do
  kubectl -n boutique delete pod --field-selector=status.phase=Running \
    -l '!'app 2>/dev/null | true
  kubectl -n boutique get pods --no-headers 2>/dev/null | \
    awk -v st="$st" '$3==st {print $1}' | \
    xargs -r kubectl -n boutique delete pod --grace-period=5 >/dev/null 2>&1 || true
done

# wait for every deployment to converge
if kubectl -n boutique rollout status deployment --timeout=300s >/dev/null 2>&1; then
  echo "[fault] lab reset complete - boutique healthy"
else
  echo "[fault] WARNING: some deployments did not converge within 300s" >&2
  kubectl -n boutique get deploy --no-headers | awk '$2!=$3' >&2 || true
  exit 1
fi
