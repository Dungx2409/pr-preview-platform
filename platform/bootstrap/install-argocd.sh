#!/usr/bin/env bash
# ==============================================================================
# Script: install-argocd.sh
# Purpose: Idempotently install/upgrade Argo CD (T-2.3)
# Chart: argo/argo-cd:10.10.5 | AppVersion: v3.5.6 (Pinned per docs/versions.md)
# ==============================================================================
set -euo pipefail

NAMESPACE="argocd"
CHART_VERSION="10.10.5"
APP_VERSION="v3.5.6"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VALUES_FILE="${REPO_ROOT}/platform/argocd/values.yaml"

export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/pr-preview.yaml}"

echo "==> [Argo CD Bootstrap] Using KUBECONFIG=${KUBECONFIG}"

# 1. Pre-flight checks
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl is required." >&2; exit 1; }
command -v helm >/dev/null 2>&1 || { echo "ERROR: helm is required." >&2; exit 1; }

if ! kubectl cluster-info >/dev/null 2>&1; then
  echo "ERROR: Cannot connect to Kubernetes cluster using ${KUBECONFIG}." >&2
  exit 1
fi

# 2. Ensure target namespace exists
if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  echo "==> Creating namespace '${NAMESPACE}'..."
  kubectl create namespace "${NAMESPACE}"
fi

# 3. Handle GitHub read-only Token Secret (out-of-band)
if ! kubectl get secret github-token -n "${NAMESPACE}" >/dev/null 2>&1; then
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    echo "==> Creating secret 'github-token' from environment GITHUB_TOKEN..."
    kubectl create secret generic github-token \
      --namespace="${NAMESPACE}" \
      --from-literal=token="${GITHUB_TOKEN}" \
      --dry-run=client -o yaml | kubectl apply -f -
  else
    echo "WARNING: Secret 'github-token' not found in namespace '${NAMESPACE}'."
    echo "         Argo CD ApplicationSet PR generator will require this secret."
    echo "         You can create it later with:"
    echo "           kubectl create secret generic github-token -n ${NAMESPACE} --from-literal=token=<PAT>"
  fi
else
  echo "==> Secret 'github-token' already exists in namespace '${NAMESPACE}'."
fi

# 4. Install / Upgrade Helm chart
echo "==> Adding Argo Helm repository..."
helm repo add argo https://argoproj.github.io/argo-helm --force-update >/dev/null

echo "==> Installing / Upgrading Argo CD (chart v${CHART_VERSION}, app ${APP_VERSION})..."
helm upgrade --install argocd argo/argo-cd \
  --version "${CHART_VERSION}" \
  --namespace "${NAMESPACE}" \
  --values "${VALUES_FILE}"

# 5. Wait for all Argo CD core components
echo "==> Waiting for Argo CD components to become ready..."
kubectl rollout status deployment/argocd-server -n "${NAMESPACE}" --timeout=180s
kubectl rollout status deployment/argocd-repo-server -n "${NAMESPACE}" --timeout=180s
kubectl rollout status deployment/argocd-applicationset-controller -n "${NAMESPACE}" --timeout=180s
kubectl rollout status statefulset/argocd-application-controller -n "${NAMESPACE}" --timeout=180s

# 6. Rotate initial admin password if ARGOCD_ADMIN_PASSWORD provided
if [[ -n "${ARGOCD_ADMIN_PASSWORD:-}" ]]; then
  echo "==> Rotating initial admin password..."
  BCRYPT_HASH=$(python3 -c "import bcrypt; print(bcrypt.hashpw(b'''${ARGOCD_ADMIN_PASSWORD}''', bcrypt.gensalt()).decode())")
  MTIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  kubectl -n "${NAMESPACE}" patch secret argocd-secret \
    --type=json \
    -p="[{\"op\": \"add\", \"path\": \"/data/admin.password\", \"value\": \"$(echo -n "${BCRYPT_HASH}" | base64 -w 0)\"}, {\"op\": \"add\", \"path\": \"/data/admin.passwordMtime\", \"value\": \"$(echo -n "${MTIME}" | base64 -w 0)\"}]"

  # Delete initial admin secret so only the rotated password works
  kubectl delete secret argocd-initial-admin-secret -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1
  echo "==> Initial admin secret rotated and cleaned up."
else
  if kubectl get secret argocd-initial-admin-secret -n "${NAMESPACE}" >/dev/null 2>&1; then
    echo "NOTE: Initial admin password is stored in secret 'argocd-initial-admin-secret'."
    echo "      Rotate it using ARGOCD_ADMIN_PASSWORD=<new-password> $0"
  fi
fi

# 7. Apply AppProjects & ApplicationSet (previews)
echo "==> Synchronizing platform manifests with root values.yaml..."
python3 "${REPO_ROOT}/scripts/sync-config.py"

PROJECTS_FILE="${REPO_ROOT}/platform/argocd/project-previews.yaml"
if [[ -f "${PROJECTS_FILE}" ]]; then
  echo "==> Applying Argo CD AppProject 'previews'..."
  kubectl apply -f "${PROJECTS_FILE}"
fi

APPSET_FILE="${REPO_ROOT}/platform/argocd/applicationset-previews.yaml"
if [[ -f "${APPSET_FILE}" ]]; then
  echo "==> Applying Argo CD ApplicationSet 'previews'..."
  kubectl apply -f "${APPSET_FILE}"
fi

echo "==> [Argo CD Bootstrap] Installation completed successfully!"
echo "    Access UI locally via:"
echo "      kubectl port-forward svc/argocd-server -n ${NAMESPACE} 8080:443"
echo "      Open https://localhost:8080 (Username: admin)"
