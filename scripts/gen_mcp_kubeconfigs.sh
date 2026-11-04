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

# --- executor (Phase 6): write credential scoped to boutique only -----------
echo "[kubeconfig] waiting for executor token"
for i in $(seq 1 30); do
  if kubectl -n kubesentra-system get secret kubesentra-executor-token \
       -o jsonpath='{.data.token}' 2>/dev/null | grep -q .; then
    break
  fi
  sleep 2
done
ETOKEN=$(kubectl -n kubesentra-system get secret kubesentra-executor-token -o jsonpath='{.data.token}' | base64 -d)

cat > .secrets/k8s-write.kubeconfig <<EOF
apiVersion: v1
kind: Config
clusters:
- name: incident-lab
  cluster:
    server: ${SERVER}
    certificate-authority-data: ${CA}
contexts:
- name: kubesentra-executor@incident-lab
  context:
    cluster: incident-lab
    user: kubesentra-executor
current-context: kubesentra-executor@incident-lab
users:
- name: kubesentra-executor
  user:
    token: ${ETOKEN}
EOF
chmod 600 .secrets/k8s-write.kubeconfig 2>/dev/null || true

echo "[kubeconfig] wrote .secrets/k8s-read.kubeconfig + .secrets/k8s-write.kubeconfig"
echo "[kubeconfig] verifying read access (list boutique pods):"
kubectl --kubeconfig .secrets/k8s-read.kubeconfig -n boutique get pods --no-headers | head -3
echo "[kubeconfig] verifying WRITE is forbidden for reader (expect Denied):"
if kubectl --kubeconfig .secrets/k8s-read.kubeconfig -n boutique delete pod --all --dry-run=server >/dev/null 2>&1; then
  echo "ERROR: reader kubeconfig was allowed a write - RBAC is broken!" >&2
  exit 1
else
  echo "OK: write correctly denied for reader kubeconfig"
fi
echo "[kubeconfig] executor: server-side dry-run patch in boutique works:"
kubectl --kubeconfig .secrets/k8s-write.kubeconfig -n boutique patch deployment checkoutservice --dry-run=server -p '{"spec":{"template":{"metadata":{"labels":{"kubesentra-dryrun":"probe"}}}}}' >/dev/null && echo "OK: dry-run patch allowed"
echo "[kubeconfig] executor: boutique pod delete dry-run works:"
kubectl --kubeconfig .secrets/k8s-write.kubeconfig -n boutique delete pod --dry-run=server -l app=checkoutservice >/dev/null 2>&1 && echo "OK: delete allowed in boutique"
echo "[kubeconfig] executor CANNOT touch kube-system (expect error):"
if kubectl --kubeconfig .secrets/k8s-write.kubeconfig -n kube-system delete pod --all --dry-run=server >/dev/null 2>&1; then
  echo "ERROR: executor could write kube-system - RBAC is broken!" >&2
  exit 1
else
  echo "OK: kube-system correctly denied for executor"
fi
