"""Interactive onboarding wizard (make init) for pr-preview-platform."""

from __future__ import annotations

import argparse
import difflib
import getpass
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any

from scripts.preview_cli.doctor_cmd import run_doctor
from scripts.preview_cli.util import (
    DEFAULT_SECRETS_DIR,
    atomic_write,
    load_values_config,
    parse_simple_yaml,
    redact_secrets,
    render_k8s_secret,
    run_command,
    update_inventory_host,
    update_values_yaml,
    update_workflow_tailnet,
)

# Colors
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _colorize(text: str, color: str, is_tty: bool) -> str:
    return f"{color}{text}{RESET}" if is_tty else text


def _get_git_remote_url(repo_root: Path) -> str:
    try:
        res = run_command(["git", "config", "--get", "remote.origin.url"], timeout=3.0)
        url = res.stdout.strip()
        if url.startswith("git@github.com:"):
            return "https://github.com/" + url.removeprefix("git@github.com:")
        return url
    except Exception:
        return ""


def _parse_repo_slug(url: str) -> tuple[str, str]:
    clean = url.strip().removesuffix(".git")
    if "github.com/" in clean:
        parts = clean.split("github.com/", 1)[1].split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    return "", ""


def _prompt_input(
    prompt_text: str,
    default_val: str,
    validator: Any = None,
    error_msg: str = "Invalid input",
    is_tty: bool = True,
) -> str:
    display_default = f" [{default_val}]" if default_val else ""
    full_prompt = f"{prompt_text}{display_default}: "

    while True:
        val = input(full_prompt).strip()
        if not val and default_val:
            val = default_val

        if not validator or validator(val):
            return val
        print(_colorize(f"  Error: {error_msg}. Please try again.", RED, is_tty))


