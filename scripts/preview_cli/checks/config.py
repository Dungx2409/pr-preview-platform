"""Configuration health checks (values.yaml, manifest sync, workflow variables)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from scripts.preview_cli.checks import CheckResult
from scripts.preview_cli.util import load_values_config, run_command

# RFC 1123 label regex
DNS_LABEL_REGEX = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
# GitHub HTTPS repo URL regex
GITHUB_HTTPS_REGEX = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$")
# GHCR image format regex: ghcr.io/owner/package
GHCR_IMAGE_REGEX = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+$")


def _extract_workflow_tailnet(workflow_path: Path) -> str | None:
    if not workflow_path.exists():
        return None
    content = workflow_path.read_text(encoding="utf-8")
    m = re.search(r"(?m)^[ \t]*TAILNET_NAME:\s*([^\s\n#]+)", content)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return None


def check_config(repo_root: Path) -> list[CheckResult]:
    """Validate values.yaml, manifest synchronization, and workflow tailnet config."""
    results: list[CheckResult] = []
    values_path = repo_root / "values.yaml"

    if not values_path.exists():
        results.append(
            CheckResult(
                id="config.values_yaml",
                title="Root values.yaml existence",
                status="FAIL",
                message="values.yaml does not exist in repository root",
                fix="Run 'make init' to generate configuration from defaults",
            )
        )
        return results

    cfg = load_values_config(repo_root)
    if not cfg:
        results.append(
            CheckResult(
                id="config.values_yaml",
                title="Root values.yaml format",
                status="FAIL",
                message="values.yaml could not be parsed as valid YAML",
                fix="Ensure values.yaml syntax is valid YAML",
            )
        )
        return results

    results.append(
        CheckResult(
            id="config.values_yaml",
            title="Root values.yaml format",
            status="PASS",
            message="values.yaml parses cleanly",
        )
    )

    # 1. repo.url
    repo_url = cfg.get("repo", {}).get("url", "")
    if repo_url and GITHUB_HTTPS_REGEX.match(repo_url):
        results.append(
            CheckResult(
                id="config.repo_url",
                title="Repository URL (repo.url)",
                status="PASS",
                message=f"Valid GitHub HTTPS URL: {repo_url}",
            )
        )
    else:
        results.append(
            CheckResult(
                id="config.repo_url",
                title="Repository URL (repo.url)",
                status="FAIL",
                message=f"Invalid or missing repo.url: '{repo_url}'",
                fix="Set repo.url in values.yaml to 'https://github.com/<owner>/<repo>.git'",
            )
        )

    # 2. app.image
    app_image = cfg.get("app", {}).get("image", "")
    if app_image and GHCR_IMAGE_REGEX.match(app_image.lower()):
        results.append(
            CheckResult(
                id="config.app_image",
                title="Application Container Image (app.image)",
                status="PASS",
                message=f"Valid GHCR repository image: {app_image}",
            )
        )
    else:
        results.append(
            CheckResult(
                id="config.app_image",
                title="Application Container Image (app.image)",
                status="FAIL",
                message=f"app.image must start with 'ghcr.io/' and be lowercase: '{app_image}'",
                fix="Set app.image in values.yaml to 'ghcr.io/<owner>/<app-name>'",
            )
        )

    # 3. app.port
    app_port = cfg.get("app", {}).get("port")
    if isinstance(app_port, int) and 1 <= app_port <= 65535:
        results.append(
            CheckResult(
                id="config.app_port",
                title="Application Port (app.port)",
                status="PASS",
                message=f"Valid port number: {app_port}",
            )
        )
    else:
        results.append(
            CheckResult(
                id="config.app_port",
                title="Application Port (app.port)",
                status="FAIL",
                message=f"app.port must be an integer between 1 and 65535, got: {app_port}",
                fix="Set app.port in values.yaml (e.g. 8000)",
            )
        )

    # 4. app.healthcheck
    healthcheck = cfg.get("app", {}).get("healthcheck", "")
    if isinstance(healthcheck, str) and healthcheck.startswith("/"):
        results.append(
            CheckResult(
                id="config.healthcheck",
                title="Healthcheck endpoint (app.healthcheck)",
                status="PASS",
                message=f"Valid probe path: {healthcheck}",
            )
        )
    else:
        results.append(
            CheckResult(
                id="config.healthcheck",
                title="Healthcheck endpoint (app.healthcheck)",
                status="FAIL",
                message=f"app.healthcheck must start with '/', got: '{healthcheck}'",
                fix="Set app.healthcheck in values.yaml (e.g. '/healthz')",
            )
        )

    # 5. namespace.prefix
    ns_prefix = cfg.get("namespace", {}).get("prefix", "")
    if ns_prefix and len(ns_prefix) <= 63 and DNS_LABEL_REGEX.match(ns_prefix):
        results.append(
            CheckResult(
                id="config.namespace_prefix",
                title="Namespace prefix (namespace.prefix)",
                status="PASS",
                message=f"Valid RFC 1123 DNS label: '{ns_prefix}'",
            )
        )
    else:
        results.append(
            CheckResult(
                id="config.namespace_prefix",
                title="Namespace prefix (namespace.prefix)",
                status="FAIL",
                message=f"Invalid DNS label for namespace.prefix: '{ns_prefix}'",
                fix="Use lowercase alphanumeric characters and hyphens only (max 63 chars)",
            )
        )

    # 6. Manifest sync check (reuse existing check-config logic)
    sync_script = repo_root / "scripts" / "sync-config.py"
    if sync_script.exists():
        try:
            res = run_command(
                [sys.executable, str(sync_script), "--check"],
                timeout=10.0,
            )
            if res.returncode == 0:
                results.append(
                    CheckResult(
                        id="config.manifest_sync",
                        title="Manifest synchronization",
                        status="PASS",
                        message="Argo CD manifests are synchronized with values.yaml",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        id="config.manifest_sync",
                        title="Manifest synchronization",
                        status="FAIL",
                        message="Argo CD manifests are out of sync with values.yaml",
                        fix="Run 'make sync-config'",
                    )
                )
        except Exception as e:
            results.append(
                CheckResult(
                    id="config.manifest_sync",
                    title="Manifest synchronization",
                    status="FAIL",
                    message=f"Check-config failed: {e}",
                    fix="Run 'make sync-config'",
                )
            )

    # 7. TAILNET_NAME in preview.yml and preview-closed.yml
    preview_wf = repo_root / ".github" / "workflows" / "preview.yml"
    preview_closed_wf = repo_root / ".github" / "workflows" / "preview-closed.yml"

    ts_preview = _extract_workflow_tailnet(preview_wf)
    ts_closed = _extract_workflow_tailnet(preview_closed_wf)
    ts_values = cfg.get("tailnet", {}).get("name", "")

    placeholders = {"<tailnet-name>.ts.net", "change_me", "example.ts.net", ""}
    is_placeholder = (
        not ts_preview
        or ts_preview.lower() in placeholders
        or "<" in ts_preview
        or ">" in ts_preview
    )

    if not ts_preview or not ts_closed:
        results.append(
            CheckResult(
                id="config.workflow_tailnet",
                title="Workflow TAILNET_NAME variable",
                status="FAIL",
                message=(
                    f"TAILNET_NAME missing: preview.yml={ts_preview!r}, "
                    f"preview-closed.yml={ts_closed!r}"
                ),
                fix="Run 'make init' or configure 'env.TAILNET_NAME' in both workflows",
            )
        )
    elif is_placeholder:
        results.append(
            CheckResult(
                id="config.workflow_tailnet",
                title="Workflow TAILNET_NAME variable",
                status="FAIL",
                message=f"TAILNET_NAME is set to a placeholder: '{ts_preview}'",
                fix="Run 'make init' to set your real Tailscale tailnet domain (e.g. xyz.ts.net)",
            )
        )
    elif ts_preview != ts_closed:
        results.append(
            CheckResult(
                id="config.workflow_tailnet",
                title="Workflow TAILNET_NAME variable",
                status="FAIL",
                message=(
                    f"TAILNET_NAME mismatch between workflows: "
                    f"preview.yml='{ts_preview}' vs preview-closed.yml='{ts_closed}'"
                ),
                fix="Run 'make init' to synchronize tailnet across workflows",
            )
        )
    elif ts_values and ts_preview != ts_values:
        results.append(
            CheckResult(
                id="config.workflow_tailnet",
                title="Workflow TAILNET_NAME variable",
                status="WARN",
                message=(
                    f"Workflow TAILNET_NAME ('{ts_preview}') differs from values.yaml "
                    f"tailnet.name ('{ts_values}')"
                ),
                fix="Run 'make init' to align values.yaml and workflow tailnet settings",
            )
        )
    else:
        results.append(
            CheckResult(
                id="config.workflow_tailnet",
                title="Workflow TAILNET_NAME variable",
                status="PASS",
                message=f"Consistent tailnet configured across workflows: '{ts_preview}'",
            )
        )

    return results
