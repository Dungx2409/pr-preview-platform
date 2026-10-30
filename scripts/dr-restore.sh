#!/usr/bin/env bash
# ==============================================================================
# Script: dr-restore.sh
# Purpose: End-to-end Disaster Recovery (DR) restoration from a clean VM (T-7.1)
# Measures total stopwatch time to reconstruct the entire platform.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SECRETS_DIR="${HOME}/.config/pr-preview/dr-secrets"

export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/pr-preview.yaml}"

echo "======================================================================"
echo "    PR Preview Platform - Disaster Recovery Rebuild Drill (T-7.1)    "
echo "======================================================================"
echo "Starting Stopwatch at: $(date)"
START_SECONDS=$(date +%s)

# ------------------------------------------------------------------------------
# 1. Pre-flight Checks
# ------------------------------------------------------------------------------
echo "==> [1/7] Pre-flight checks..."
command -v ansible-playbook >/dev/null 2>&1 || { echo "ERROR: ansible-playbook required" >&2; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl required" >&2; exit 1; }
command -v helm >/dev/null 2>&1 || { echo "ERROR: helm required" >&2; exit 1; }

if command -v VBoxManage >/dev/null 2>&1; then
  VM_MEM=$(VBoxManage showvminfo "devops-server" --machinereadable 2>/dev/null | grep -E '^memory=' | cut -d= -f2 || echo "")
  if [[ -n "${VM_MEM}" && "${VM_MEM}" -lt 4096 ]]; then
    echo "WARNING: VM memory is configured to only ${VM_MEM}MB." >&2
    echo "         Minimum 4096MB recommended (8192MB standard) to prevent swap thrashing." >&2
    echo "         Run: VBoxManage modifyvm \"devops-server\" --memory 8192" >&2
  fi
fi

# ------------------------------------------------------------------------------
# 2. Provision k3s Node via Ansible
# ------------------------------------------------------------------------------
echo "==> [2/7] Provisioning k3s cluster via Ansible..."
ansible-playbook -i "${REPO_ROOT}/ansible/inventory/local.ini" "${REPO_ROOT}/ansible/site.yml"

echo "==> Verifying k3s API connectivity..."
kubectl wait --for=condition=ready node/devops-server --timeout=120s
kubectl get nodes -o wide

# ------------------------------------------------------------------------------
# 3. Restore Out-of-Band Secrets & Namespaces
# ------------------------------------------------------------------------------
echo "==> [3/7] Restoring platform namespaces & secrets..."
kubectl create namespace tailscale --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace shared --dry-run=client -o yaml | kubectl apply -f -

if [[ -d "${SECRETS_DIR}" ]]; then
  echo "==> Applying secrets from local backup: ${SECRETS_DIR}..."
  [[ -f "${SECRETS_DIR}/operator-oauth.yaml" ]] && kubectl apply -f "${SECRETS_DIR}/operator-oauth.yaml"
  [[ -f "${SECRETS_DIR}/github-token.yaml" ]] && kubectl apply -f "${SECRETS_DIR}/github-token.yaml"
  [[ -f "${SECRETS_DIR}/shared-postgres.yaml" ]] && kubectl apply -f "${SECRETS_DIR}/shared-postgres.yaml"
else
  echo "WARNING: ${SECRETS_DIR} not found. Ensure secrets are created manually."
fi

# ------------------------------------------------------------------------------
# 4. Bootstrap Tailscale Operator
# ------------------------------------------------------------------------------
echo "==> [4/7] Bootstrapping Tailscale Kubernetes Operator..."
bash "${REPO_ROOT}/platform/bootstrap/install-tailscale.sh"

# ------------------------------------------------------------------------------
# 5. Bootstrap Argo CD & GitOps Engine
# ------------------------------------------------------------------------------
echo "==> [5/7] Bootstrapping Argo CD..."
bash "${REPO_ROOT}/platform/bootstrap/install-argocd.sh"

echo "==> Applying Argo CD AppProject and Applications..."
kubectl apply -f "${REPO_ROOT}/platform/argocd/project-previews.yaml"
kubectl apply -f "${REPO_ROOT}/platform/argocd/application-shared.yaml"

echo "==> Applying ApplicationSet previews (waiting for CRD discovery)..."
APPSET_APPLIED=false
for attempt in {1..6}; do
  if kubectl apply -f "${REPO_ROOT}/platform/argocd/applicationset-previews.yaml"; then
    APPSET_APPLIED=true
    break
  fi
  echo "    ApplicationSet CRD registering, refreshing discovery cache in 5s (attempt ${attempt}/6)..."
  rm -rf "${HOME}/.kube/cache"
  sleep 5
done
if [[ "${APPSET_APPLIED}" != true ]]; then
  echo "ERROR: Failed to apply ApplicationSet after 6 attempts." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# 6. Bootstrap Monitoring Stack & Exporter
# ------------------------------------------------------------------------------
echo "==> [6/7] Bootstrapping Monitoring Stack (Prometheus, Grafana, Exporter)..."
bash "${REPO_ROOT}/platform/bootstrap/install-monitoring.sh"

echo "==> Deploying Reaper CronJob..."
kubectl apply -f "${REPO_ROOT}/platform/reaper/rbac.yaml"
kubectl apply -f "${REPO_ROOT}/platform/reaper/configmap.yaml"
kubectl apply -f "${REPO_ROOT}/platform/reaper/cronjob.yaml"

# ------------------------------------------------------------------------------
# 7. Verification & Health Audit
# ------------------------------------------------------------------------------
echo "==> [7/7] Waiting for critical platform workloads to become Ready..."

echo "--> Waiting for Argo CD to sync and deploy shared environment..."
# Wait up to 180s for deployment/shared-main-app in namespace shared
for i in {1..36}; do
  if kubectl get deployment shared-main-app -n shared >/dev/null 2>&1; then
    break
  fi
  echo "    Waiting for shared-main-app deployment to be generated by Argo CD ($(( i * 5 ))s)..."
  sleep 5
done

kubectl rollout status deployment/shared-main-app -n shared --timeout=180s

echo "--> Checking namespace pod summaries:"
kubectl get pods -A | grep -E "tailscale|argocd|monitoring|shared"

END_SECONDS=$(date +%s)
TOTAL_DURATION=$(( END_SECONDS - START_SECONDS ))
MINUTES=$(( TOTAL_DURATION / 60 ))
SECONDS=$(( TOTAL_DURATION % 60 ))

echo "======================================================================"
echo "    Disaster Recovery (DR) Rebuild Completed Successfully!           "
echo "    Total Elapsed Time: ${MINUTES}m ${SECONDS}s (${TOTAL_DURATION}s)               "
echo "======================================================================"
