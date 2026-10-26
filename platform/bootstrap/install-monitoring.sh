#!/usr/bin/env bash
# ==============================================================================
# Script: install-monitoring.sh
# Purpose: Idempotently install/upgrade kube-prometheus-stack (T-6.1, SPEC §6.8)
# Chart: prometheus-community/kube-prometheus-stack:92.11.0 (appVersion: v0.94.1)
# ==============================================================================
set -euo pipefail

NAMESPACE="monitoring"
CHART_VERSION="92.11.0"
APP_VERSION="v0.94.1"
RELEASE_NAME="kube-prometheus-stack"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VALUES_FILE="${REPO_ROOT}/platform/monitoring/values.yaml"
CACHE_TARBALL="${HOME}/.cache/helm/repository/kube-prometheus-stack-${CHART_VERSION}.tgz"

export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/pr-preview.yaml}"

echo "==> [Monitoring Bootstrap] Using KUBECONFIG=${KUBECONFIG}"

# 1. Pre-flight checks
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl is required." >&2; exit 1; }
command -v helm >/dev/null 2>&1 || { echo "ERROR: helm is required." >&2; exit 1; }

if ! kubectl cluster-info >/dev/null 2>&1; then
  echo "ERROR: Cannot connect to Kubernetes cluster using ${KUBECONFIG}." >&2
  exit 1
fi

# 2. Ensure target namespace exists with PSS Privileged (Required for node-exporter host metrics)
if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  echo "==> Creating namespace '${NAMESPACE}' with PSS privileged (for node-exporter)..."
  kubectl create namespace "${NAMESPACE}"
  kubectl label namespace "${NAMESPACE}" \
    pod-security.kubernetes.io/enforce=privileged \
    pod-security.kubernetes.io/warn=baseline \
    pod-security.kubernetes.io/audit=baseline \
    --overwrite
else
  echo "==> Namespace '${NAMESPACE}' already exists. Ensuring PSS privileged..."
  kubectl label namespace "${NAMESPACE}" \
    pod-security.kubernetes.io/enforce=privileged \
    pod-security.kubernetes.io/warn=baseline \
    pod-security.kubernetes.io/audit=baseline \
    --overwrite
fi

# 3. Determine chart source (local cache or repo)
CHART_SOURCE="prometheus-community/kube-prometheus-stack"
if [[ -f "${CACHE_TARBALL}" ]]; then
  CHART_SOURCE="${CACHE_TARBALL}"
  echo "==> Using local cached chart: ${CHART_SOURCE}"
else
  echo "==> Ensuring prometheus-community helm repo is configured..."
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
fi

# 4. Install / Upgrade Helm chart
echo "==> Installing / Upgrading kube-prometheus-stack (chart v${CHART_VERSION}, app ${APP_VERSION})..."
helm upgrade --install "${RELEASE_NAME}" "${CHART_SOURCE}" \
  --version "${CHART_VERSION}" \
  --namespace "${NAMESPACE}" \
  --values "${VALUES_FILE}" \
  --timeout 10m0s \
  --wait

echo
echo "==> [Monitoring Bootstrap] Rollout successful!"
echo "==> Verification details:"
kubectl get pods -n "${NAMESPACE}"
echo
echo "==> Access Grafana via local port-forward:"
echo "    KUBECONFIG=${KUBECONFIG} kubectl port-forward svc/${RELEASE_NAME}-grafana -n ${NAMESPACE} 3000:80"
echo "    URL: http://localhost:3000 (User: admin / Password: admin)"
echo
echo "==> Access Prometheus via local port-forward:"
echo "    KUBECONFIG=${KUBECONFIG} kubectl port-forward svc/${RELEASE_NAME}-prometheus -n ${NAMESPACE} 9090:9090"
echo "    URL: http://localhost:9090"
