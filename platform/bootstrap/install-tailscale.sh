#!/usr/bin/env bash
# ==============================================================================
# Script: install-tailscale.sh
# Purpose: Idempotently install/upgrade Tailscale Kubernetes Operator (T-2.1)
# Version: 1.104.2 (Pinned per docs/versions.md)
# ==============================================================================
set -euo pipefail

NAMESPACE="tailscale"
CHART_VERSION="1.104.2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VALUES_FILE="${REPO_ROOT}/platform/tailscale/values.yaml"

# Default to ~/.kube/pr-preview.yaml if KUBECONFIG not set
export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/pr-preview.yaml}"

echo "==> [Tailscale Bootstrap] Using KUBECONFIG=${KUBECONFIG}"

# 1. Pre-flight checks
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl is required but not installed." >&2; exit 1; }
command -v helm >/dev/null 2>&1 || { echo "ERROR: helm is required but not installed." >&2; exit 1; }

if ! kubectl cluster-info >/dev/null 2>&1; then
  echo "ERROR: Cannot connect to Kubernetes cluster using ${KUBECONFIG}." >&2
  exit 1
fi

# 2. Ensure target namespace exists
if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  echo "==> Creating namespace '${NAMESPACE}'..."
  kubectl create namespace "${NAMESPACE}"
fi

# 3. Ensure OAuth Secret exists out-of-band
if ! kubectl get secret operator-oauth -n "${NAMESPACE}" >/dev/null 2>&1; then
  if [[ -n "${TS_OAUTH_CLIENT_ID:-}" && -n "${TS_OAUTH_CLIENT_SECRET:-}" ]]; then
    echo "==> Creating secret 'operator-oauth' from environment credentials..."
    kubectl create secret generic operator-oauth \
      --namespace="${NAMESPACE}" \
      --from-literal=client_id="${TS_OAUTH_CLIENT_ID}" \
      --from-literal=client_secret="${TS_OAUTH_CLIENT_SECRET}" \
      --dry-run=client -o yaml | kubectl apply -f -
  else
    echo "ERROR: Secret 'operator-oauth' not found in namespace '${NAMESPACE}'." >&2
    echo "Please provide TS_OAUTH_CLIENT_ID and TS_OAUTH_CLIENT_SECRET as environment variables, or create the secret manually:" >&2
    echo "  kubectl create secret generic operator-oauth -n ${NAMESPACE} --from-literal=client_id=... --from-literal=client_secret=..." >&2
    exit 1
  fi
else
  echo "==> Secret 'operator-oauth' already exists in namespace '${NAMESPACE}'."
fi

# 4. Install / Upgrade Helm chart
echo "==> Adding Tailscale Helm repository..."
helm repo add tailscale https://pkgs.tailscale.com/helmcharts --force-update >/dev/null

echo "==> Installing / Upgrading Tailscale Operator (chart v${CHART_VERSION})..."
helm upgrade --install tailscale-operator tailscale/tailscale-operator \
  --version "${CHART_VERSION}" \
  --namespace "${NAMESPACE}" \
  --values "${VALUES_FILE}"

# 5. Wait for Operator deployment rollout
echo "==> Waiting for operator deployment to become ready..."
kubectl rollout status deployment/operator -n "${NAMESPACE}" --timeout=120s

echo "==> [Tailscale Bootstrap] Completed successfully! Operator is Running."
