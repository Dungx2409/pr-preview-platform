"""Secrets and credentials storage checks."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from scripts.preview_cli.checks import CheckResult
from scripts.preview_cli.util import DEFAULT_SECRETS_DIR, parse_simple_yaml


def _check_secret_yaml_keys(path: Path, expected_keys: list[str | list[str]]) -> tuple[bool, str]:
    if not path.exists():
        return False, f"File {path.name} not found"
    try:
        content = path.read_text(encoding="utf-8")
        parsed = parse_simple_yaml(content)
        data = parsed.get("stringData") or parsed.get("data") or {}
        missing: list[str] = []
        for item in expected_keys:
            if isinstance(item, list):
                if not any(k in data for k in item):
                    missing.append(f"({' or '.join(item)})")
            elif item not in data:
                missing.append(item)
        if missing:
            return False, f"{path.name} is missing keys: {', '.join(missing)}"
        return True, "Valid YAML with required keys"
    except Exception as e:
        return False, f"Could not parse {path.name}: {e}"


def check_secrets(secrets_dir: Path | None = None) -> list[CheckResult]:
    """Verify disaster recovery secrets directory permissions or environment variables."""
    results: list[CheckResult] = []
    target_dir = secrets_dir or DEFAULT_SECRETS_DIR

    # Check env vars first
    env_ts_id = os.environ.get("TS_OAUTH_CLIENT_ID")
    env_ts_secret = os.environ.get("TS_OAUTH_CLIENT_SECRET")
    env_gh_token = os.environ.get("GITHUB_TOKEN")
    env_db_pass = os.environ.get("PREVIEW_DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD")

    has_all_envs = bool(env_ts_id and env_ts_secret and env_gh_token)

    # Check directory
    dir_exists = target_dir.exists()
    if dir_exists:
        mode = stat.S_IMODE(target_dir.stat().st_mode)
        if mode == 0o700:
            results.append(
                CheckResult(
                    id="secrets.dir_permissions",
                    title="DR Secrets directory permissions",
                    status="PASS",
                    message=f"{target_dir} has secure permissions (0700)",
                )
            )
        else:
            results.append(
                CheckResult(
                    id="secrets.dir_permissions",
                    title="DR Secrets directory permissions",
                    status="FAIL",
                    message=f"{target_dir} mode is {oct(mode)} (expected 0700)",
                    fix=f"Run: chmod 700 {target_dir}",
                )
            )
    elif has_all_envs:
        results.append(
            CheckResult(
                id="secrets.dir_permissions",
                title="DR Secrets directory permissions",
                status="PASS",
                message=(f"Directory {target_dir} not found, but secrets provided via env vars"),
            )
        )
    else:
        results.append(
            CheckResult(
                id="secrets.dir_permissions",
                title="DR Secrets directory",
                status="FAIL",
                message=f"Secrets directory {target_dir} does not exist and env vars are not set",
                fix="Run 'make init' to generate disaster recovery secrets securely",
            )
        )
        return results

    # Files to verify
    secret_files: list[tuple[str, list[str | list[str]], str]] = [
        (
            "operator-oauth.yaml",
            ["client_id", "client_secret"],
            "Tailscale Operator OAuth credentials",
        ),
        ("github-token.yaml", ["token"], "GitHub access token"),
        (
            "shared-postgres.yaml",
            [["password", "POSTGRES_PASSWORD"]],
            "Shared PostgreSQL password",
        ),
    ]

    for fname, keys, desc in secret_files:
        fpath = target_dir / fname
        if fpath.exists():
            fmode = stat.S_IMODE(fpath.stat().st_mode)
            if fmode != 0o600:
                results.append(
                    CheckResult(
                        id=f"secrets.{fname.replace('.', '_')}",
                        title=desc,
                        status="FAIL",
                        message=f"{fname} has insecure permissions {oct(fmode)} (expected 0600)",
                        fix=f"Run: chmod 600 {fpath}",
                    )
                )
                continue

            valid, reason = _check_secret_yaml_keys(fpath, keys)
            if valid:
                results.append(
                    CheckResult(
                        id=f"secrets.{fname.replace('.', '_')}",
                        title=desc,
                        status="PASS",
                        message=f"{fname} present (0600) with required keys",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        id=f"secrets.{fname.replace('.', '_')}",
                        title=desc,
                        status="FAIL",
                        message=reason,
                        fix=f"Recreate {fname} using 'make init' or inspect manifest structure",
                    )
                )
        else:
            # Fall back to env var if file missing
            is_env_ok = False
            if fname == "operator-oauth.yaml" and env_ts_id and env_ts_secret:
                is_env_ok = True
            elif fname == "github-token.yaml" and env_gh_token:
                is_env_ok = True
            elif fname == "shared-postgres.yaml" and env_db_pass:
                is_env_ok = True

            if is_env_ok:
                results.append(
                    CheckResult(
                        id=f"secrets.{fname.replace('.', '_')}",
                        title=desc,
                        status="PASS",
                        message=f"{fname} not found, but credentials provided via env vars",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        id=f"secrets.{fname.replace('.', '_')}",
                        title=desc,
                        status="FAIL",
                        message=f"Missing {fname} in {target_dir} and env vars not set",
                        fix=f"Run 'make init' to create {fname} or set environment variables",
                    )
                )

    return results
