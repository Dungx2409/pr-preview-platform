"""Utility functions for pr-preview CLI tools (init and doctor).

Standard library only. Zero third-party runtime dependencies.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any

# Default path for Disaster Recovery secrets
DEFAULT_SECRETS_DIR = Path.home() / ".config" / "pr-preview" / "dr-secrets"


def redact_secrets(text: str, extra_secrets: list[str] | None = None) -> str:
    """Redact sensitive patterns and specific secret values from text."""
    if not text:
        return ""

    redacted = str(text)

    # Redact explicit strings passed by caller
    if extra_secrets:
        for secret in extra_secrets:
            if secret and len(secret) >= 4:
                redacted = redacted.replace(secret, "[REDACTED]")

    # Common credential patterns
    patterns = [
        # GitHub Personal Access Tokens (classic & fine-grained)
        r"ghp_[a-zA-Z0-9]{36,}",
        r"github_pat_[a-zA-Z0-9_]{82,}",
        r"gho_[a-zA-Z0-9]{36,}",
        # Tailscale API / auth keys
        r"tskey-(?:api|auth)-[a-zA-Z0-9]+",
        r"tskey-client-[a-zA-Z0-9-]+",
        # Generic Authorization / Bearer tokens
        r"(Bearer\s+)[a-zA-Z0-9_\-\.]{15,}",
        # Basic auth user:pass in URLs
        r"(https?://[^:]+:)[^@]+(@)",
        # client_secret query params or json fields
        r'("?client_secret"?\s*[:=]\s*["\'])([^"\']+)("?)',
        r'("?password"?\s*[:=]\s*["\'])([^"\']+)("?)',
        r'("?token"?\s*[:=]\s*["\'])([^"\']+)("?)',
    ]

    for pat in patterns:
        if (
            pat.startswith(r'("?client_secret')
            or pat.startswith(r'("?password')
            or pat.startswith(r'("?token')
        ):
            redacted = re.sub(pat, r"\g<1>[REDACTED]\g<3>", redacted)
        elif pat.startswith(r"(Bearer"):
            redacted = re.sub(pat, r"\g<1>[REDACTED]", redacted)
        elif pat.startswith(r"(https?://"):
            redacted = re.sub(pat, r"\g<1>[REDACTED]\g<2>", redacted)
        else:
            redacted = re.sub(pat, "[REDACTED]", redacted)

    return redacted


def run_command(
    cmd: list[str],
    timeout: float = 10.0,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an external command safely with timeout and redacted exceptions."""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command '{cmd[0]}' timed out after {timeout}s") from exc
    except Exception as exc:
        msg = redact_secrets(str(exc))
        raise RuntimeError(f"Command '{cmd[0]}' failed: {msg}") from exc


def parse_pinned_versions(repo_root: Path) -> dict[str, str]:
    """Extract pinned versions from docs/versions.md tables."""
    versions_file = repo_root / "docs" / "versions.md"
    versions: dict[str, str] = {}
    if not versions_file.exists():
        return versions

    content = versions_file.read_text(encoding="utf-8")
    # Parse rows: | **Tool Name** | `version` | ...
    pattern = re.compile(r"\|\s*\*\*([^*]+)\*\*\s*\|\s*`([^`]+)`\s*\|")
    for match in pattern.finditer(content):
        name = match.group(1).strip().lower()
        version = match.group(2).strip().lstrip("v")
        # Standardize key names
        if "python" in name:
            versions["python"] = version
        elif "ansible core" in name:
            versions["ansible"] = version
        elif "ansible-lint" in name:
            versions["ansible-lint"] = version
        elif "kubectl" in name:
            versions["kubectl"] = version
        elif "helm" in name:
            versions["helm"] = version
        elif "virtualbox" in name:
            # Strip build suffix e.g. 7.2.10r174163 -> 7.2.10
            clean_vb = re.split(r"[a-zA-Z]", version)[0]
            versions["virtualbox"] = clean_vb
        elif "k3s" in name:
            versions["k3s"] = version
        elif "argo" in name:
            versions["argocd"] = version
        elif "tailscale" in name:
            versions["tailscale"] = version
        elif "trivy" in name:
            versions["trivy"] = version
    return versions


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse values.yaml using PyYAML if available, or lightweight stdlib fallback."""
    try:
        import yaml

        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    # Standard-library fallback for values.yaml structure
    res: dict[str, Any] = {}
    current_section = ""

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line or line.startswith("---"):
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if ":" not in stripped:
            continue

        k, v = stripped.split(":", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")

        if indent == 0 and not v:
            current_section = k
            if current_section not in res:
                res[current_section] = {}
        elif indent > 0 and current_section:
            # Handle numeric conversion
            if v.isdigit():
                typed_v: Any = int(v)
            elif v.lower() in ("true", "false"):
                typed_v = v.lower() == "true"
            else:
                typed_v = v
            res[current_section][k] = typed_v

    return res


def load_values_config(repo_root: Path) -> dict[str, Any]:
    """Load configuration from values.yaml."""
    values_path = repo_root / "values.yaml"
    if not values_path.exists():
        return {}
    return parse_simple_yaml(values_path.read_text(encoding="utf-8"))


def atomic_write(path: Path, content: str, mode: int | None = None, backup: bool = True) -> None:
    """Atomically write content to a file, making a .bak copy if existing."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if backup and path.exists():
        bak_path = path.with_name(path.name + ".bak")
        shutil.copy2(path, bak_path)

    # Write to temporary file in same directory for atomic rename
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as tmp:
        tmp.write(content)
        tmp_name = tmp.name

    if mode is not None:
        os.chmod(tmp_name, mode)

    os.replace(tmp_name, path)


