#!/usr/bin/env bash
# scripts/golden-check.sh - Enforce backward-compatible byte-identical Helm template rendering
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GOLDEN_FILE="${REPO_ROOT}/tests/golden/helm-template-default.yaml"
CHART_DIR="${REPO_ROOT}/charts/app"

if ! command -v helm >/dev/null 2>&1; then
    echo "Error: helm is not installed or not available in PATH." >&2
    exit 1
fi

if [[ ! -f "${GOLDEN_FILE}" ]]; then
    echo "Error: Golden baseline file not found: ${GOLDEN_FILE}" >&2
    exit 1
fi

if [[ ! -d "${CHART_DIR}" ]]; then
    echo "Error: Chart directory not found: ${CHART_DIR}" >&2
    exit 1
fi

echo "Verifying helm template test-app charts/app against golden baseline..."

TMP_RENDER="$(mktemp)"
trap 'rm -f "${TMP_RENDER}"' EXIT

helm template test-app "${CHART_DIR}" > "${TMP_RENDER}"

if diff -u "${GOLDEN_FILE}" "${TMP_RENDER}"; then
    echo "✓ Helm template output is byte-identical to golden baseline."
    exit 0
else
    echo "✗ Golden check failed: rendered template diverged from ${GOLDEN_FILE}" >&2
    echo "This check enforces that single-service default rendering remains byte-identical." >&2
    echo "If this change is intentional, re-render and update ${GOLDEN_FILE}." >&2
    exit 1
fi
