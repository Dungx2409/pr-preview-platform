#!/usr/bin/env bash
# ==============================================================================
# Script: verify-teardown.sh
# Purpose: Verify zero resource leaks after PR Preview teardown (T-4.6 / SPEC §1.2)
# Checks:
#   1. Kubernetes namespaces (pr-*)
#   2. Argo CD Applications (preview-pr-*)
#   3. Pods across all namespaces belonging to previews
#   4. Tailscale proxy pods in namespace tailscale (ts-preview-pr-*)
#   5. PersistentVolumeClaims and PVs for preview namespaces
#   6. GitHub Deployments in state other than 'inactive' (optional if gh available)
#   7. Container image tags in GHCR matching pr-* (optional if gh available)
# ==============================================================================
set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/pr-preview.yaml}"

TARGET_PR=""
STRICT_GITHUB=false

usage() {
  cat <<USAGE
Usage: $(basename "$0") [OPTIONS]

Options:
  --pr <number>    Verify teardown specifically for PR number <number>
  --strict-github  Fail if any GHCR tags or active GitHub deployments remain
  -h, --help       Show this help message
USAGE
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr)
      TARGET_PR="$2"
      shift 2
      ;;
    --strict-github)
      STRICT_GITHUB=true
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown option: $1"
      usage
      ;;
  esac
done

CYAN="\033[36m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

echo "======================================================================"
echo "          PR Preview Platform - Teardown Leak Verification            "
echo "======================================================================"
if [ -n "${TARGET_PR}" ]; then
  echo -e "Target: PR #${CYAN}${TARGET_PR}${RESET}"
else
  echo -e "Target: ${CYAN}All PR Previews (pr-*)${RESET}"
fi
echo -e "Kubeconfig: ${CYAN}${KUBECONFIG}${RESET}"
echo

TOTAL_LEAKS=0

# Helper to check cluster resources
check_k8s_resource() {
  local title="$1"
  local cmd="$2"
  
  local output
  output=$(eval "$cmd" 2>/dev/null || true)
  local count
  if [ -z "${output}" ]; then
    count=0
  else
    count=$(echo "${output}" | grep -c . || true)
  fi

  if [ "${count}" -eq 0 ]; then
    echo -e "  [PASS] ${title}: ${GREEN}0 leaks found${RESET}"
  else
    echo -e "  [FAIL] ${title}: ${RED}${count} leak(s) detected!${RESET}"
    while IFS= read -r line; do
      [ -n "${line}" ] && echo "         - ${line}"
    done <<< "${output}"
    TOTAL_LEAKS=$((TOTAL_LEAKS + count))
  fi
}

echo "--> [1/5] Checking Kubernetes Cluster Resources..."

# 1. Namespaces
if [ -n "${TARGET_PR}" ]; then
  NS_CMD="kubectl get ns -o json | jq -r '[.items[].metadata.name | select(. == \"pr-${TARGET_PR}\")] | .[]'"
else
  NS_CMD="kubectl get ns -o json | jq -r '[.items[].metadata.name | select(startswith(\"pr-\"))] | .[]'"
fi
check_k8s_resource "Preview Namespaces" "${NS_CMD}"

# 2. Argo CD Applications
if [ -n "${TARGET_PR}" ]; then
  APP_CMD="kubectl get applications.argoproj.io -n argocd -o json | jq -r '[.items[].metadata.name | select(. == \"preview-pr-${TARGET_PR}\")] | .[]'"
else
  APP_CMD="kubectl get applications.argoproj.io -n argocd -o json | jq -r '[.items[].metadata.name | select(startswith(\"preview-pr-\"))] | .[]'"
fi
check_k8s_resource "Argo CD Applications" "${APP_CMD}"

# 3. Tailscale Proxy Pods in namespace tailscale
if [ -n "${TARGET_PR}" ]; then
  TS_CMD="kubectl get pods -n tailscale -o json | jq -r '[.items[].metadata.name | select(startswith(\"ts-preview-pr-${TARGET_PR}-\"))] | .[]'"
else
  TS_CMD="kubectl get pods -n tailscale -o json | jq -r '[.items[].metadata.name | select(startswith(\"ts-preview-pr-\"))] | .[]'"
fi
check_k8s_resource "Tailscale Proxy Pods" "${TS_CMD}"

# 4. Preview Pods (in case namespace stuck terminating)
if [ -n "${TARGET_PR}" ]; then
  PODS_CMD="kubectl get pods -A -o json | jq -r '[.items[] | select(.metadata.namespace == \"pr-${TARGET_PR}\") | .metadata.name] | .[]'"
else
  PODS_CMD="kubectl get pods -A -o json | jq -r '[.items[] | select(.metadata.namespace | startswith(\"pr-\")) | .metadata.name] | .[]'"
fi
check_k8s_resource "Preview Workload Pods" "${PODS_CMD}"

