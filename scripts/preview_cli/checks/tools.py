"""CLI and toolchain dependency checks."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from scripts.preview_cli.checks import CheckResult
from scripts.preview_cli.util import parse_pinned_versions, run_command


def _parse_semver(v_str: str) -> tuple[int, ...]:
    clean = re.sub(r"[^\d.]", "", v_str)
    parts = clean.split(".")
    res = []
    for p in parts:
        if p.isdigit():
            res.append(int(p))
    return tuple(res)


def check_tools(repo_root: Path) -> list[CheckResult]:
    """Verify local toolchain dependencies and minimum versions."""
    results: list[CheckResult] = []
    pinned = parse_pinned_versions(repo_root)

    # 1. Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    is_valid_python = (sys.version_info[0], sys.version_info[1]) >= (3, 10)
    if is_valid_python:
        results.append(
            CheckResult(
                id="tools.python",
                title="Python runtime",
                status="PASS",
                message=f"Python {py_ver} (>= 3.10 required)",
            )
        )
    else:
        results.append(
            CheckResult(
                id="tools.python",
                title="Python runtime",
                status="FAIL",
                message=f"Python {py_ver} is too old (>= 3.10 required)",
                fix="Install Python 3.10 or later using pyenv or your system package manager",
            )
        )

    # 2. uv or pipx
    has_uv = shutil.which("uv") is not None
    has_pipx = shutil.which("pipx") is not None
    if has_uv or has_pipx:
        tool_name = "uv" if has_uv else "pipx"
        results.append(
            CheckResult(
                id="tools.uv_pipx",
                title="Python tool runner (uv/pipx)",
                status="PASS",
                message=f"Found {tool_name} package manager",
            )
        )
    else:
        results.append(
            CheckResult(
                id="tools.uv_pipx",
                title="Python tool runner (uv/pipx)",
                status="WARN",
                message="Neither 'uv' nor 'pipx' found in PATH",
                fix="Install uv (curl -LsSf https://astral.sh/uv/install.sh | sh) or pipx",
            )
        )

    # Helper for CLI tools
    def check_cli(
        name: str,
        cmd: list[str],
        version_pattern: str,
        min_ver: str,
        install_fix: str,
        title: str,
    ) -> CheckResult:
        if not shutil.which(name):
            return CheckResult(
                id=f"tools.{name}",
                title=title,
                status="FAIL",
                message=f"'{name}' executable not found in PATH",
                fix=install_fix,
            )
        try:
            out = run_command(cmd, timeout=5.0).stdout
            match = re.search(version_pattern, out)
            if match:
                found_ver = match.group(1).lstrip("v")
                if min_ver and _parse_semver(found_ver) < _parse_semver(min_ver):
                    return CheckResult(
                        id=f"tools.{name}",
                        title=title,
                        status="WARN",
                        message=f"'{name}' version {found_ver} is older than pinned {min_ver}",
                        fix=f"Upgrade {name} to version {min_ver}+",
                    )
                return CheckResult(
                    id=f"tools.{name}",
                    title=title,
                    status="PASS",
                    message=f"'{name}' version {found_ver} (ok)",
                )
            return CheckResult(
                id=f"tools.{name}",
                title=title,
                status="PASS",
                message=f"'{name}' is installed",
            )
        except Exception as e:
            return CheckResult(
                id=f"tools.{name}",
                title=title,
                status="FAIL",
                message=f"Failed to check {name}: {e}",
                fix=install_fix,
            )

    # 3. Ansible
    ansible_min = pinned.get("ansible", "2.15")
    results.append(
        check_cli(
            "ansible-playbook",
            ["ansible-playbook", "--version"],
            r"ansible-playbook\s*(?:\[core\s*)?([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
            ansible_min,
            "Install ansible-core: pip install 'ansible-core>=2.16'",
            "Ansible automation engine",
        )
    )

    # 4. Helm
    helm_min = pinned.get("helm", "3.10")
    results.append(
        check_cli(
            "helm",
            ["helm", "version", "--short"],
            r"v?([0-9]+\.[0-9]+\.[0-9]+)",
            helm_min,
            "Install Helm v3: https://helm.sh/docs/intro/install/",
            "Helm package manager",
        )
    )

    # 5. Kubectl
    kubectl_min = pinned.get("kubectl", "1.25")
    results.append(
        check_cli(
            "kubectl",
            ["kubectl", "version", "--client"],
            r"Client Version:\s*v?([0-9]+\.[0-9]+\.[0-9]+)",
            kubectl_min,
            "Install kubectl: https://kubernetes.io/docs/tasks/tools/",
            "Kubernetes CLI (kubectl)",
        )
    )

    # 6. Make
    results.append(
        check_cli(
            "make",
            ["make", "--version"],
            r"GNU Make\s+([0-9]+\.[0-9]+)",
            "3.81",
            "Install GNU make (e.g. sudo apt install build-essential)",
            "GNU Make",
        )
    )

    # 7. Git
    results.append(
        check_cli(
            "git",
            ["git", "--version"],
            r"git version\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
            "2.25",
            "Install git (sudo apt install git)",
            "Git version control",
        )
    )

    # 8. VirtualBox (only if inventory targets local VM)
    inventory_path = repo_root / "ansible" / "inventory" / "local.ini"
    targets_local_vm = True
    if inventory_path.exists():
        inv_text = inventory_path.read_text(encoding="utf-8")
        if "192.168.56." not in inv_text and "devops-server" not in inv_text:
            targets_local_vm = False

    if targets_local_vm:
        vbox_min = pinned.get("virtualbox", "7.0")
        results.append(
            check_cli(
                "VBoxManage",
                ["VBoxManage", "--version"],
                r"^([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
                vbox_min,
                (
                    "Install VirtualBox: https://www.virtualbox.org/wiki/Downloads or see "
                    "docs/runbook.md#1-local-vm-hardware--network-specifications"
                ),
                "VirtualBox hypervisor",
            )
        )
    else:
        results.append(
            CheckResult(
                id="tools.VBoxManage",
                title="VirtualBox hypervisor",
                status="SKIP",
                message="Skipped: inventory does not target local VirtualBox VM",
            )
        )

    return results
