"""Host and VM connectivity checks (SSH port 22, ICMP ping, Ansible inventory)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from scripts.preview_cli.checks import CheckResult
from scripts.preview_cli.util import is_tcp_port_open, run_command


def _parse_inventory_ip(inv_path: Path) -> str | None:
    if not inv_path.exists():
        return None
    content = inv_path.read_text(encoding="utf-8")
    m = re.search(r"ansible_host=([^\s\n#]+)", content)
    if m:
        return m.group(1).strip()
    return None


def check_host(
    repo_root: Path,
    host_override: str | None = None,
) -> list[CheckResult]:
    """Verify inventory parsing and TCP port 22 reachability to target host/VM."""
    results: list[CheckResult] = []
    inv_path = repo_root / "ansible" / "inventory" / "local.ini"

    target_ip = host_override
    if not target_ip:
        if not inv_path.exists():
            results.append(
                CheckResult(
                    id="host.inventory",
                    title="Ansible inventory",
                    status="FAIL",
                    message="ansible/inventory/local.ini not found",
                    fix="Run 'make init' or copy ansible/inventory/local.ini.example",
                )
            )
            return results

        target_ip = _parse_inventory_ip(inv_path)
        if not target_ip:
            results.append(
                CheckResult(
                    id="host.inventory",
                    title="Ansible inventory IP",
                    status="FAIL",
                    message="Could not find 'ansible_host' in ansible/inventory/local.ini",
                    fix="Specify 'ansible_host=<IP>' in inventory or run 'make init'",
                )
            )
            return results

    # 1. Check Ansible inventory parsing
    if inv_path.exists():
        if shutil.which("ansible-inventory"):
            try:
                res = run_command(
                    ["ansible-inventory", "-i", str(inv_path), "--list"],
                    timeout=5.0,
                )
                if res.returncode == 0:
                    results.append(
                        CheckResult(
                            id="host.inventory",
                            title="Ansible inventory syntax",
                            status="PASS",
                            message="ansible/inventory/local.ini parses cleanly",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            id="host.inventory",
                            title="Ansible inventory syntax",
                            status="FAIL",
                            message="ansible-inventory failed to parse inventory file",
                            fix="Verify syntax of ansible/inventory/local.ini",
                        )
                    )
            except Exception as exc:
                results.append(
                    CheckResult(
                        id="host.inventory",
                        title="Ansible inventory syntax",
                        status="WARN",
                        message=f"Could not validate inventory with ansible-inventory: {exc}",
                        fix="Check ansible installation",
                    )
                )
        else:
            results.append(
                CheckResult(
                    id="host.inventory",
                    title="Ansible inventory file",
                    status="PASS",
                    message="ansible/inventory/local.ini exists (ansible-inventory CLI not found)",
                )
            )

    # 2. Check TCP port 22 reachable
    if is_tcp_port_open(target_ip, 22, timeout=5.0):
        results.append(
            CheckResult(
                id="host.ssh_port",
                title="SSH service connectivity (TCP 22)",
                status="PASS",
                message=f"SSH port 22 is reachable on {target_ip}",
            )
        )
    else:
        results.append(
            CheckResult(
                id="host.ssh_port",
                title="SSH service connectivity (TCP 22)",
                status="FAIL",
                message=f"TCP port 22 unreachable on {target_ip} (connection refused or timeout)",
                fix=(
                    f"Ensure target host ({target_ip}) is running. If using local VirtualBox, "
                    "run: VBoxManage startvm 'devops-server' --type headless. "
                    "See docs/runbook.md#2-day-to-day-operations-headless-cli"
                ),
            )
        )

    # 3. Optional ICMP ping check
    if shutil.which("ping"):
        try:
            ping_res = run_command(["ping", "-c", "1", "-W", "2", target_ip], timeout=3.0)
            if ping_res.returncode == 0:
                results.append(
                    CheckResult(
                        id="host.icmp",
                        title="ICMP Ping connectivity",
                        status="PASS",
                        message=f"Host {target_ip} responds to ICMP ping",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        id="host.icmp",
                        title="ICMP Ping connectivity",
                        status="WARN",
                        message=f"Host {target_ip} did not reply to ICMP ping (may be firewalled)",
                    )
                )
        except Exception:
            pass

    return results
