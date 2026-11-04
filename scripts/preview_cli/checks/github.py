"""GitHub token, repository access, label, and permission checks."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from scripts.preview_cli.checks import CheckResult
from scripts.preview_cli.util import (
    DEFAULT_SECRETS_DIR,
    load_values_config,
    parse_simple_yaml,
    redact_secrets,
)


def _get_github_token(secrets_dir: Path) -> str | None:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip()
    token_file = secrets_dir / "github-token.yaml"
    if token_file.exists():
        try:
            cfg = parse_simple_yaml(token_file.read_text(encoding="utf-8"))
            data = cfg.get("stringData") or cfg.get("data") or {}
            tok = data.get("token")
            if tok:
                return str(tok).strip()
        except Exception:
            return None
    return None


def _parse_repo_coords(repo_url: str) -> tuple[str, str] | None:
    # Matches https://github.com/owner/repo or .git
    clean = repo_url.strip().removesuffix(".git")
    if "github.com/" in clean:
        parts = clean.split("github.com/", 1)[1].split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None


def check_github(
    repo_root: Path,
    offline: bool = False,
    secrets_dir: Path | None = None,
) -> list[CheckResult]:
    """Verify GitHub token validity, repository permissions, preview label, and rate limits."""
    results: list[CheckResult] = []
    target_secrets_dir = secrets_dir or DEFAULT_SECRETS_DIR

    if offline:
        results.append(
            CheckResult(
                id="github.offline",
                title="GitHub API preflight",
                status="SKIP",
                message="Offline mode enabled (--offline); skipping remote GitHub API calls",
            )
        )
        return results

    token = _get_github_token(target_secrets_dir)
    if not token:
        results.append(
            CheckResult(
                id="github.token",
                title="GitHub API token",
                status="FAIL",
                message="GitHub access token not found in GITHUB_TOKEN or github-token.yaml",
                fix="Set GITHUB_TOKEN environment variable or run 'make init'",
            )
        )
        return results

    cfg = load_values_config(repo_root)
    repo_url = cfg.get("repo", {}).get("url", "")
    coords = _parse_repo_coords(repo_url)
    if not coords:
        results.append(
            CheckResult(
                id="github.repo_access",
                title="GitHub repository target",
                status="FAIL",
                message=f"Could not parse GitHub owner/repo from repo.url: '{repo_url}'",
                fix="Configure a valid GitHub HTTPS repo URL in values.yaml",
            )
        )
        return results

    owner, repo_name = coords
    rate_remaining = -1

    def make_gh_request(endpoint: str) -> tuple[int, dict, dict]:
        url = f"https://api.github.com{endpoint}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "pr-preview-platform/1.0",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                status = resp.status
                headers = dict(resp.headers)
                body = json.loads(resp.read().decode("utf-8"))
                return status, headers, body
        except urllib.error.HTTPError as err:
            err_headers = dict(err.headers)
            try:
                err_body = json.loads(err.read().decode("utf-8"))
            except Exception:
                err_body = {}
            return err.code, err_headers, err_body
        except Exception as exc:
            raise RuntimeError(redact_secrets(str(exc), [token])) from exc

    # 1. Token validation: GET /user
    try:
        status, headers, body = make_gh_request("/user")
        rate_str = headers.get("x-ratelimit-remaining", "-1")
        if rate_str.isdigit():
            rate_remaining = int(rate_str)

        if status == 200:
            login = body.get("login", "unknown")
            results.append(
                CheckResult(
                    id="github.token",
                    title="GitHub token authentication",
                    status="PASS",
                    message=f"Authenticated as @{login}",
                )
            )
        else:
            msg = body.get("message", "Authentication failed")
            results.append(
                CheckResult(
                    id="github.token",
                    title="GitHub token authentication",
                    status="FAIL",
                    message=f"HTTP {status}: {redact_secrets(msg, [token])}",
                    fix="Provide a valid GitHub Personal Access Token (PAT) with repo scope",
                )
            )
            return results
    except Exception as exc:
        results.append(
            CheckResult(
                id="github.token",
                title="GitHub token authentication",
                status="FAIL",
                message=f"Connection error: {redact_secrets(str(exc), [token])}",
                fix="Check network connection or GitHub API status",
            )
        )
        return results

    # 2. Repo access: GET /repos/{owner}/{repo}
    try:
        status, headers, body = make_gh_request(f"/repos/{owner}/{repo_name}")
        rate_str = headers.get("x-ratelimit-remaining", "-1")
        if rate_str.isdigit():
            rate_remaining = int(rate_str)

        if status == 200:
            full_name = body.get("full_name", f"{owner}/{repo_name}")
            results.append(
                CheckResult(
                    id="github.repo_access",
                    title="Repository access",
                    status="PASS",
                    message=f"Access verified to repository {full_name}",
                )
            )
        else:
            results.append(
                CheckResult(
                    id="github.repo_access",
                    title="Repository access",
                    status="FAIL",
                    message=f"Cannot access repository {owner}/{repo_name} (HTTP {status})",
                    fix=f"Verify token has read access to https://github.com/{owner}/{repo_name}",
                )
            )
            return results
    except Exception as exc:
        results.append(
            CheckResult(
                id="github.repo_access",
                title="Repository access",
                status="FAIL",
                message=f"Repo check error: {redact_secrets(str(exc), [token])}",
                fix=f"Verify token has read access to https://github.com/{owner}/{repo_name}",
            )
        )
        return results

    # 3. Label 'preview' check
    try:
        status, headers, _ = make_gh_request(f"/repos/{owner}/{repo_name}/labels/preview")
        rate_str = headers.get("x-ratelimit-remaining", "-1")
        if rate_str.isdigit():
            rate_remaining = int(rate_str)

        if status == 200:
            results.append(
                CheckResult(
                    id="github.preview_label",
                    title="Preview trigger label",
                    status="PASS",
                    message="Label 'preview' exists on target repository",
                )
            )
        else:
            results.append(
                CheckResult(
                    id="github.preview_label",
                    title="Preview trigger label",
                    status="FAIL",
                    message=f"Label 'preview' not found in {owner}/{repo_name}",
                    fix=f"Create label 'preview' at https://github.com/{owner}/{repo_name}/labels",
                )
            )
    except Exception as exc:
        results.append(
            CheckResult(
                id="github.preview_label",
                title="Preview trigger label",
                status="FAIL",
                message=f"Label check error: {redact_secrets(str(exc), [token])}",
                fix=f"Create label 'preview' at https://github.com/{owner}/{repo_name}/labels",
            )
        )

    # 4. Workflow permissions check: GET /repos/{owner}/{repo}/actions/permissions
    try:
        status, headers, body = make_gh_request(f"/repos/{owner}/{repo_name}/actions/permissions")
        rate_str = headers.get("x-ratelimit-remaining", "-1")
        if rate_str.isdigit():
            rate_remaining = int(rate_str)

        if status == 200:
            results.append(
                CheckResult(
                    id="github.workflow_permissions",
                    title="Workflow permissions",
                    status="PASS",
                    message="GitHub Actions workflow permissions accessible",
                )
            )
        elif status in (401, 403):
            results.append(
                CheckResult(
                    id="github.workflow_permissions",
                    title="Workflow permissions",
                    status="WARN",
                    message="Cannot verify workflow permissions via API (admin token required)",
                    fix=(
                        f"Check manually: https://github.com/{owner}/{repo_name}/settings/actions "
                        "-> Workflow permissions -> select 'Read and write permissions' and check "
                        "'Allow GitHub Actions to create and approve pull requests'"
                    ),
                )
            )
        else:
            results.append(
                CheckResult(
                    id="github.workflow_permissions",
                    title="Workflow permissions",
                    status="WARN",
                    message=f"GitHub Actions permissions returned HTTP {status}",
                    fix=f"Check settings at https://github.com/{owner}/{repo_name}/settings/actions",
                )
            )
    except Exception as exc:
        results.append(
            CheckResult(
                id="github.workflow_permissions",
                title="Workflow permissions",
                status="WARN",
                message=f"Workflow check note: {redact_secrets(str(exc), [token])}",
                fix=f"Verify actions settings at https://github.com/{owner}/{repo_name}/settings/actions",
            )
        )

    # 5. Rate limit sanity check
    if rate_remaining >= 0:
        if rate_remaining < 20:
            results.append(
                CheckResult(
                    id="github.rate_limit",
                    title="GitHub API rate limit remaining",
                    status="WARN",
                    message=f"Low rate limit remaining: {rate_remaining} calls left",
                    fix="Wait for rate limit window reset or use an authenticated token",
                )
            )
        else:
            results.append(
                CheckResult(
                    id="github.rate_limit",
                    title="GitHub API rate limit remaining",
                    status="PASS",
                    message=f"Healthy rate limit: {rate_remaining} remaining",
                )
            )

    return results
