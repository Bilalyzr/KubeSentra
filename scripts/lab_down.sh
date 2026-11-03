#!/usr/bin/env bash
# Tear down the KubeSentra laboratory cluster.
# The Postgres container (docker compose) is NOT touched.
set -euo pipefail
export PATH="$HOME/bin:$PATH"

if kind get clusters 2>/dev/null | grep -q '^incident-lab$'; then
  kind delete cluster --name incident-lab
  echo "[lab-down] cluster incident-lab deleted"
else
  echo "[lab-down] no incident-lab cluster found (nothing to do)"
fi
