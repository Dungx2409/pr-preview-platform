#!/usr/bin/env bash
# ==============================================================================
# Script: test-20-cycles.sh
# Purpose: Stress-test preview lifecycle through N open/close cycles (T-4.6)
# Verifies:
#   - Automated creation & healthy transition
#   - Clean cascading deletion via resources-finalizer
#   - Zero resource leaks after every single cycle
#   - Records teardown time statistics
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/pr-preview.yaml}"

CYCLES=${1:-20}
PR_ID="cycle"
APP_NAME="preview-pr-${PR_ID}"
NS_NAME="pr-${PR_ID}"

CYAN="\033[36m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

echo "======================================================================"
echo "      PR Preview Platform - Lifecycle & Teardown Stress Test          "
echo "======================================================================"
echo -e "Total Cycles: ${CYAN}${CYCLES}${RESET}"
echo -e "Target Environment: ${CYAN}${NS_NAME}${RESET}"
echo -e "Cluster Kubeconfig: ${CYAN}${KUBECONFIG}${RESET}"
echo

# Pre-flight check: ensure clean state before starting
echo "--> Performing pre-flight teardown check..."
"${SCRIPT_DIR}/verify-teardown.sh" --pr "${PR_ID}" >/dev/null 2>&1 || {
  echo -e "${YELLOW}Cleaning up stale test resources from earlier runs...${RESET}"
  kubectl delete application "${APP_NAME}" -n argocd --ignore-not-found=true --wait=true 2>/dev/null || true
  kubectl delete ns "${NS_NAME}" --ignore-not-found=true --wait=true 2>/dev/null || true
}

TEARDOWN_TIMES=()

for ((i=1; i<=CYCLES; i++)); do
  echo "----------------------------------------------------------------------"
  echo -e "==> [Cycle ${CYAN}${i}/${CYCLES}${RESET}] Starting preview creation..."
  T_START=$(date +%s)

  # Deploy Application manifest
  cat <<APPLY_EOF | kubectl apply -f - >/dev/null
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${APP_NAME}
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
  labels:
    app.kubernetes.io/instance: ${APP_NAME}
    preview: "true"
    pr: "${PR_ID}"
spec:
  project: previews
  source:
    repoURL: https://github.com/Dungx2409/pr-preview-platform.git
    targetRevision: HEAD
    path: charts/app
    helm:
      valuesObject:
        env: "${NS_NAME}"
        pr:
          number: "${PR_ID}"
        image:
          repository: ghcr.io/dungx2409/demo-app
          tag: "latest"
        ingress:
          className: tailscale
          hostname: "${NS_NAME}"
        namespace:
          create: true
          name: "${NS_NAME}"
  destination:
    server: https://kubernetes.default.svc
    namespace: "${NS_NAME}"
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
APPLY_EOF

  # Wait for Application to sync and become Healthy (timeout: 90s)
  READY=false
  for _ in {1..30}; do
    HEALTH=$(kubectl get application "${APP_NAME}" -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null || echo "")
    SYNC=$(kubectl get application "${APP_NAME}" -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "")
    if [ "${HEALTH}" == "Healthy" ] && [ "${SYNC}" == "Synced" ]; then
      READY=true
      break
    fi
    sleep 2
  done

  if [ "${READY}" != true ]; then
    echo -e "    ${RED}[FAIL] Application did not reach Healthy/Synced state within timeout!${RESET}"
    exit 1
  fi

  T_READY=$(date +%s)
  TTR=$((T_READY - T_START))
  echo -e "    ${GREEN}✓ Preview ready${RESET} (Time-to-Ready: ${TTR}s)"

  # Teardown step
  echo "    Initiating teardown..."
  T_TD_START=$(date +%s)

  kubectl delete application "${APP_NAME}" -n argocd --wait=false >/dev/null

  # Wait for namespace to be deleted
  NS_GONE=false
  for _ in {1..45}; do
    if ! kubectl get ns "${NS_NAME}" >/dev/null 2>&1; then
      NS_GONE=true
      break
    fi
    sleep 2
  done

  if [ "${NS_GONE}" != true ]; then
    echo -e "    ${RED}[FAIL] Namespace ${NS_NAME} did not delete within timeout!${RESET}"
    exit 1
  fi

  T_TD_END=$(date +%s)
  TD_TIME=$((T_TD_END - T_TD_START))
  TEARDOWN_TIMES+=("${TD_TIME}")

  # Verify 0 leaks
  LEAKS_OUTPUT=$("${SCRIPT_DIR}/verify-teardown.sh" --pr "${PR_ID}")
  if echo "${LEAKS_OUTPUT}" | grep -q "0 resource leaks detected"; then
    echo -e "    ${GREEN}✓ Teardown verified clean${RESET} (Teardown time: ${TD_TIME}s, 0 leaks)"
  else
    echo -e "    ${RED}[FAIL] Leaks detected after cycle ${i}!${RESET}"
    echo "${LEAKS_OUTPUT}"
    exit 1
  fi
done

echo
echo "======================================================================"
echo "                      STRESS TEST RESULTS                             "
echo "======================================================================"
echo -e "Completed Cycles: ${GREEN}${CYCLES}/${CYCLES}${RESET}"
echo -e "Leaks Detected:   ${GREEN}0 LEAKS${RESET}"

# Calculate stats
SUM=0
MIN=${TEARDOWN_TIMES[0]}
MAX=${TEARDOWN_TIMES[0]}

for t in "${TEARDOWN_TIMES[@]}"; do
  SUM=$((SUM + t))
  if [ "$t" -lt "$MIN" ]; then MIN=$t; fi
  if [ "$t" -gt "$MAX" ]; then MAX=$t; fi
done

AVG=$((SUM / CYCLES))

echo "Teardown Time Statistics:"
echo "  - Min: ${MIN}s"
echo "  - Avg: ${AVG}s"
echo "  - Max: ${MAX}s"
echo "======================================================================"
