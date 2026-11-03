#!/usr/bin/env bash
# Clean up a fault scenario by rolling the target deployment back to its
# last good revision, then waiting for it to become available again.
# Usage: scripts/cleanup_fault.sh <scenario-id>
set -euo pipefail
cd "$(dirname "$0")/.."

scen="${1:?usage: cleanup_fault.sh <scenario-id>}"

declare -A TARGET=(
  [oom_checkout]=checkoutservice
  [crashloop_frontend]=frontend
  [imagepull_currency]=currencyservice
  [readiness_recommendation]=recommendationservice
  [cpu_adservice]=adservice
)
target="${TARGET[$scen]:-}"
if [ -z "$target" ]; then echo "[fault] unknown scenario: $scen" >&2; exit 1; fi

echo "[fault] rolling back deployment/$target"
kubectl -n boutique rollout undo "deployment/$target"
kubectl -n boutique rollout status "deployment/$target" --timeout=300s
echo "[fault] $scen cleaned up - $target healthy again"