def run_init(
    repo_root: Path,
    non_interactive: bool = False,
    dry_run: bool = False,
    yes: bool = False,
    skip_secrets: bool = False,
    skip_doctor: bool = False,
    secrets_dir: Path | None = None,
    write_services: bool = False,
) -> int:
    """Run the initialization wizard."""
    is_tty = sys.stdout.isatty() and not non_interactive
    target_secrets_dir = secrets_dir or DEFAULT_SECRETS_DIR

    values_path = repo_root / "values.yaml"
    preview_wf = repo_root / ".github" / "workflows" / "preview.yml"
    preview_closed_wf = repo_root / ".github" / "workflows" / "preview-closed.yml"
    inv_path = repo_root / "ansible" / "inventory" / "local.ini"
    inv_example = repo_root / "ansible" / "inventory" / "local.ini.example"

    # Step 1: Detect existing configurations for defaults
    existing_cfg = load_values_config(repo_root)
    git_remote = _get_git_remote_url(repo_root)

    default_repo_url = (
        existing_cfg.get("repo", {}).get("url")
        or git_remote
        or "https://github.com/owner/my-repo.git"
    )
    def_owner, def_name = _parse_repo_slug(default_repo_url)

    default_app_name = existing_cfg.get("app", {}).get("name") or def_name or "demo-app"
    default_image = (
        existing_cfg.get("app", {}).get("image")
        or f"ghcr.io/{def_owner.lower() or 'owner'}/{default_app_name}"
    )
    default_port = str(existing_cfg.get("app", {}).get("port") or 8000)
    default_healthcheck = existing_cfg.get("app", {}).get("healthcheck") or "/healthz"
    default_ns_prefix = existing_cfg.get("namespace", {}).get("prefix") or "preview"
    default_tailnet = existing_cfg.get("tailnet", {}).get("name") or "my-tailnet.ts.net"

    default_vm_ip = "192.168.56.10"
    default_vm_user = "vboxuser"
    if inv_path.exists():
        inv_text = inv_path.read_text(encoding="utf-8")
        m_ip = re.search(r"ansible_host=([^\s\n#]+)", inv_text)
        if m_ip:
            default_vm_ip = m_ip.group(1).strip()
        m_u = re.search(r"ansible_user=([^\s\n#]+)", inv_text)
        if m_u:
            default_vm_user = m_u.group(1).strip()

    print(_colorize("==================================================", BOLD + CYAN, is_tty))
    print(_colorize("  PR Preview Platform - Configuration Setup Wizard", BOLD + CYAN, is_tty))
    print(_colorize("==================================================", BOLD + CYAN, is_tty))
    print("This wizard configures your platform parameters, workflows, and secrets.")
    print()

    # Step 2: Gather configurations
    if non_interactive:
        # Read from environment variables
        env_map = {
            "PREVIEW_REPO_URL": os.environ.get("PREVIEW_REPO_URL"),
            "PREVIEW_APP_NAME": os.environ.get("PREVIEW_APP_NAME"),
            "PREVIEW_IMAGE": os.environ.get("PREVIEW_IMAGE"),
            "PREVIEW_PORT": os.environ.get("PREVIEW_PORT"),
            "PREVIEW_HEALTHCHECK": os.environ.get("PREVIEW_HEALTHCHECK"),
            "PREVIEW_NS_PREFIX": os.environ.get("PREVIEW_NS_PREFIX"),
            "PREVIEW_TAILNET": os.environ.get("PREVIEW_TAILNET"),
            "PREVIEW_VM_IP": os.environ.get("PREVIEW_VM_IP"),
        }
        if not skip_secrets:
            env_map["TS_OAUTH_CLIENT_ID"] = os.environ.get("TS_OAUTH_CLIENT_ID") or os.environ.get(
                "PREVIEW_TS_OAUTH_CLIENT_ID"
            )
            env_map["TS_OAUTH_CLIENT_SECRET"] = os.environ.get(
                "TS_OAUTH_CLIENT_SECRET"
            ) or os.environ.get("PREVIEW_TS_OAUTH_CLIENT_SECRET")
            env_map["GITHUB_TOKEN"] = os.environ.get("GITHUB_TOKEN") or os.environ.get(
                "PREVIEW_GITHUB_TOKEN"
            )

        missing_envs = [k for k, v in env_map.items() if not v]
        if missing_envs:
            sys.stderr.write(
                f"Error: Non-interactive mode missing required environment variables: "
                f"{', '.join(missing_envs)}\n"
            )
            return 1

        repo_url = env_map["PREVIEW_REPO_URL"]
        app_name = env_map["PREVIEW_APP_NAME"]
        app_image = env_map["PREVIEW_IMAGE"]
        app_port = int(env_map["PREVIEW_PORT"])
        healthcheck = env_map["PREVIEW_HEALTHCHECK"]
        ns_prefix = env_map["PREVIEW_NS_PREFIX"]
        tailnet_name = env_map["PREVIEW_TAILNET"]
        vm_ip = env_map["PREVIEW_VM_IP"]
        vm_user = os.environ.get("PREVIEW_SSH_USER", default_vm_user)

        ts_id = env_map.get("TS_OAUTH_CLIENT_ID", "")
        ts_secret = env_map.get("TS_OAUTH_CLIENT_SECRET", "")
        gh_token = env_map.get("GITHUB_TOKEN", "")
        db_password = (
            os.environ.get("PREVIEW_DB_PASSWORD")
            or os.environ.get("POSTGRES_PASSWORD")
            or secrets.token_urlsafe(24)
        )
    else:
        # Interactive prompts with validation
        repo_url = _prompt_input(
            "GitHub Repository URL",
            default_repo_url,
            validator=lambda u: u.startswith("https://github.com/"),
            error_msg="Must be a valid GitHub HTTPS URL (https://github.com/...)",
            is_tty=is_tty,
        )

        app_name = _prompt_input(
            "Application Name",
            default_app_name,
            validator=lambda n: bool(re.match(r"^[a-zA-Z0-9_-]+$", n)),
            error_msg="Name must contain only letters, numbers, hyphens, and underscores",
            is_tty=is_tty,
        )

        app_image = _prompt_input(
            "Container Image Repository",
            default_image,
            validator=lambda img: img.startswith("ghcr.io/") and img == img.lower(),
            error_msg="Image must start with 'ghcr.io/' and be lowercase",
            is_tty=is_tty,
        )

        port_str = _prompt_input(
            "Application Port",
            default_port,
            validator=lambda p: p.isdigit() and 1 <= int(p) <= 65535,
            error_msg="Port must be an integer between 1 and 65535",
            is_tty=is_tty,
        )
        app_port = int(port_str)

        healthcheck = _prompt_input(
            "Healthcheck Probe Endpoint",
            default_healthcheck,
            validator=lambda h: h.startswith("/"),
            error_msg="Endpoint path must begin with '/'",
            is_tty=is_tty,
        )

        ns_prefix = _prompt_input(
            "Preview Namespace Prefix",
            default_ns_prefix,
            validator=lambda ns: bool(re.match(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", ns))
            and len(ns) <= 63,
            error_msg="Must be a valid DNS label (lowercase alphanumeric + hyphens, max 63 chars)",
            is_tty=is_tty,
        )

        tailnet_name = _prompt_input(
            "Tailscale Tailnet Domain",
            default_tailnet,
            validator=lambda t: t.endswith(".ts.net") and not t.startswith("<"),
            error_msg="Tailnet name must end in .ts.net (e.g. tail1234.ts.net)",
            is_tty=is_tty,
        )

        vm_ip = _prompt_input(
            "VM / Host Target IP",
            default_vm_ip,
            validator=lambda ip: bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip))
            or ip in ("localhost", "127.0.0.1"),
            error_msg="Must be a valid IPv4 address",
            is_tty=is_tty,
        )

        vm_user = _prompt_input(
            "VM SSH User",
            default_vm_user,
            validator=lambda u: bool(u),
            error_msg="User cannot be empty",
            is_tty=is_tty,
        )

        # Step 3: Secrets handling
        ts_id = ""
        ts_secret = ""
        gh_token = ""
        db_password = ""

        if not skip_secrets:
            print()
            print(_colorize("[Secrets Configuration]", BOLD, is_tty))
            print("Secrets are written to ~/.config/pr-preview/dr-secrets/ (mode 0600).")
            print("Values are entered securely and never echoed or logged.")

            # Check existing secret files
            op_oauth_path = target_secrets_dir / "operator-oauth.yaml"
            keep_existing_ts = False
            if op_oauth_path.exists():
                try:
                    s_data = parse_simple_yaml(op_oauth_path.read_text(encoding="utf-8"))
                    d = s_data.get("stringData") or s_data.get("data") or {}
                    if d.get("client_id") and d.get("client_secret"):
                        keep_ans = input(
                            "Found existing Tailscale OAuth secret. Keep existing? [Y/n]: "
                        ).strip()
                        if keep_ans.lower() not in ("n", "no"):
                            keep_existing_ts = True
                            ts_id = str(d["client_id"]).strip()
                            ts_secret = str(d["client_secret"]).strip()
                except Exception:
                    pass

            if not keep_existing_ts:
                while not ts_id:
                    ts_id = getpass.getpass("Tailscale OAuth Client ID: ").strip()
                while not ts_secret:
                    ts_secret = getpass.getpass("Tailscale OAuth Client Secret: ").strip()

            gh_token_path = target_secrets_dir / "github-token.yaml"
            keep_existing_gh = False
            if gh_token_path.exists():
                try:
                    s_data = parse_simple_yaml(gh_token_path.read_text(encoding="utf-8"))
                    d = s_data.get("stringData") or s_data.get("data") or {}
                    if d.get("token"):
                        keep_ans = input(
                            "Found existing GitHub token secret. Keep existing? [Y/n]: "
                        ).strip()
                        if keep_ans.lower() not in ("n", "no"):
                            keep_existing_gh = True
                            gh_token = str(d["token"]).strip()
                except Exception:
                    pass

            if not keep_existing_gh:
                while not gh_token:
                    gh_token = getpass.getpass("GitHub Personal Access Token (PAT): ").strip()

            db_pass_path = target_secrets_dir / "shared-postgres.yaml"
            keep_existing_db = False
            if db_pass_path.exists():
                try:
                    s_data = parse_simple_yaml(db_pass_path.read_text(encoding="utf-8"))
                    d = s_data.get("stringData") or s_data.get("data") or {}
                    if d.get("password") or d.get("POSTGRES_PASSWORD"):
                        keep_ans = input(
                            "Found existing PostgreSQL password secret. Keep existing? [Y/n]: "
                        ).strip()
                        if keep_ans.lower() not in ("n", "no"):
                            keep_existing_db = True
                            raw_p = d.get("password") or d.get("POSTGRES_PASSWORD")
                            db_password = str(raw_p).strip()
                except Exception:
                    pass

            if not keep_existing_db:
                custom_pass = getpass.getpass(
                    "Shared PostgreSQL Password (press Enter to generate strong random password): "
                ).strip()
                db_password = custom_pass if custom_pass else secrets.token_urlsafe(24)

    # Prepare file modifications
    # 1. values.yaml
    old_values = values_path.read_text(encoding="utf-8") if values_path.exists() else ""
    should_write_services = write_services or os.environ.get(
        "PREVIEW_WRITE_SERVICES", ""
    ).lower() in ("1", "true", "yes")

    values_updates: dict[str, Any] = {
        "repo_url": repo_url,
        "app_name": app_name,
        "app_image": app_image,
        "app_port": app_port,
        "app_healthcheck": healthcheck,
        "ns_prefix": ns_prefix,
        "tailnet_name": tailnet_name,
    }
    if should_write_services:
        values_updates["write_services"] = True

    new_values = update_values_yaml(old_values, values_updates)

    # 2. Workflows
    old_preview_wf = preview_wf.read_text(encoding="utf-8") if preview_wf.exists() else ""
    new_preview_wf = update_workflow_tailnet(old_preview_wf, tailnet_name)

    old_closed_wf = (
        preview_closed_wf.read_text(encoding="utf-8") if preview_closed_wf.exists() else ""
    )
    new_closed_wf = update_workflow_tailnet(old_closed_wf, tailnet_name)

    # 3. Inventory
    if inv_path.exists():
        old_inv = inv_path.read_text(encoding="utf-8")
    elif inv_example.exists():
        old_inv = inv_example.read_text(encoding="utf-8")
    else:
        old_inv = (
            "[k3s_server]\ndevops-server ansible_host=127.0.0.1\n"
            "[all:vars]\nansible_user=vboxuser\n"
        )
    new_inv = update_inventory_host(old_inv, vm_ip, vm_user)

    # 4. Secrets manifests
    manifest_operator = (
        render_k8s_secret(
            "operator-oauth",
            "tailscale",
            {"client_id": ts_id, "client_secret": ts_secret},
        )
        if (ts_id and ts_secret)
        else ""
    )

    manifest_github = (
        render_k8s_secret(
            "github-token",
            "argocd",
            {"token": gh_token},
        )
        if gh_token
        else ""
    )

    manifest_postgres = (
        render_k8s_secret(
            "shared-main-app-postgres",
            "shared",
            {"password": db_password},
        )
        if db_password
        else ""
    )

    # Dry-run handling: show unified diffs and exit
    if dry_run:
        print()
        print(_colorize("[DRY-RUN] Unified diffs of planned changes:", BOLD + YELLOW, is_tty))

        def show_diff(name: str, a: str, b: str, redact: bool = False) -> None:
            if a == b:
                print(f"  {name}: (no changes)")
                return
            diff_lines = list(
                difflib.unified_diff(
                    a.splitlines(keepends=True),
                    b.splitlines(keepends=True),
                    fromfile=f"a/{name}",
                    tofile=f"b/{name}",
                )
            )
            print(f"--- {name} diff ---")
            for line in diff_lines:
                out_l = redact_secrets(line) if redact else line
                print(out_l, end="")
            print()

        show_diff("values.yaml", old_values, new_values)
        show_diff(".github/workflows/preview.yml", old_preview_wf, new_preview_wf)
        show_diff(".github/workflows/preview-closed.yml", old_closed_wf, new_closed_wf)
        show_diff("ansible/inventory/local.ini", old_inv, new_inv)

        if not skip_secrets:
            print("--- DR Secrets Manifests (redacted) ---")
            print(redact_secrets(manifest_operator))
            print(redact_secrets(manifest_github))
            print(redact_secrets(manifest_postgres))

        print(_colorize("[DRY-RUN] No files were modified.", BOLD + YELLOW, is_tty))
        return 0

    # User confirmation before writing (unless --yes or non-interactive)
    if not non_interactive and not yes:
        print()
        print(_colorize("Summary of files to update:", BOLD, is_tty))
        print(f"  - {values_path.relative_to(repo_root)}")
        print(f"  - {preview_wf.relative_to(repo_root)}")
        print(f"  - {preview_closed_wf.relative_to(repo_root)}")
        print(f"  - {inv_path.relative_to(repo_root)}")
        if not skip_secrets:
            print(f"  - {target_secrets_dir}/operator-oauth.yaml (0600)")
            print(f"  - {target_secrets_dir}/github-token.yaml (0600)")
            print(f"  - {target_secrets_dir}/shared-postgres.yaml (0600)")
        confirm = input("\nProceed with writing configuration? [Y/n]: ").strip()
        if confirm.lower() in ("n", "no"):
            print("Aborted by user.")
            return 0

    # Step 4: Apply changes atomically
    print()
    print(_colorize("Applying changes...", BOLD + CYAN, is_tty))

    # Update values.yaml
    atomic_write(values_path, new_values, backup=True)
    print(f"  {_colorize('✓ Updated', GREEN, is_tty)} values.yaml (backup created)")

    # Update workflows
    if preview_wf.exists():
        atomic_write(preview_wf, new_preview_wf, backup=True)
        print(f"  {_colorize('✓ Updated', GREEN, is_tty)} .github/workflows/preview.yml")

    if preview_closed_wf.exists():
        atomic_write(preview_closed_wf, new_closed_wf, backup=True)
        print(f"  {_colorize('✓ Updated', GREEN, is_tty)} .github/workflows/preview-closed.yml")

    # Update inventory
    atomic_write(inv_path, new_inv, backup=True)
    print(f"  {_colorize('✓ Updated', GREEN, is_tty)} ansible/inventory/local.ini")

    # Write secrets
    if not skip_secrets:
        target_secrets_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(target_secrets_dir, 0o700)

        if manifest_operator:
            atomic_write(
                target_secrets_dir / "operator-oauth.yaml",
                manifest_operator,
                mode=0o600,
                backup=False,
            )
        if manifest_github:
            atomic_write(
                target_secrets_dir / "github-token.yaml",
                manifest_github,
                mode=0o600,
                backup=False,
            )
        if manifest_postgres:
            atomic_write(
                target_secrets_dir / "shared-postgres.yaml",
                manifest_postgres,
                mode=0o600,
                backup=False,
            )
        print(f"  {_colorize('✓ Generated', GREEN, is_tty)} 0600 secrets in {target_secrets_dir}")

    # Step 5: Run existing sync-config logic
    print(_colorize("Synchronizing platform manifests with values.yaml...", CYAN, is_tty))
    sync_script = repo_root / "scripts" / "sync-config.py"
    if sync_script.exists():
        try:
            res_sync = run_command([sys.executable, str(sync_script)], timeout=10.0)
            if res_sync.returncode == 0:
                print(f"  {_colorize('✓ Manifests synchronized', GREEN, is_tty)}")
            else:
                warn_txt = _colorize("⚠ Warning: Manifest sync returned error", YELLOW, is_tty)
                print(f"  {warn_txt}")
        except Exception as e:
            print(f"  {_colorize('⚠ Warning: Manifest sync failed: ' + str(e), YELLOW, is_tty)}")

    # Step 6: Run doctor preflight checks
    if not skip_doctor:
        print()
        print(_colorize("Running post-init preflight doctor...", BOLD + CYAN, is_tty))
        run_doctor(
            repo_root=repo_root,
            offline=False,
            skip_cluster=True,  # Initially skip cluster until bootstrapped
            secrets_dir=target_secrets_dir,
        )

    # Step 7: Print next steps
    print()
    print(_colorize("==================================================", BOLD + GREEN, is_tty))
    print(_colorize("  Initialization Complete!", BOLD + GREEN, is_tty))
    print(_colorize("==================================================", BOLD + GREEN, is_tty))
    print("Next steps to provision your PR Preview Platform:")
    print("  1. Review your changes: git diff")
    print("  2. Verify preflight health: make doctor")
    print("  3. Bootstrap the complete platform:")
    print("     - For clean VirtualBox VM: make bootstrap")
    print("     - For existing cluster:    make bootstrap-platform")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for init CLI."""
    parser = argparse.ArgumentParser(
        description="Interactive onboarding wizard for PR Preview Platform",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without interactive prompts (reads PREVIEW_* and credential env vars)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate changes and display unified diffs without modifying files",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Automatically confirm prompt to write configuration files",
    )
    parser.add_argument(
        "--skip-secrets",
        action="store_true",
        help="Skip generating or writing out-of-band disaster recovery secrets",
    )
    parser.add_argument(
        "--skip-doctor",
        action="store_true",
        help="Skip running preflight health check after configuration",
    )
    parser.add_argument(
        "--with-services",
        "--write-services",
        action="store_true",
        dest="write_services",
        help="Optionally write services list into values.yaml derived from app configuration",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    repo_root = Path(__file__).resolve().parent.parent.parent
    try:
        return run_init(
            repo_root=repo_root,
            non_interactive=args.non_interactive,
            dry_run=args.dry_run,
            yes=args.yes,
            skip_secrets=args.skip_secrets,
            skip_doctor=args.skip_doctor,
            write_services=args.write_services,
        )
    except Exception as exc:
        msg = redact_secrets(str(exc))
        sys.stderr.write(f"Fatal init crash: {msg}\n")
        return 2
