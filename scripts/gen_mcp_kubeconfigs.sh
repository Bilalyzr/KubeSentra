#!/usr/bin/env bash
# Apply deploy/rbac.yaml and generate a dedicated read-only kubeconfig for
# the k8s-read MCP server at .secrets/k8s-read.kubeconfig (git-ignored).
# Phase 7 will extend this with a separate executor kubeconfig.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/bin:$PATH"

echo "[kubeconfig] applying RBAC"
kubectl apply -f deploy/rbac.yaml >/dev/null

echo "[kubeconfig] waiting for reader token"
for i in $(seq 1 30); do
  if kubectl -n kubesentra-system get secret kubesentra-reader-token \
       -o jsonpath='{.data.token}' 2>/dev/null | grep -q .; then
    break
  fi
  sleep 2
done

mkdir -p .secrets
SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
CA=$(kubectl -n kubesentra-system get secret kubesentra-reader-token -o jsonpath='{.data.ca\.crt}')
TOKEN=$(kubectl -n kubesentra-system get secret kubesentra-reader-token -o jsonpath='{.data.token}' | base64 -d)

cat > .secrets/k8s-read.kubeconfig <<EOF
apiVersion: v1
kind: Config
clusters:
- name: incident-lab
  cluster:
    server: ${SERVER}
    certificate-authority-data: ${CA}
contexts:
- name: kubesentra-reader@incident-lab
  context:
    cluster: incident-lab
    user: kubesentra-reader
current-context: kubesentra-reader@incident-lab
users:
- name: kubesentra-reader
  user:
    token: ${TOKEN}
EOF
chmod 600 .secrets/k8s-read.kubeconfig 2>/dev/null || true

echo "[kubeconfig] wrote .secrets/k8s-read.kubeconfig"
echo "[kubeconfig] verifying read access (list boutique pods):"
kubectl --kubeconfig .secrets/k8s-read.kubeconfig -n boutique get pods --no-headers | head -3
echo "[kubeconfig] verifying WRITE is forbidden (expect Denied):"
if kubectl --kubeconfig .secrets/k8s-read.kubeconfig -n boutique delete pod --all --dry-run=server >/dev/null 2>&1; then
  echo "ERROR: reader kubeconfig was allowed a write - RBAC is broken!" >&2
  exit 1
else
  echo "OK: write correctly denied for reader kubeconfig"
fi
