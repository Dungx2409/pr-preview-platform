"""Doctor diagnostic runner for pr-preview-platform."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from scripts.preview_cli.checks import CheckResult
from scripts.preview_cli.checks.cluster import check_cluster
from scripts.preview_cli.checks.config import check_config
from scripts.preview_cli.checks.ghcr import check_ghcr
from scripts.preview_cli.checks.github import check_github
from scripts.preview_cli.checks.host import check_host
from scripts.preview_cli.checks.secrets import check_secrets
from scripts.preview_cli.checks.tailscale import check_tailscale
from scripts.preview_cli.checks.tools import check_tools
from scripts.preview_cli.util import redact_secrets

# ANSI color codes
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
GRAY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _colorize(text: str, color: str, is_tty: bool) -> str:
    return f"{color}{text}{RESET}" if is_tty else text


def run_doctor(
    repo_root: Path,
    offline: bool = False,
    skip_cluster: bool = False,
    only_group: str | None = None,
    verbose: bool = False,
    is_json: bool = False,
    host_override: str | None = None,
    secrets_dir: Path | None = None,
) -> int:
    """Execute preflight diagnostic checks and render results."""
    is_tty = sys.stdout.isatty() and not is_json
    start_time = time.time()

    all_groups: dict[str, str] = {
        "tools": "Toolchain & System Binaries",
        "config": "Centralized Configuration (values.yaml)",
        "secrets": "Disaster Recovery Secrets & Environment Variables",
        "github": "GitHub API, Repository & Workflow Permissions",
        "ghcr": "GHCR Anonymous Package Visibility",
        "tailscale": "Tailscale OAuth & Private Networking",
        "host": "Target VM / Host Connectivity (TCP 22)",
        "cluster": "Kubernetes In-Cluster Workloads & Resources",
    }

    if only_group and only_group not in all_groups:
        sys.stderr.write(
            f"Error: Unknown check group '{only_group}'. "
            f"Available groups: {', '.join(all_groups.keys())}\n"
        )
        return 2

    active_groups = [only_group] if only_group else list(all_groups.keys())
    group_results: dict[str, list[CheckResult]] = {}

    for grp in active_groups:
        try:
            if grp == "tools":
                res = check_tools(repo_root)
            elif grp == "config":
                res = check_config(repo_root)
            elif grp == "secrets":
                res = check_secrets(secrets_dir)
            elif grp == "github":
                res = check_github(repo_root, offline=offline, secrets_dir=secrets_dir)
            elif grp == "ghcr":
                res = check_ghcr(repo_root, offline=offline)
            elif grp == "tailscale":
                res = check_tailscale(repo_root, offline=offline, secrets_dir=secrets_dir)
            elif grp == "host":
                res = check_host(repo_root, host_override=host_override)
            elif grp == "cluster":
                res = check_cluster(repo_root, offline=offline, skip_cluster=skip_cluster)
            else:
                res = []
        except Exception as exc:
            msg = redact_secrets(str(exc))
            res = [
                CheckResult(
                    id=f"{grp}.crash",
                    title=f"{all_groups[grp]} runner",
                    status="FAIL",
                    message=f"check errored: {msg}",
                    fix="Run with --verbose or check underlying tool installation",
                )
            ]
        group_results[grp] = res

    elapsed = time.time() - start_time

    # Calculate statistics
    total_pass = 0
    total_warn = 0
    total_fail = 0
    total_skip = 0

    flat_results: list[dict[str, str]] = []
    for grp, res_list in group_results.items():
        for item in res_list:
            if item.status == "PASS":
                total_pass += 1
            elif item.status == "WARN":
                total_warn += 1
            elif item.status == "FAIL":
                total_fail += 1
            elif item.status == "SKIP":
                total_skip += 1

            flat_results.append(
                {
                    "group": grp,
                    "id": item.id,
                    "title": item.title,
                    "status": item.status,
                    "message": redact_secrets(item.message),
                    "fix": redact_secrets(item.fix),
                }
            )

    overall_status = "FAIL" if total_fail > 0 else "PASS"

    if is_json:
        data = {
            "status": overall_status,
            "passed": total_pass,
            "warnings": total_warn,
            "failed": total_fail,
            "skipped": total_skip,
            "elapsed_seconds": round(elapsed, 2),
            "checks": flat_results,
        }
        print(json.dumps(data, indent=2))
        return 1 if total_fail > 0 else 0

    # Human-readable formatted output
    header = f"=== PR Preview Platform - Preflight Health Doctor ({elapsed:.2f}s) ==="
    print(_colorize(header, BOLD + CYAN, is_tty))
    print()

    for grp in active_groups:
        title = all_groups[grp]
        checks = group_results[grp]
        print(_colorize(f"[{title}]", BOLD, is_tty))

        for c in checks:
            if c.status == "PASS":
                status_badge = _colorize("[PASS]", GREEN, is_tty)
            elif c.status == "WARN":
                status_badge = _colorize("[WARN]", YELLOW, is_tty)
            elif c.status == "FAIL":
                status_badge = _colorize("[FAIL]", RED, is_tty)
            else:
                status_badge = _colorize("[SKIP]", GRAY, is_tty)

            print(f"  {status_badge} {c.title}: {redact_secrets(c.message)}")
            if c.status in ("FAIL", "WARN") and c.fix:
                indent = "         "
                fix_label = _colorize("Fix:", CYAN, is_tty)
                print(f"{indent}{fix_label} {redact_secrets(c.fix)}")

        print()

    # Summary Line
    summary_parts = [
        _colorize(f"{total_pass} passed", GREEN, is_tty),
        _colorize(f"{total_warn} warnings", YELLOW if total_warn else GRAY, is_tty),
        _colorize(f"{total_fail} failed", RED if total_fail else GRAY, is_tty),
        _colorize(f"{total_skip} skipped", GRAY, is_tty),
    ]
    summary_str = f"Doctor summary: {', '.join(summary_parts)} ({elapsed:.2f}s)"
    print(_colorize(summary_str, BOLD, is_tty))

    if total_fail > 0:
        fail_msg = "Result: Preflight checks encountered failures. Review the fix hints above."
        print(_colorize(fail_msg, RED + BOLD, is_tty))
        return 1

    pass_msg = "Result: All critical preflight checks passed. Platform is healthy!"
    print(_colorize(pass_msg, GREEN + BOLD, is_tty))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the doctor CLI."""
    parser = argparse.ArgumentParser(
        description="Preflight and health diagnostic check for PR Preview Platform",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip remote external network and API checks (GitHub, GHCR, Tailscale)",
    )
    parser.add_argument(
        "--skip-cluster",
        action="store_true",
        help="Skip in-cluster Kubernetes checks (kubectl, pods, secrets, CRDs)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format (safe and machine-readable)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed diagnostic output",
    )
    parser.add_argument(
        "--only",
        dest="only_group",
        choices=["tools", "config", "secrets", "github", "ghcr", "tailscale", "host", "cluster"],
        help="Run only a specific check group",
    )
    parser.add_argument(
        "--host",
        dest="host_override",
        help="Override target VM / server IP for connectivity checks",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    repo_root = Path(__file__).resolve().parent.parent.parent
    try:
        return run_doctor(
            repo_root=repo_root,
            offline=args.offline,
            skip_cluster=args.skip_cluster,
            only_group=args.only_group,
            verbose=args.verbose,
            is_json=args.json,
            host_override=args.host_override,
        )
    except Exception as exc:
        msg = redact_secrets(str(exc))
        sys.stderr.write(f"Fatal doctor crash: {msg}\n")
        return 2
