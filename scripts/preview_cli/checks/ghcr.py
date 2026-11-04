"""GHCR anonymous package visibility check."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from scripts.preview_cli.checks import CheckResult
from scripts.preview_cli.util import load_values_config, redact_secrets


def check_ghcr(repo_root: Path, offline: bool = False) -> list[CheckResult]:
    """Verify anonymously that the GHCR image package is publicly pullable."""
    results: list[CheckResult] = []

    if offline:
        results.append(
            CheckResult(
                id="ghcr.visibility",
                title="GHCR package visibility",
                status="SKIP",
                message="Offline mode enabled (--offline); skipping remote GHCR check",
            )
        )
        return results

    cfg = load_values_config(repo_root)
    app_image = cfg.get("app", {}).get("image", "").strip()

    if not app_image or not app_image.startswith("ghcr.io/"):
        results.append(
            CheckResult(
                id="ghcr.visibility",
                title="GHCR package visibility",
                status="FAIL",
                message=f"app.image in values.yaml is not a valid GHCR image path: '{app_image}'",
                fix="Set app.image in values.yaml to 'ghcr.io/<owner>/<app>'",
            )
        )
        return results

    # Extract repository path: ghcr.io/<owner>/<package>
    repo_path = app_image.removeprefix("ghcr.io/").strip().lower()
    parts = repo_path.split("/")
    if len(parts) < 2:
        results.append(
            CheckResult(
                id="ghcr.visibility",
                title="GHCR package visibility",
                status="FAIL",
                message=f"Cannot determine owner/package from image: '{app_image}'",
                fix="Use format 'ghcr.io/<owner>/<package>' in values.yaml",
            )
        )
        return results

    owner = parts[0]
    pkg_name = parts[1]

    # Step 1: Request anonymous pull token
    token_url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{owner}/{pkg_name}:pull"
    req_token = urllib.request.Request(
        token_url,
        headers={"User-Agent": "pr-preview-platform/1.0"},
    )

    try:
        with urllib.request.urlopen(req_token, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            anon_token = data.get("token")
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            results.append(
                CheckResult(
                    id="ghcr.visibility",
                    title="GHCR package visibility",
                    status="FAIL",
                    message=f"Package '{repo_path}' is Private (anonymous pull token denied)",
                    fix=(
                        f"Navigate to https://github.com/users/{owner}/packages/"
                        f"container/{pkg_name}/settings and change visibility to Public"
                    ),
                )
            )
            return results
        if err.code == 404:
            results.append(
                CheckResult(
                    id="ghcr.visibility",
                    title="GHCR package visibility",
                    status="WARN",
                    message=f"Package '{repo_path}' not found on GHCR (never pushed yet)",
                    fix="Run first PR build to push image, then set visibility to Public",
                )
            )
            return results
        results.append(
            CheckResult(
                id="ghcr.visibility",
                title="GHCR package visibility",
                status="FAIL",
                message=f"GHCR auth error: HTTP {err.code}",
                fix="Check network connection or GHCR status",
            )
        )
        return results
    except Exception as exc:
        results.append(
            CheckResult(
                id="ghcr.visibility",
                title="GHCR package visibility",
                status="FAIL",
                message=f"Connection error to ghcr.io: {redact_secrets(str(exc))}",
                fix="Check internet connection",
            )
        )
        return results

    if not anon_token:
        results.append(
            CheckResult(
                id="ghcr.visibility",
                title="GHCR package visibility",
                status="WARN",
                message="No anonymous pull token returned from ghcr.io",
                fix="Verify package visibility in GitHub Package settings",
            )
        )
        return results

    # Step 2: Query tags or manifest with anonymous token
    tags_url = f"https://ghcr.io/v2/{owner}/{pkg_name}/tags/list"
    req_tags = urllib.request.Request(
        tags_url,
        headers={
            "Authorization": f"Bearer {anon_token}",
            "User-Agent": "pr-preview-platform/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req_tags, timeout=10.0) as resp:
            tags_data = json.loads(resp.read().decode("utf-8"))
            tags = tags_data.get("tags") or []
            if tags:
                # HEAD latest tag manifest
                test_tag = tags[-1]
                manifest_url = f"https://ghcr.io/v2/{owner}/{pkg_name}/manifests/{test_tag}"
                req_head = urllib.request.Request(
                    manifest_url,
                    method="HEAD",
                    headers={
                        "Authorization": f"Bearer {anon_token}",
                        "Accept": (
                            "application/vnd.docker.distribution.manifest.v2+json, "
                            "application/vnd.oci.image.manifest.v1+json"
                        ),
                        "User-Agent": "pr-preview-platform/1.0",
                    },
                )
                with urllib.request.urlopen(req_head, timeout=10.0) as head_resp:
                    if head_resp.status in (200, 206):
                        results.append(
                            CheckResult(
                                id="ghcr.visibility",
                                title="GHCR package visibility",
                                status="PASS",
                                message=(
                                    f"Package is Public and pullable anonymously "
                                    f"({len(tags)} tag(s) found)"
                                ),
                            )
                        )
                        return results
            results.append(
                CheckResult(
                    id="ghcr.visibility",
                    title="GHCR package visibility",
                    status="WARN",
                    message=f"Package exists but has no tags yet: {repo_path}",
                    fix="Run first PR build to push container image, then verify visibility",
                )
            )
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            results.append(
                CheckResult(
                    id="ghcr.visibility",
                    title="GHCR package visibility",
                    status="FAIL",
                    message=f"Package '{repo_path}' is Private (HEAD request unauthorized)",
                    fix=(
                        f"Navigate to https://github.com/users/{owner}/packages/"
                        f"container/{pkg_name}/settings and change visibility to Public"
                    ),
                )
            )
        elif err.code == 404:
            results.append(
                CheckResult(
                    id="ghcr.visibility",
                    title="GHCR package visibility",
                    status="WARN",
                    message=f"Image has not been pushed to GHCR yet: '{repo_path}'",
                    fix="Run first PR build to push container image, then set visibility to Public",
                )
            )
        else:
            results.append(
                CheckResult(
                    id="ghcr.visibility",
                    title="GHCR package visibility",
                    status="FAIL",
                    message=f"GHCR registry returned HTTP {err.code}",
                    fix="Check package settings on GitHub",
                )
            )
    except Exception as exc:
        results.append(
            CheckResult(
                id="ghcr.visibility",
                title="GHCR package visibility",
                status="FAIL",
                message=f"Error checking package: {redact_secrets(str(exc))}",
                fix="Check internet connection",
            )
        )

    return results