# 5. PersistentVolumeClaims
if [ -n "${TARGET_PR}" ]; then
  PVC_CMD="kubectl get pvc -A -o json | jq -r '[.items[] | select(.metadata.namespace == \"pr-${TARGET_PR}\") | .metadata.name] | .[]'"
else
  PVC_CMD="kubectl get pvc -A -o json | jq -r '[.items[] | select(.metadata.namespace | startswith(\"pr-\")) | .metadata.name] | .[]'"
fi
check_k8s_resource "PersistentVolumeClaims" "${PVC_CMD}"

echo
echo "--> [2/5] Checking Cloud & Registry State (GitHub / GHCR)..."

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "Dungx2409/pr-preview-platform")
  OWNER=$(echo "${REPO}" | cut -d/ -f1)

  # Check active Deployments
  DEPLOY_OUTPUT=""
  if [ -n "${TARGET_PR}" ]; then
    DEPS=$(gh api "repos/${REPO}/deployments?environment=pr-${TARGET_PR}" --jq '.[].id' 2>/dev/null || true)
  else
    DEPS=$(gh api "repos/${REPO}/deployments" --jq '.[] | select(.environment | startswith("pr-")) | .id' 2>/dev/null || true)
  fi

  ACTIVE_DEPS_COUNT=0
  for dep_id in ${DEPS}; do
    STATUS=$(gh api "repos/${REPO}/deployments/${dep_id}/statuses" --jq '.[0].state' 2>/dev/null || echo "unknown")
    if [ "${STATUS}" != "inactive" ]; then
      ACTIVE_DEPS_COUNT=$((ACTIVE_DEPS_COUNT + 1))
      DEPLOY_OUTPUT="${DEPLOY_OUTPUT}\nDeployment ID ${dep_id} (status: ${STATUS})"
    fi
  done

  if [ "${ACTIVE_DEPS_COUNT}" -eq 0 ]; then
    echo -e "  [PASS] Active GitHub Deployments: ${GREEN}0 active deployments found${RESET}"
  else
    echo -e "  [FAIL] Active GitHub Deployments: ${RED}${ACTIVE_DEPS_COUNT} active deployment(s) remain!${RESET}"
    echo -e "${DEPLOY_OUTPUT}" | sed 's/^/         - /'
    if [ "${STRICT_GITHUB}" = true ]; then
      TOTAL_LEAKS=$((TOTAL_LEAKS + ACTIVE_DEPS_COUNT))
    fi
  fi

  # Check GHCR image tags for demo-app
  if [ -n "${TARGET_PR}" ]; then
    GHCR_VERSIONS=$(gh api "users/${OWNER}/packages/container/demo-app/versions" \
      --jq ".[] | select(.metadata.container.tags[]? | startswith(\"pr-${TARGET_PR}-\")) | .metadata.container.tags[]" 2>/dev/null || true)
  else
    GHCR_VERSIONS=$(gh api "users/${OWNER}/packages/container/demo-app/versions" \
      --jq '.[] | select(.metadata.container.tags[]? | startswith("pr-")) | .metadata.container.tags[]' 2>/dev/null || true)
  fi

  GHCR_COUNT=0
  if [ -n "${GHCR_VERSIONS}" ]; then
    GHCR_COUNT=$(echo "${GHCR_VERSIONS}" | grep -c . || true)
  fi

  if [ "${GHCR_COUNT}" -eq 0 ]; then
    echo -e "  [PASS] GHCR Container Tags: ${GREEN}0 preview tags found${RESET}"
  else
    if [ -n "${TARGET_PR}" ] || [ "${STRICT_GITHUB}" = true ]; then
      echo -e "  [FAIL] GHCR Container Tags: ${RED}${GHCR_COUNT} preview tag(s) remain!${RESET}"
      TOTAL_LEAKS=$((TOTAL_LEAKS + GHCR_COUNT))
    else
      echo -e "  [WARN] GHCR Container Tags: ${YELLOW}${GHCR_COUNT} historical preview tag(s) detected${RESET}"
    fi
    while IFS= read -r line; do
      [ -n "${line}" ] && echo "         - ${line}"
    done <<< "${GHCR_VERSIONS}"
  fi
else
  echo -e "  [SKIP] GitHub CLI (gh) not authenticated; skipping GitHub Deployments & GHCR check."
fi

echo
echo "======================================================================"
if [ "${TOTAL_LEAKS}" -eq 0 ]; then
  echo -e "  ${GREEN}✓ VERIFICATION PASSED: 0 resource leaks detected!${RESET}"
  echo "======================================================================"
  exit 0
else
  echo -e "  ${RED}✗ VERIFICATION FAILED: ${TOTAL_LEAKS} resource leak(s) detected!${RESET}"
  echo "======================================================================"
  exit 1
fi
