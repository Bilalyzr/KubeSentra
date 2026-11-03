#!/usr/bin/env bash
# Inject a fault scenario into the boutique lab.
# Usage: scripts/inject_fault.sh <scenario-id>
# Scenarios are defined in eval/scenarios/*.yaml; the imperative patch for
# each id lives here. Cleanup: scripts/cleanup_fault.sh <scenario-id>
set -euo pipefail
cd "$(dirname "$0")/.."

scen="${1:?usage: inject_fault.sh <oom_checkout|crashloop_frontend|imagepull_currency|readiness_recommendation|cpu_adservice>}"
echo "[fault] injecting: $scen"

case "$scen" in
  oom_checkout)
    # checkoutservice (Go, cgroup-aware GC) idles at ~7MiB working set;
    # a 5Mi limit is below what the runtime can compress to -> OOMKilled loop
    kubectl -n boutique patch deployment checkoutservice --type=json -p \
      '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/memory","value":"2Mi"},
        {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"5Mi"}]' >/dev/null
    ;;
  crashloop_frontend)
    kubectl -n boutique patch deployment frontend --type=json -p \
      '[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["/nonexistent-binary"]}]' >/dev/null
    ;;
  imagepull_currency)
    kubectl -n boutique set image deployment/currencyservice \
      "server=us-central1-docker.pkg.dev/online-boutique-ci/microservices-demo/currencyservice:tag-does-not-exist" >/dev/null
    ;;
  readiness_recommendation)
    kubectl -n boutique patch deployment recommendationservice --type=json -p \
      '[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/port","value":9999}]' >/dev/null
    ;;
  cpu_adservice)
    kubectl -n boutique patch deployment adservice --type=json -p \
      '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/cpu","value":"10m"}]' >/dev/null
    ;;
  *)
    echo "[fault] unknown scenario: $scen" >&2; exit 1 ;;
esac

echo "[fault] injected $scen - watch with: kubectl -n boutique get pods -w"
