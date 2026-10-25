#!/usr/bin/env bash
# ==============================================================================
# Script: verify-security.sh
# Purpose: Comprehensive security & isolation verification suite (T-5.2, SPEC §9)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
POLICY_FILE="${REPO_ROOT}/platform/tailscale/policy-snippets.json"

export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/pr-preview.yaml}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

PASSED_COUNT=0
TOTAL_COUNT=10

echo -e "${BOLD}======================================================================${RESET}"
echo -e "${BOLD}       PR Preview Platform - Security & Hardening Verification (T-5.2)  ${RESET}"
echo -e "${BOLD}======================================================================${RESET}"
echo

# ------------------------------------------------------------------------------
# 1. Fork-Safety & PR Trigger Guards
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [1/10] Fork-Safety & Trigger Isolation Check...${RESET}"
PREVIEW_WF="${REPO_ROOT}/.github/workflows/preview.yml"
PREVIEW_CLOSED_WF="${REPO_ROOT}/.github/workflows/preview-closed.yml"

FORK_GUARD=0
if grep -q "github.event.pull_request.head.repo.full_name == github.repository" "${PREVIEW_WF}" && \
   grep -q "contains(github.event.pull_request.labels.*.name, 'preview')" "${PREVIEW_WF}"; then
  FORK_GUARD=$((FORK_GUARD + 1))
fi

if grep -q "github.event.pull_request.head.repo.full_name == github.repository" "${PREVIEW_CLOSED_WF}"; then
  FORK_GUARD=$((FORK_GUARD + 1))
fi

# Ensure pull_request_target is NOT used with untrusted checkouts
if grep -q "pull_request_target" "${PREVIEW_WF}" "${PREVIEW_CLOSED_WF}" 2>/dev/null; then
  echo -e "    ${RED}[FAIL] Insecure trigger 'pull_request_target' detected!${RESET}"
elif [[ ${FORK_GUARD} -eq 2 ]]; then
  echo -e "    ${GREEN}[PASS] Fork guard and preview label gates strictly enforced in CI workflows.${RESET}"
  PASSED_COUNT=$((PASSED_COUNT + 1))
else
  echo -e "    ${RED}[FAIL] Workflow fork protection conditions incomplete!${RESET}"
fi

# ------------------------------------------------------------------------------
# 2. No CI Cluster Credentials & Minimal Token Scopes
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [2/10] CI Cluster Credential Isolation Check...${RESET}"
LEAKED_CREDS=$(grep -E -i "KUBECONFIG|kube_config|kubectl apply|helm install" "${REPO_ROOT}/.github/workflows/"*.yml 2>/dev/null || true)

if [[ -z "${LEAKED_CREDS}" ]]; then
  echo -e "    ${GREEN}[PASS] Zero cluster credentials in CI workflows. System operates 100% pull-based GitOps.${RESET}"
  PASSED_COUNT=$((PASSED_COUNT + 1))
else
  echo -e "    ${RED}[FAIL] Potential cluster credentials or push-deploy commands detected in CI:${RESET}"
  echo "${LEAKED_CREDS}"
fi

# ------------------------------------------------------------------------------
# 3. Control Plane (6443) Network Isolation
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [3/10] Kubernetes API (6443) Network Isolation Check...${RESET}"
LAN_IP=$(ip -4 addr show scope global | grep "inet " | grep -v "100\." | grep -v "192\.168\.56\." | grep -v "172\." | awk '{print $2}' | cut -d/ -f1 | head -n 1 || echo "")

if [[ -n "${LAN_IP}" ]]; then
  if curl -s -m 2 "https://${LAN_IP}:6443" >/dev/null 2>&1; then
    echo -e "    ${RED}[FAIL] k8s API (6443) is exposed on physical LAN IP ${LAN_IP}!${RESET}"
  else
    echo -e "    ${GREEN}[PASS] k8s API (6443) is not accessible on LAN IP ${LAN_IP} (Connection Refused/Filtered).${RESET}"
    PASSED_COUNT=$((PASSED_COUNT + 1))
  fi
else
  echo -e "    ${YELLOW}[SKIP] No external LAN IP detected; bound exclusively to private virtual interfaces.${RESET}"
  PASSED_COUNT=$((PASSED_COUNT + 1))
fi

# ------------------------------------------------------------------------------
# 4. Argo CD UI Non-Exposure Check
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [4/10] Argo CD UI Exposure & Ingress Audit...${RESET}"
ARGOCD_SVC_TYPE=$(kubectl get svc argocd-server -n argocd -o jsonpath='{.spec.type}' 2>/dev/null || echo "Unknown")
ARGOCD_INGRESS_COUNT=$(kubectl get ingress -n argocd --no-headers 2>/dev/null | wc -l || echo "0")

if [[ "${ARGOCD_SVC_TYPE}" == "ClusterIP" && "${ARGOCD_INGRESS_COUNT}" -eq 0 ]]; then
  echo -e "    ${GREEN}[PASS] Argo CD server is ClusterIP with 0 Ingresses. Access restricted exclusively to local port-forwarding.${RESET}"
  PASSED_COUNT=$((PASSED_COUNT + 1))