def render_k8s_secret(name: str, namespace: str, string_data: dict[str, str]) -> str:
    """Render a Kubernetes Secret manifest with stringData."""
    lines = [
        "---",
        "apiVersion: v1",
        "kind: Secret",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {namespace}",
        "type: Opaque",
        "stringData:",
    ]
    for k, v in string_data.items():
        # Escape value for YAML string
        clean_v = str(v).replace('"', '\\"')
        lines.append(f'  {k}: "{clean_v}"')
    lines.append("")
    return "\n".join(lines)


def update_values_yaml(content: str, updates: dict[str, Any]) -> str:
    """Update values in values.yaml preserving comments and indentation."""
    new_content = content

    mapping = {
        ("repo", "url"): updates.get("repo_url"),
        ("repo", "label"): updates.get("repo_label"),
        ("app", "name"): updates.get("app_name"),
        ("app", "image"): updates.get("app_image"),
        ("app", "port"): updates.get("app_port"),
        ("app", "healthcheck"): updates.get("app_healthcheck"),
        ("namespace", "prefix"): updates.get("ns_prefix"),
        ("tailnet", "name"): updates.get("tailnet_name"),
    }

    for (section, key), val in mapping.items():
        if val is None:
            continue
        # Format string or number
        val_str = f'"{val}"' if isinstance(val, str) else str(val)

        # Regex to locate key under section
        # Finds: section: ... key: <old_val>
        pattern = re.compile(
            rf"(?m)(^{re.escape(section)}:\s*\n"
            rf"(?:[ \t]*#[^\n]*\n)*"
            rf"[ \t]*{re.escape(key)}:\s*)[^\n]+"
        )
        if pattern.search(new_content):
            new_content = pattern.sub(rf"\g<1>{val_str}", new_content)
        else:
            # If section doesn't exist, append it
            if f"\n{section}:" not in new_content and not new_content.startswith(f"{section}:"):
                new_content += f"\n{section}:\n  {key}: {val_str}\n"

    return new_content


def update_workflow_tailnet(content: str, tailnet_name: str) -> str:
    """Update or add TAILNET_NAME in GitHub Actions workflow content."""
    # 1. Update existing env.TAILNET_NAME
    env_pattern = re.compile(r"(?m)(^[ \t]*TAILNET_NAME:\s*)[^\n]+")
    if env_pattern.search(content):
        content = env_pattern.sub(rf"\g<1>{tailnet_name}", content)
    else:
        # Insert env block if missing
        if "env:" in content:
            content = re.sub(
                r"(?m)(^env:\s*\n)",
                rf"\g<1>  TAILNET_NAME: {tailnet_name}\n",
                content,
                count=1,
            )
        else:
            # Insert after permissions: block
            perm_pattern = re.compile(r"(?m)(^permissions:\s*\n(?:[ \t]+[^\n]+\n)+)")
            if perm_pattern.search(content):
                content = perm_pattern.sub(
                    rf"\g<1>\nenv:\n  TAILNET_NAME: {tailnet_name}\n\n",
                    content,
                    count=1,
                )
            else:
                content = f"env:\n  TAILNET_NAME: {tailnet_name}\n\n" + content

    # 2. In preview.yml inline python, also update fallback default if present
    inline_py_pat = re.compile(r"(cfg\.get\('tailnet',\s*\{\}\)\.get\('name',\s*')[^']+('\)\)\))")
    if inline_py_pat.search(content):
        content = inline_py_pat.sub(rf"\g<1>{tailnet_name}\g<2>", content)

    return content


def update_inventory_host(content: str, ip: str, user: str | None = None) -> str:
    """Update host IP and optional SSH user in Ansible inventory content."""
    # Update ansible_host=...
    host_pattern = re.compile(r"(ansible_host=)[^\s\n]+")
    if host_pattern.search(content):
        content = host_pattern.sub(rf"\g<1>{ip}", content)
    else:
        # Append or replace line in k3s_server group
        content = re.sub(
            r"(?m)(^\[k3s_server\]\s*\n\w+\s*)[^\n]*",
            rf"\g<1>ansible_host={ip}",
            content,
        )

    if user:
        user_pattern = re.compile(r"(ansible_user=)[^\s\n]+")
        if user_pattern.search(content):
            content = user_pattern.sub(rf"\g<1>{user}", content)

    return content


def is_tcp_port_open(host: str, port: int, timeout: float = 5.0) -> bool:
    """Check if a TCP port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False
