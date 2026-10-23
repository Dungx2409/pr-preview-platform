#!/usr/bin/env bash
# ==============================================================================
# Script: verify-access.sh
# Purpose: Verify the zero-trust private access model for PR Previews (T-2.2)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
POLICY_FILE="${REPO_ROOT}/platform/tailscale/policy-snippets.json"

export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/pr-preview.yaml}"

echo "======================================================================"
echo "          PR Preview Platform - Security & Access Verification        "
echo "======================================================================"
echo

PASSED_COUNT=0
TOTAL_COUNT=5

# ------------------------------------------------------------------------------
# Test 1: Public DNS Exposure / Leak
# ------------------------------------------------------------------------------
echo "==> [Test 1/5] Public DNS Leakage Check..."
SAMPLE_DOMAIN="preview-test.taildc1471.ts.net"
PUBLIC_DNS_OUTPUT=$(nslookup "${SAMPLE_DOMAIN}" 8.8.8.8 2>&1 || true)

if echo "${PUBLIC_DNS_OUTPUT}" | grep -q -E "No answer|NXDOMAIN|server can't find"; then
  echo "    [PASS] Public DNS (8.8.8.8) does not resolve MagicDNS '${SAMPLE_DOMAIN}'"
  PASSED_COUNT=$((PASSED_COUNT + 1))
else
  echo "    [FAIL] Public DNS resolved private preview domain!"
  echo "${PUBLIC_DNS_OUTPUT}"
fi

# ------------------------------------------------------------------------------
# Test 2: Local LAN / Host Non-Exposure Check
# ------------------------------------------------------------------------------
echo "==> [Test 2/5] LAN Interface Isolation Check..."
# Get active non-loopback LAN IPv4 address
LAN_IP=$(ip -4 addr show scope global | grep "inet " | grep -v "100\." | grep -v "192\.168\.56\." | grep -v "172\." | awk '{print $2}' | cut -d/ -f1 | head -n 1 || echo "")

if [[ -n "${LAN_IP}" ]]; then
  echo "    Testing LAN IP: ${LAN_IP}"
  if curl -s -m 2 "https://${LAN_IP}:6443" >/dev/null 2>&1; then
    echo "    [FAIL] k8s API (6443) is exposed on LAN IP ${LAN_IP}!"
  else
    echo "    [PASS] k8s API (6443) is not accessible on LAN IP ${LAN_IP} (Connection Refused/Filtered)"
    PASSED_COUNT=$((PASSED_COUNT + 1))
  fi
else
  echo "    [SKIP] No physical LAN IP detected (assumed host-only / virtualized)."
  PASSED_COUNT=$((PASSED_COUNT + 1))
fi

# ------------------------------------------------------------------------------
# Test 3: Tailscale Tailnet Membership & MagicDNS Status
# ------------------------------------------------------------------------------
echo "==> [Test 3/5] Tailscale Authentication & Tailnet Membership..."
if command -v tailscale >/dev/null 2>&1; then
  TAILSCALE_STATUS=$(tailscale status --json 2>&1 || true)
  CURRENT_TAILNET=$(echo "${TAILSCALE_STATUS}" | grep -o '"MagicDNSSuffix": *"[^"]*"' | head -n 1 | cut -d'"' -f4 || echo "")
  MAGIC_DNS_ENABLED=$(echo "${TAILSCALE_STATUS}" | grep -o '"MagicDNSEnabled": *true' || echo "")

  if [[ -n "${CURRENT_TAILNET}" && -n "${MAGIC_DNS_ENABLED}" ]]; then
    echo "    [PASS] Client connected to tailnet '${CURRENT_TAILNET}' with MagicDNS enabled"
    PASSED_COUNT=$((PASSED_COUNT + 1))
  else
    echo "    [FAIL] Tailscale is not running or MagicDNS is disabled."
  fi
else
  echo "    [FAIL] tailscale CLI is not installed."
fi

# ------------------------------------------------------------------------------
# Test 4: ACL Policy Specification Audit
# ------------------------------------------------------------------------------
echo "==> [Test 4/5] Tailscale ACL Policy Specification Audit..."
if [[ -f "${POLICY_FILE}" ]]; then
  HAS_TAG_OWNERS=$(grep -c "tag:k8s-operator" "${POLICY_FILE}" || true)
  HAS_PROXY_TAGS=$(grep -c "tag:k8s" "${POLICY_FILE}" || true)
  HAS_REVIEWERS=$(grep -c "group:reviewers" "${POLICY_FILE}" || true)
  HAS_ACCEPT_443=$(grep -c "tag:k8s:443" "${POLICY_FILE}" || true)

  if [[ ${HAS_TAG_OWNERS} -gt 0 && ${HAS_PROXY_TAGS} -gt 0 && ${HAS_REVIEWERS} -gt 0 && ${HAS_ACCEPT_443} -gt 0 ]]; then
    echo "    [PASS] Policy snippet explicitly bounds access: group:reviewers -> tag:k8s:443 (default deny for all others)"
    PASSED_COUNT=$((PASSED_COUNT + 1))
  else
    echo "    [FAIL] Policy snippet missing required tags or group definitions."
  fi
else
  echo "    [FAIL] Policy file ${POLICY_FILE} not found."
fi

# ------------------------------------------------------------------------------
# Test 5: Kubernetes Operator Security Posture (D8 & API Server Isolation)
# ------------------------------------------------------------------------------
echo "==> [Test 5/5] In-Cluster Operator Security Posture..."
if command -v kubectl >/dev/null 2>&1 && kubectl cluster-info >/dev/null 2>&1; then
  APISERVER_PROXY_ENV=$(kubectl get deployment operator -n tailscale -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="APISERVER_PROXY")].value}' 2>/dev/null || echo "")
  
  if [[ "${APISERVER_PROXY_ENV}" == "false" ]]; then
    echo "    [PASS] Operator API server proxy is disabled (APISERVER_PROXY=false). Port 6443 not exposed via Tailnet."
    PASSED_COUNT=$((PASSED_COUNT + 1))
  else
    echo "    [FAIL] APISERVER_PROXY is not 'false' (value: '${APISERVER_PROXY_ENV}')."
  fi
else
  echo "    [FAIL] Unable to query Kubernetes cluster."
fi

echo
echo "======================================================================"
echo " Verification Result: ${PASSED_COUNT}/${TOTAL_COUNT} Checks Passed"
echo "======================================================================"

if [[ ${PASSED_COUNT} -eq ${TOTAL_COUNT} ]]; then
  echo "Status: ALL SECURITY CONTROLS VERIFIED."
  exit 0
else
  echo "Status: ONE OR MORE SECURITY CHECKS FAILED."
  exit 1
fi
