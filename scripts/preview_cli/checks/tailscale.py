"""Tailscale OAuth credentials, tailnet domain, and CLI checks."""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.preview_cli.checks import CheckResult
from scripts.preview_cli.util import (
    DEFAULT_SECRETS_DIR,
    load_values_config,
    parse_simple_yaml,
    redact_secrets,
    run_command,
)

TAILNET_NAME_REGEX = re.compile(r"^[a-zA-Z0-9][-a-zA-Z0-9.]*\.ts\.net$")


def _get_tailscale_oauth(secrets_dir: Path) -> tuple[str | None, str | None]:
    cid = os.environ.get("TS_OAUTH_CLIENT_ID")
    csecret = os.environ.get("TS_OAUTH_CLIENT_SECRET")
    if cid and csecret:
        return cid.strip(), csecret.strip()

    oauth_file = secrets_dir / "operator-oauth.yaml"
    if oauth_file.exists():
        try:
            cfg = parse_simple_yaml(oauth_file.read_text(encoding="utf-8"))
            data = cfg.get("stringData") or cfg.get("data") or {}
            fid = data.get("client_id")
            fsecret = data.get("client_secret")
            if fid and fsecret:
                return str(fid).strip(), str(fsecret).strip()
        except Exception:
            return None, None
    return None, None


def check_tailscale(
    repo_root: Path,
    offline: bool = False,
    secrets_dir: Path | None = None,
) -> list[CheckResult]:
    """Verify Tailscale OAuth token generation, tailnet name, and CLI status."""
    results: list[CheckResult] = []
    target_secrets_dir = secrets_dir or DEFAULT_SECRETS_DIR
    cfg = load_values_config(repo_root)

    # 1. Tailnet name format
    tailnet_name = cfg.get("tailnet", {}).get("name", "").strip()
    placeholders = {"<tailnet-name>.ts.net", "change_me", "example.ts.net", ""}
    if not tailnet_name or tailnet_name.lower() in placeholders or "<" in tailnet_name:
        results.append(
            CheckResult(
                id="tailscale.tailnet_name",
                title="Tailnet domain format",
                status="FAIL",
                message=f"tailnet.name is missing or placeholder: '{tailnet_name}'",
                fix="Set your real domain (e.g. xyz.ts.net) in values.yaml or run 'make init'",
            )
        )
    elif TAILNET_NAME_REGEX.match(tailnet_name):
        results.append(
            CheckResult(
                id="tailscale.tailnet_name",
                title="Tailnet domain format",
                status="PASS",
                message=f"Valid tailnet domain: {tailnet_name}",
            )
        )
    else:
        results.append(
            CheckResult(
                id="tailscale.tailnet_name",
                title="Tailnet domain format",
                status="FAIL",
                message=f"Invalid tailnet format (must end in .ts.net): '{tailnet_name}'",
                fix="Configure a valid domain ending in .ts.net in values.yaml",
            )
        )

    # 2. OAuth client credentials grant
    cid, csec = _get_tailscale_oauth(target_secrets_dir)
    if not cid or not csec:
        results.append(
            CheckResult(
                id="tailscale.oauth",
                title="Tailscale OAuth credentials",
                status="FAIL",
                message="OAuth client credentials not found in env or operator-oauth.yaml",
                fix="Run 'make init' or set TS_OAUTH_CLIENT_ID and TS_OAUTH_CLIENT_SECRET",
            )
        )
    elif offline:
        results.append(
            CheckResult(
                id="tailscale.oauth",
                title="Tailscale OAuth credentials",
                status="SKIP",
                message="Offline mode enabled (--offline); skipping remote OAuth token validation",
            )
        )
    else:
        # Perform client_credentials token grant
        token_endpoint = "https://api.tailscale.com/api/v2/oauth/token"
        body_data = urllib.parse.urlencode(
            {
                "client_id": cid,
                "client_secret": csec,
                "grant_type": "client_credentials",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            token_endpoint,
            data=body_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "pr-preview-platform/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                if resp.status == 200 and resp_data.get("access_token"):
                    results.append(
                        CheckResult(
                            id="tailscale.oauth",
                            title="Tailscale OAuth credentials",
                            status="PASS",
                            message="OAuth client_credentials token granted successfully",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            id="tailscale.oauth",
                            title="Tailscale OAuth credentials",
                            status="FAIL",
                            message=f"OAuth endpoint returned status {resp.status}",
                            fix="Verify OAuth client permissions in Tailscale Admin Console",
                        )
                    )
        except urllib.error.HTTPError as err:
            results.append(
                CheckResult(
                    id="tailscale.oauth",
                    title="Tailscale OAuth credentials",
                    status="FAIL",
                    message=f"OAuth authentication failed (HTTP {err.code})",
                    fix=(
                        "Verify OAuth client in https://login.tailscale.com/admin/settings/oauth. "
                        "Ensure Devices:Write and Auth Keys:Write scopes are granted."
                    ),
                )
            )
        except Exception as exc:
            results.append(
                CheckResult(
                    id="tailscale.oauth",
                    title="Tailscale OAuth credentials",
                    status="FAIL",
                    message=f"Connection error: {redact_secrets(str(exc), [csec])}",
                    fix="Check internet connection",
                )
            )

    # 3. Host Tailscale CLI status
    if shutil.which("tailscale"):
        try:
            res = run_command(["tailscale", "status", "--json"], timeout=5.0)
            if res.returncode == 0:
                ts_stat = json.loads(res.stdout) if res.stdout.strip().startswith("{") else {}
                backend_state = ts_stat.get("BackendState", "")
                if backend_state == "Running" or "Logged out" not in res.stdout:
                    results.append(
                        CheckResult(
                            id="tailscale.cli",
                            title="Host Tailscale CLI status",
                            status="PASS",
                            message=(
                                f"Tailscale is running on host (state: {backend_state or 'active'})"
                            ),
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            id="tailscale.cli",
                            title="Host Tailscale CLI status",
                            status="WARN",
                            message=f"Tailscale CLI is not connected (state: {backend_state})",
                            fix="Run: tailscale up",
                        )
                    )
            else:
                results.append(
                    CheckResult(
                        id="tailscale.cli",
                        title="Host Tailscale CLI status",
                        status="WARN",
                        message="Tailscale daemon is not responding",
                        fix="Start Tailscale daemon and run: tailscale up",
                    )
                )
        except Exception as exc:
            results.append(
                CheckResult(
                    id="tailscale.cli",
                    title="Host Tailscale CLI status",
                    status="WARN",
                    message=f"Could not verify Tailscale CLI: {exc}",
                    fix="Run: tailscale status",
                )
            )
    else:
        results.append(
            CheckResult(
                id="tailscale.cli",
                title="Host Tailscale CLI status",
                status="SKIP",
                message="tailscale CLI not installed on host machine (optional)",
            )
        )

    # 4. MagicDNS and HTTPS Certificates notice
    results.append(
        CheckResult(
            id="tailscale.dns_https",
            title="Tailscale MagicDNS & HTTPS certificates",
            status="WARN",
            message="MagicDNS and HTTPS certificates cannot be verified automatically via API",
            fix="Verify MagicDNS and HTTPS are enabled: https://login.tailscale.com/admin/dns",
        )
    )

    return results
