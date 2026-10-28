#!/usr/bin/env python3
"""Synchronize platform manifests with root values.yaml.

Single Source of Truth: values.yaml
This script parses repo.url, repo.label, and namespace.prefix from values.yaml
and automatically updates:
- platform/argocd/applicationset-previews.yaml (owner, repo, labels, git repoURL)
- platform/argocd/project-previews.yaml (sourceRepos, destination prefix)
- platform/argocd/application-shared.yaml (source repoURL)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


def parse_repo_coordinates(
    url: str,
    explicit_owner: str = "",
    explicit_repo: str = "",
) -> tuple[str, str]:
    """Extract (owner, repo) from GitHub URL or return explicit values."""
    if explicit_owner and explicit_repo:
        return explicit_owner, explicit_repo

    clean_url = url.strip().removesuffix(".git")
    # Matches https://github.com/owner/repo or git@github.com:owner/repo
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+)$", clean_url)
    if not m:
        raise ValueError(
            f"Could not parse GitHub owner/repo from URL: '{url}'. "
            "Please ensure repo.url is valid or set repo.owner and repo.name."
        )
    return explicit_owner or m.group(1), explicit_repo or m.group(2)


def sync_applicationset(
    content: str,
    owner: str,
    repo: str,
    label: str,
    repo_url: str,
) -> str:
    """Update pullRequest generator and git generator in applicationset-previews.yaml."""
    # 1. Update pullRequest.github.owner
    content = re.sub(
        r"(pullRequest:\s*\n\s*github:\s*\n\s*owner:\s*)[^\n]+",
        rf"\g<1>{owner}",
        content,
    )
    # 2. Update pullRequest.github.repo
    content = re.sub(
        r"(pullRequest:\s*\n\s*github:\s*\n(?:\s*[^\n]+\n)*?\s*repo:\s*)[^\n]+",
        rf"\g<1>{repo}",
        content,
    )
    # 3. Update pullRequest.github.labels
    content = re.sub(
        r"(labels:\s*\n\s*-\s*)[^\n]+",
        rf"\g<1>{label}",
        content,
        count=1,
    )
    # 4. Update git generator repoURL
    content = re.sub(
        r"(- git:\s*\n\s*repoURL:\s*)[^\n]+",
        rf"\g<1>{repo_url}",
        content,
    )
    return content


def sync_appproject(content: str, repo_url: str, ns_prefix: str) -> str:
    """Ensure repo_url and destination prefix are present in project-previews.yaml."""
    # Ensure repo_url is in sourceRepos
    has_repo = (
        f'- "{repo_url}"' in content or f"- '{repo_url}'" in content or f"- {repo_url}" in content
    )
    if not has_repo:
        content = re.sub(
            r"(sourceRepos:\s*\n)(\s*-\s*[^\n]+)",
            rf'\g<1>    - "{repo_url}"',
            content,
            count=1,
        )

    # Ensure prefix-* is in destinations
    target_dest = f'namespace: "{ns_prefix}-*"'
    if target_dest not in content:
        dest_snippet = (
            f'    - server: "https://kubernetes.default.svc"\n      namespace: "{ns_prefix}-*"\n'
        )
        content = re.sub(
            r"(destinations:\s*\n)",
            rf"\g<1>{dest_snippet}",
            content,
            count=1,
        )

    return content


def sync_application_shared(content: str, repo_url: str) -> str:
    """Update repoURL in application-shared.yaml."""
    content = re.sub(
        r"(source:\s*\n\s*repoURL:\s*)[^\n]+",
        rf"\g<1>{repo_url}",
        content,
        count=1,
    )
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync platform manifests with root values.yaml")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if files are in sync without writing",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    values_path = repo_root / "values.yaml"
    appset_path = repo_root / "platform" / "argocd" / "applicationset-previews.yaml"
    appproj_path = repo_root / "platform" / "argocd" / "project-previews.yaml"
    appshared_path = repo_root / "platform" / "argocd" / "application-shared.yaml"

    if not values_path.exists():
        print(f"ERROR: {values_path} not found.", file=sys.stderr)
        return 1

    with open(values_path, encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    repo_cfg = cfg.get("repo", {})
    repo_url = repo_cfg.get("url", "").strip()
    if not repo_url:
        print("ERROR: 'repo.url' is required in values.yaml.", file=sys.stderr)
        return 1

    repo_label = repo_cfg.get("label", "preview")
    explicit_owner = repo_cfg.get("owner", "")
    explicit_repo = repo_cfg.get("name", "")
    ns_prefix = cfg.get("namespace", {}).get("prefix", "preview")

    owner, repo_name = parse_repo_coordinates(repo_url, explicit_owner, explicit_repo)

    out_of_sync = False

    # 1. Sync ApplicationSet
    if appset_path.exists():
        orig_appset = appset_path.read_text(encoding="utf-8")
        new_appset = sync_applicationset(orig_appset, owner, repo_name, repo_label, repo_url)
        if orig_appset != new_appset:
            out_of_sync = True
            if not args.check:
                appset_path.write_text(new_appset, encoding="utf-8")
                print(f"✓ Updated {appset_path.relative_to(repo_root)}")

    # 2. Sync AppProject
    if appproj_path.exists():
        orig_appproj = appproj_path.read_text(encoding="utf-8")
        new_appproj = sync_appproject(orig_appproj, repo_url, ns_prefix)
        if orig_appproj != new_appproj:
            out_of_sync = True
            if not args.check:
                appproj_path.write_text(new_appproj, encoding="utf-8")
                print(f"✓ Updated {appproj_path.relative_to(repo_root)}")

    # 3. Sync Application Shared
    if appshared_path.exists():
        orig_appshared = appshared_path.read_text(encoding="utf-8")
        new_appshared = sync_application_shared(orig_appshared, repo_url)
        if orig_appshared != new_appshared:
            out_of_sync = True
            if not args.check:
                appshared_path.write_text(new_appshared, encoding="utf-8")
                print(f"✓ Updated {appshared_path.relative_to(repo_root)}")

    if args.check:
        if out_of_sync:
            print(
                "ERROR: Platform manifests out of sync with values.yaml. Run 'make sync-config'.",
                file=sys.stderr,
            )
            return 1
        print("✓ All platform manifests are synchronized with values.yaml.")
        return 0

    if not out_of_sync:
        print("✓ All platform manifests already in sync with values.yaml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