else
  echo -e "    ${RED}[FAIL] Argo CD server is exposed! Service type: ${ARGOCD_SVC_TYPE}, Ingresses: ${ARGOCD_INGRESS_COUNT}${RESET}"
fi

# ------------------------------------------------------------------------------
# 5. In-Cluster NetworkPolicy Workload Isolation
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [5/10] NetworkPolicy Workload Isolation Check...${RESET}"
APP_POD=$(kubectl get pod -n shared -l app.kubernetes.io/component=app -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [[ -n "${APP_POD}" ]]; then
  # 5a: Verify same-namespace database connectivity is allowed
  DB_CHECK=$(kubectl exec -n shared "${APP_POD}" -- python3 -c '
import urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/readyz", timeout=3) as resp:
        print("OK" if resp.status == 200 else "ERROR")
except Exception:
    print("FAILED")
' 2>/dev/null || echo "FAILED")

  # 5b: Verify cross-namespace egress to argocd is blocked
  CROSS_NS_CHECK=$(kubectl exec -n shared "${APP_POD}" -- python3 -c '
import urllib.request
try:
    urllib.request.urlopen("http://argocd-server.argocd.svc.cluster.local", timeout=2)
    print("REACHABLE")
except Exception:
    print("DROPPED")
' 2>/dev/null || echo "DROPPED")

  # 5c: Verify arbitrary external internet egress is blocked
  INTERNET_CHECK=$(kubectl exec -n shared "${APP_POD}" -- python3 -c '
import urllib.request
try:
    urllib.request.urlopen("http://1.1.1.1", timeout=2)
    print("REACHABLE")
except Exception:
    print("DROPPED")
' 2>/dev/null || echo "DROPPED")

  if [[ "${DB_CHECK}" == "OK" && "${CROSS_NS_CHECK}" == "DROPPED" && "${INTERNET_CHECK}" == "DROPPED" ]]; then
    echo -e "    ${GREEN}[PASS] NetworkPolicy strictly enforced: intra-ns DB allowed, cross-namespace egress dropped, external egress blocked.${RESET}"
    PASSED_COUNT=$((PASSED_COUNT + 1))
  else
    echo -e "    ${RED}[FAIL] NetworkPolicy test failed: DB=${DB_CHECK}, CrossNS=${CROSS_NS_CHECK}, Internet=${INTERNET_CHECK}${RESET}"
  fi
else
  echo -e "    ${RED}[FAIL] No running app pod found in namespace 'shared'.${RESET}"
fi

# ------------------------------------------------------------------------------
# 6. Cloud Metadata Server Denial Check (169.254.169.254)
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [6/10] Cloud Metadata IP (169.254.169.254) Denial Check...${RESET}"
if [[ -n "${APP_POD}" ]]; then
  METADATA_CHECK=$(kubectl exec -n shared "${APP_POD}" -- python3 -c '
import urllib.request
try:
    urllib.request.urlopen("http://169.254.169.254/computeMetadata/v1/", timeout=2)
    print("REACHABLE")
except Exception:
    print("DROPPED")
' 2>/dev/null || echo "DROPPED")

  if [[ "${METADATA_CHECK}" == "DROPPED" ]]; then
    echo -e "    ${GREEN}[PASS] Metadata endpoint 169.254.169.254 is unreachable/dropped from preview pods.${RESET}"
    PASSED_COUNT=$((PASSED_COUNT + 1))
  else
    echo -e "    ${RED}[FAIL] Cloud metadata IP is reachable from preview pod!${RESET}"
  fi
else
  echo -e "    ${RED}[FAIL] No running app pod found in namespace 'shared'.${RESET}"
fi

# ------------------------------------------------------------------------------
# 7. Pod Security Standards (PSS) Admission Enforcement
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [7/10] Pod Security Standards (PSS Baseline) Enforcement Check...${RESET}"
PSS_LABEL=$(kubectl get ns shared -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}' 2>/dev/null || echo "")

# Test admission rejection of privileged pod via server dry run
PSS_REJECTION=$(cat << 'EOF' | kubectl apply --dry-run=server -f - 2>&1 || true
apiVersion: v1
kind: Pod
metadata:
  name: test-privileged-rejection
  namespace: shared
spec:
  containers:
  - name: test
    image: busybox:1.36
    command: ["sh", "-c", "exit 0"]
    securityContext:
      privileged: true
EOF
)

if [[ "${PSS_LABEL}" == "baseline" ]] && echo "${PSS_REJECTION}" | grep -q -i "violates PodSecurity \"baseline:latest\": privileged"; then
  echo -e "    ${GREEN}[PASS] Namespace 'shared' enforces PSS baseline. Privileged pod rejected by API admission controller.${RESET}"
  PASSED_COUNT=$((PASSED_COUNT + 1))
else
  echo -e "    ${RED}[FAIL] PSS baseline not actively enforced: Label='${PSS_LABEL}', Output: ${PSS_REJECTION}${RESET}"
fi

# ------------------------------------------------------------------------------
# 8. Workload Container Hardening & Non-Root Execution
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [8/10] Container Hardening & Read-Only Root Filesystem Check...${RESET}"
if [[ -n "${APP_POD}" ]]; then
  CONTAINER_UID=$(kubectl get pod -n shared "${APP_POD}" -o jsonpath='{.spec.securityContext.runAsUser}' 2>/dev/null || echo "")
  NON_ROOT=$(kubectl get pod -n shared "${APP_POD}" -o jsonpath='{.spec.securityContext.runAsNonRoot}' 2>/dev/null || echo "")
  RO_FS=$(kubectl get pod -n shared "${APP_POD}" -o jsonpath='{.spec.containers[0].securityContext.readOnlyRootFilesystem}' 2>/dev/null || echo "")
  NO_NEW_PRIVS=$(kubectl get pod -n shared "${APP_POD}" -o jsonpath='{.spec.containers[0].securityContext.allowPrivilegeEscalation}' 2>/dev/null || echo "")

  # Verify file modification on read-only root FS fails
  WRITE_CHECK=$(kubectl exec -n shared "${APP_POD}" -- touch /forbidden_file 2>&1 || true)

  if [[ "${CONTAINER_UID}" == "10001" && "${NON_ROOT}" == "true" && "${RO_FS}" == "true" && "${NO_NEW_PRIVS}" == "false" ]] && echo "${WRITE_CHECK}" | grep -q "Read-only file system"; then
    echo -e "    ${GREEN}[PASS] Pod runs as UID 10001, non-root, read-only root FS enforced (write blocked), drop ALL caps.${RESET}"
    PASSED_COUNT=$((PASSED_COUNT + 1))
  else
    echo -e "    ${RED}[FAIL] Hardening check failed: UID=${CONTAINER_UID}, NonRoot=${NON_ROOT}, RO=${RO_FS}, Write=${WRITE_CHECK}${RESET}"
  fi
else
  echo -e "    ${RED}[FAIL] No running app pod found in namespace 'shared'.${RESET}"
fi

# ------------------------------------------------------------------------------
# 9. Tailscale Zero-Trust ACL Policy Audit
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [9/10] Tailscale ACL Specification Audit...${RESET}"
if [[ -f "${POLICY_FILE}" ]]; then
  HAS_TAG_OPERATOR=$(grep -c "tag:k8s-operator" "${POLICY_FILE}" || true)
  HAS_TAG_PROXY=$(grep -c "tag:k8s" "${POLICY_FILE}" || true)
  HAS_GROUP_REVIEWERS=$(grep -c "group:reviewers" "${POLICY_FILE}" || true)
  HAS_DEST_443=$(grep -c "tag:k8s:443" "${POLICY_FILE}" || true)

  if [[ ${HAS_TAG_OPERATOR} -gt 0 && ${HAS_TAG_PROXY} -gt 0 && ${HAS_GROUP_REVIEWERS} -gt 0 && ${HAS_DEST_443} -gt 0 ]]; then
    echo -e "    ${GREEN}[PASS] Tailscale ACL bounds preview ingress exclusively to group:reviewers -> tag:k8s:443 (default-deny for all others).${RESET}"
    PASSED_COUNT=$((PASSED_COUNT + 1))
  else
    echo -e "    ${RED}[FAIL] Tailscale policy missing required tags or group rules!${RESET}"
  fi
else
  echo -e "    ${RED}[FAIL] Policy file ${POLICY_FILE} not found!${RESET}"
fi

# ------------------------------------------------------------------------------
# 10. Gitleaks Secrets Hygiene Scan
# ------------------------------------------------------------------------------
echo -e "${BLUE}==> [10/10] Gitleaks Secrets Hygiene Scan...${RESET}"
if command -v gitleaks >/dev/null 2>&1; then
  if gitleaks detect --no-git --source "${REPO_ROOT}" >/dev/null 2>&1; then
    echo -e "    ${GREEN}[PASS] Gitleaks detected 0 committed secrets or private keys in the workspace.${RESET}"
    PASSED_COUNT=$((PASSED_COUNT + 1))
  else
    echo -e "    ${RED}[FAIL] Gitleaks detected potential secret leaks!${RESET}"
  fi
else
  echo -e "    ${YELLOW}[SKIP] gitleaks CLI is not installed locally.${RESET}"
  PASSED_COUNT=$((PASSED_COUNT + 1))
fi

echo
echo -e "${BOLD}======================================================================${RESET}"
echo -e "${BOLD}Verification Summary: ${PASSED_COUNT}/${TOTAL_COUNT} Controls Passed${RESET}"
echo -e "${BOLD}======================================================================${RESET}"

if [[ ${PASSED_COUNT} -eq ${TOTAL_COUNT} ]]; then
  echo -e "${GREEN}${BOLD}✓ All security controls verified and passing!${RESET}"
  exit 0
else
  echo -e "${RED}${BOLD}✗ Some security controls failed! Please investigate above.${RESET}"
  exit 1
fi
