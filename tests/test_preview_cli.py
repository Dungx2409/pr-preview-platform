"""Unit tests for preview_cli (init and doctor commands, checks, and utilities).

Zero network or cluster access. All external calls are mocked.
"""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.preview_cli.checks.cluster import check_cluster
from scripts.preview_cli.checks.config import check_config
from scripts.preview_cli.checks.ghcr import check_ghcr
from scripts.preview_cli.checks.github import check_github
from scripts.preview_cli.checks.host import check_host
from scripts.preview_cli.checks.secrets import check_secrets
from scripts.preview_cli.checks.tailscale import check_tailscale
from scripts.preview_cli.checks.tools import check_tools
from scripts.preview_cli.doctor_cmd import run_doctor
from scripts.preview_cli.init_cmd import run_init
from scripts.preview_cli.util import (
    atomic_write,
    parse_pinned_versions,
    parse_simple_yaml,
    redact_secrets,
    render_k8s_secret,
    update_inventory_host,
    update_values_yaml,
    update_workflow_tailnet,
)


def test_redact_secrets_patterns() -> None:
    # GitHub Classic and Fine-Grained Tokens (dynamically built to avoid gitleaks false positives)
    fake_pat_prefix = "gh" + "p_"
    fake_token = fake_pat_prefix + "1" * 36
    fake_pat_fine = "github_pat_" + "1" * 82
    sample = f"Token is {fake_token} and pat {fake_pat_fine}"
    redacted = redact_secrets(sample)
    assert fake_pat_prefix not in redacted
    assert "github_pat_" not in redacted
    assert "[REDACTED]" in redacted

    # Tailscale keys & Bearer tokens
    sample_ts = (
        "Tailscale key: tskey-client-1234567890abcdef and "
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    )
    redacted_ts = redact_secrets(sample_ts)
    assert "tskey-" not in redacted_ts
    assert "[REDACTED]" in redacted_ts

    # Basic Auth in URLs
    sample_url = "Clone from https://user:super_secret_password@github.com/org/repo.git"
    redacted_url = redact_secrets(sample_url)
    assert "super_secret_password" not in redacted_url
    assert "https://user:[REDACTED]@github.com" in redacted_url


def test_redact_secrets_explicit() -> None:
    secret_val = "SuperCustomSensitiveString987"
    text = f"Error connecting with password: {secret_val}"
    redacted = redact_secrets(text, extra_secrets=[secret_val])
    assert secret_val not in redacted
    assert "[REDACTED]" in redacted


def test_parse_pinned_versions(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    md_content = """
| Component | Pinned Version | Notes |
|---|---|---|
| **Python** | `3.10.12` | Python base |
| **Ansible Core** | `2.16.19` | Automation |
| **ansible-lint** | `26.10.1` | Linter |
| **VirtualBox** | `7.2.10r174163` | Hypervisor |
| **kubectl** | `v1.35.9` | CLI |
| **Helm** | `v3.22.1` | Package manager |
"""
    (docs_dir / "versions.md").write_text(md_content, encoding="utf-8")
    versions = parse_pinned_versions(tmp_path)
    assert versions["python"] == "3.10.12"
    assert versions["ansible"] == "2.16.19"
    assert versions["virtualbox"] == "7.2.10"
    assert versions["kubectl"] == "1.35.9"
    assert versions["helm"] == "3.22.1"


def test_parse_simple_yaml() -> None:
    yaml_text = """
repo:
  url: "https://github.com/foo/bar.git"
  label: "preview"
app:
  name: "test-app"
  port: 8080
  healthcheck: "/health"
namespace:
  prefix: "test"
"""
    parsed = parse_simple_yaml(yaml_text)
    assert parsed["repo"]["url"] == "https://github.com/foo/bar.git"
    assert parsed["app"]["port"] == 8080
    assert parsed["app"]["healthcheck"] == "/health"
    assert parsed["namespace"]["prefix"] == "test"


def test_update_values_yaml() -> None:
    baseline = """
# Root Config
repo:
  url: "https://github.com/old/repo.git"
  label: "preview"

app:
  # App name
  name: "old-app"
  image: "ghcr.io/old/app"
  port: 8000
  healthcheck: "/healthz"

namespace:
  prefix: "preview"

tailnet:
  name: "old.ts.net"
"""
    updates = {
        "repo_url": "https://github.com/new/project.git",
        "app_name": "new-app",
        "app_image": "ghcr.io/new/new-app",
        "app_port": 9000,
        "app_healthcheck": "/ready",
        "ns_prefix": "staging",
        "tailnet_name": "new.ts.net",
    }
    result = update_values_yaml(baseline, updates)
    assert 'url: "https://github.com/new/project.git"' in result
    assert 'name: "new-app"' in result
    assert 'image: "ghcr.io/new/new-app"' in result
    assert "port: 9000" in result
    assert 'healthcheck: "/ready"' in result
    assert 'prefix: "staging"' in result
    assert 'name: "new.ts.net"' in result
    assert "# App name" in result  # Preserved comments


def test_update_workflow_tailnet() -> None:
    wf = """
name: Preview
permissions:
  contents: read
env:
  TAILNET_NAME: old.ts.net

jobs:
  test:
    runs-on: ubuntu-latest
"""
    updated = update_workflow_tailnet(wf, "custom-tailnet.ts.net")
    assert "TAILNET_NAME: custom-tailnet.ts.net" in updated
    assert "old.ts.net" not in updated


def test_update_inventory_host() -> None:
    inv = """
[k3s_server]
devops-server ansible_host=192.168.56.10

[all:vars]
ansible_user=vboxuser
"""
    updated = update_inventory_host(inv, "10.0.0.50", "admin")
    assert "ansible_host=10.0.0.50" in updated
    assert "ansible_user=admin" in updated


def test_render_k8s_secret() -> None:
    manifest = render_k8s_secret(
        "test-secret",
        "my-ns",
        {"key1": "value1", "pass": 'has"quotes'},
    )
    assert "kind: Secret" in manifest
    assert "name: test-secret" in manifest
    assert "namespace: my-ns" in manifest
    assert 'key1: "value1"' in manifest
    assert 'pass: "has\\"quotes"' in manifest


def test_atomic_write_and_backup(tmp_path: Path) -> None:
    target = tmp_path / "config.txt"
    target.write_text("initial content", encoding="utf-8")

    atomic_write(target, "new content", mode=0o600, backup=True)
    assert target.read_text(encoding="utf-8") == "new content"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600

    bak = tmp_path / "config.txt.bak"
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == "initial content"


def test_check_tools_mocked(tmp_path: Path) -> None:
    # Mock all CLI tools to return valid versions per tool
    def mock_cmd(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        tool = cmd[0]
        outs = {
            "ansible-playbook": "ansible-playbook [core 2.16.5]",
            "helm": "v3.25.0",
            "kubectl": "Client Version: v1.35.0",
            "make": "GNU Make 4.3",
            "git": "git version 2.34.1",
            "VBoxManage": "7.2.10",
        }
        return subprocess.CompletedProcess(cmd, 0, stdout=outs.get(tool, ""))

    with (
        patch("shutil.which", return_value="/usr/bin/tool"),
        patch(
            "scripts.preview_cli.checks.tools.run_command",
            side_effect=mock_cmd,
        ),
    ):
        results = check_tools(tmp_path)
        statuses = {r.id: r.status for r in results}
        assert statuses["tools.python"] == "PASS"
        assert statuses["tools.uv_pipx"] == "PASS"
        assert statuses["tools.kubectl"] == "PASS"
        assert statuses["tools.helm"] == "PASS"
        assert statuses["tools.make"] == "PASS"
        assert statuses["tools.git"] == "PASS"


def test_check_config_valid_and_invalid(tmp_path: Path) -> None:
    # 1. Missing values.yaml
    res_missing = check_config(tmp_path)
    assert any(r.status == "FAIL" for r in res_missing)

    # 2. Invalid fields in values.yaml
    bad_values = tmp_path / "values.yaml"
    bad_values.write_text(
        """
repo:
  url: "invalid-url"
app:
  image: "docker.io/bad/image"
  port: -5
  healthcheck: "no-slash"
namespace:
  prefix: "BAD_PREFIX_WITH_CAPS!"
tailnet:
  name: "<tailnet-name>.ts.net"
""",
        encoding="utf-8",
    )
    res_bad = check_config(tmp_path)
    bad_ids = {r.id: r.status for r in res_bad}
    assert bad_ids["config.repo_url"] == "FAIL"
    assert bad_ids["config.app_image"] == "FAIL"
    assert bad_ids["config.app_port"] == "FAIL"
    assert bad_ids["config.healthcheck"] == "FAIL"
    assert bad_ids["config.namespace_prefix"] == "FAIL"
    assert bad_ids["config.workflow_tailnet"] == "FAIL"


def test_check_secrets_dir_and_permissions(tmp_path: Path) -> None:
    sec_dir = tmp_path / "dr-secrets"
    sec_dir.mkdir(mode=0o700)

    # Missing files -> FAIL
    res_empty = check_secrets(secrets_dir=sec_dir)
    assert any(r.status == "FAIL" for r in res_empty)

    # Insecure directory mode -> FAIL
    os.chmod(sec_dir, 0o777)
    res_insecure_dir = check_secrets(secrets_dir=sec_dir)
    assert any(r.id == "secrets.dir_permissions" and r.status == "FAIL" for r in res_insecure_dir)

    # Valid directory & files
    os.chmod(sec_dir, 0o700)
    dummy_tok = "gh" + "p_" + "A" * 36
    for fname, content in [
        ("operator-oauth.yaml", "stringData:\n  client_id: foo\n  client_secret: bar\n"),
        ("github-token.yaml", f"stringData:\n  token: {dummy_tok}\n"),
        ("shared-postgres.yaml", "stringData:\n  password: secretpass\n"),
    ]:
        f = sec_dir / fname
        f.write_text(content, encoding="utf-8")
        os.chmod(f, 0o600)

    res_valid = check_secrets(secrets_dir=sec_dir)
    assert all(r.status == "PASS" for r in res_valid)


def test_check_github_offline_and_mock(tmp_path: Path) -> None:
    # Offline mode returns SKIP
    res_offline = check_github(tmp_path, offline=True)
    assert res_offline[0].status == "SKIP"

    # Mock token in env
    values = tmp_path / "values.yaml"
    values.write_text("repo:\n  url: 'https://github.com/my-org/my-repo.git'\n", encoding="utf-8")

    mock_gh_token = "gh" + "p_" + "M" * 36
    with patch.dict(os.environ, {"GITHUB_TOKEN": mock_gh_token}):
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.headers = {"x-ratelimit-remaining": "4950"}
            payload = {"login": "testuser", "full_name": "my-org/my-repo"}
            mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
            mock_url.return_value.__enter__.return_value = mock_resp

            results = check_github(tmp_path, offline=False)
            token_res = next(r for r in results if r.id == "github.token")
            assert token_res.status == "PASS"
            assert "@testuser" in token_res.message


def test_check_ghcr_mock(tmp_path: Path) -> None:
    values = tmp_path / "values.yaml"
    values.write_text("app:\n  image: 'ghcr.io/my-org/my-app'\n", encoding="utf-8")

    # Offline -> SKIP
    assert check_ghcr(tmp_path, offline=True)[0].status == "SKIP"

    # Mock public 200 responses
    with patch("urllib.request.urlopen") as mock_url:
        resp_token = MagicMock()
        resp_token.status = 200
        resp_token.read.return_value = json.dumps({"token": "anon-pull-token"}).encode("utf-8")

        resp_tags = MagicMock()
        resp_tags.status = 200
        resp_tags.read.return_value = json.dumps({"tags": ["v1.0.0"]}).encode("utf-8")

        resp_head = MagicMock()
        resp_head.status = 200

        mock_url.return_value.__enter__.side_effect = [resp_token, resp_tags, resp_head]

        res = check_ghcr(tmp_path, offline=False)
        assert res[0].status == "PASS"
        assert "Public and pullable" in res[0].message


def test_check_tailscale_mock(tmp_path: Path) -> None:
    values = tmp_path / "values.yaml"
    values.write_text("tailnet:\n  name: 'my-team.ts.net'\n", encoding="utf-8")

    with patch.dict(os.environ, {"TS_OAUTH_CLIENT_ID": "cid", "TS_OAUTH_CLIENT_SECRET": "csec"}):
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.status = 200
            token_payload = {"access_token": "ts-token-123"}
            mock_resp.read.return_value = json.dumps(token_payload).encode("utf-8")
            mock_url.return_value.__enter__.return_value = mock_resp

            with patch("shutil.which", return_value=None):
                results = check_tailscale(tmp_path, offline=False)
                oauth_res = next(r for r in results if r.id == "tailscale.oauth")
                assert oauth_res.status == "PASS"
                assert "ts-token-123" not in oauth_res.message


def test_check_host_mock(tmp_path: Path) -> None:
    inv_dir = tmp_path / "ansible" / "inventory"
    inv_dir.mkdir(parents=True)
    inv_file = inv_dir / "local.ini"
    inv_file.write_text("[k3s_server]\ndevops-server ansible_host=10.0.0.5\n", encoding="utf-8")

    with patch("scripts.preview_cli.checks.host.is_tcp_port_open", return_value=True):
        with patch("shutil.which", return_value=None):
            results = check_host(tmp_path)
            ssh_res = next(r for r in results if r.id == "host.ssh_port")
            assert ssh_res.status == "PASS"
            assert "10.0.0.5" in ssh_res.message


def test_check_cluster_mock(tmp_path: Path) -> None:
    # Offline or skip_cluster -> SKIP
    assert check_cluster(tmp_path, offline=True)[0].status == "SKIP"
    assert check_cluster(tmp_path, skip_cluster=True)[0].status == "SKIP"

    # Mock kubectl responses
    node_json = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "node-1"},
                    "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                }
            ]
        }
    )
    pod_json = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "app-1"},
                    "status": {"phase": "Running", "containerStatuses": []},
                }
            ]
        }
    )

    with patch("shutil.which", return_value="/usr/bin/kubectl"):
        with patch(
            "scripts.preview_cli.checks.cluster._run_kubectl",
            side_effect=[
                (0, node_json),  # get nodes
                (0, pod_json),  # get pods argocd
                (0, pod_json),  # get pods tailscale
                (0, pod_json),  # get pods monitoring
                (0, pod_json),  # get pods shared
                (0, ""),  # appset
                (0, ""),  # appproject
                (0, ""),  # reaper
                (0, ""),  # secret 1
                (0, ""),  # secret 2
                (0, ""),  # secret 3
                (0, '{"items": []}'),  # namespaces
            ],
        ):
            results = check_cluster(tmp_path)
            node_res = next(r for r in results if r.id == "cluster.node_ready")
            assert node_res.status == "PASS"


def test_doctor_json_output_safe(tmp_path: Path) -> None:
    # Verify --json contains no secret tokens
    secret_pat = "gh" + "p_" + "Z" * 36
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        with patch.dict(os.environ, {"GITHUB_TOKEN": secret_pat}):
            exit_code = run_doctor(tmp_path, offline=True, skip_cluster=True, is_json=True)

    json_text = buf.getvalue()
    data = json.loads(json_text)
    assert secret_pat not in json_text
    assert "status" in data
    assert "checks" in data
    assert exit_code in (0, 1)


def test_init_non_interactive_and_dry_run(tmp_path: Path) -> None:
    # Setup test workspace
    (tmp_path / "values.yaml").write_text("repo:\n  url: 'old'\n", encoding="utf-8")
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "preview.yml").write_text("env:\n  TAILNET_NAME: old\n", encoding="utf-8")
    (wf_dir / "preview-closed.yml").write_text("env:\n  TAILNET_NAME: old\n", encoding="utf-8")
    inv_dir = tmp_path / "ansible" / "inventory"
    inv_dir.mkdir(parents=True)
    inv_content = "[k3s_server]\ndevops-server ansible_host=old\n"
    (inv_dir / "local.ini").write_text(inv_content, encoding="utf-8")

    sec_dir = tmp_path / "secrets"

    env_vars = {
        "PREVIEW_REPO_URL": "https://github.com/org/repo.git",
        "PREVIEW_APP_NAME": "my-app",
        "PREVIEW_IMAGE": "ghcr.io/org/my-app",
        "PREVIEW_PORT": "3000",
        "PREVIEW_HEALTHCHECK": "/api/health",
        "PREVIEW_NS_PREFIX": "prv",
        "PREVIEW_TAILNET": "my-corp.ts.net",
        "PREVIEW_VM_IP": "192.168.1.100",
        "TS_OAUTH_CLIENT_ID": "my-client-id",
        "TS_OAUTH_CLIENT_SECRET": "my-client-secret",
        "GITHUB_TOKEN": "gh" + "p_" + "T" * 36,
    }

    # 1. Dry run writes 0 files
    with patch.dict(os.environ, env_vars):
        rc_dry = run_init(
            repo_root=tmp_path,
            non_interactive=True,
            dry_run=True,
            skip_doctor=True,
            secrets_dir=sec_dir,
        )
        assert rc_dry == 0
        assert not sec_dir.exists()

    # 2. Real non-interactive write
    with patch.dict(os.environ, env_vars):
        rc = run_init(
            repo_root=tmp_path,
            non_interactive=True,
            dry_run=False,
            yes=True,
            skip_doctor=True,
            secrets_dir=sec_dir,
        )
        assert rc == 0
        assert sec_dir.exists()
        assert (sec_dir / "operator-oauth.yaml").exists()
        assert (sec_dir / "github-token.yaml").exists()
        assert (sec_dir / "shared-postgres.yaml").exists()

        # Check values.yaml updated
        val_content = (tmp_path / "values.yaml").read_text(encoding="utf-8")
        assert 'url: "https://github.com/org/repo.git"' in val_content
        assert 'name: "my-app"' in val_content
        assert "port: 3000" in val_content

        # Check workflow updated
        wf_content = (wf_dir / "preview.yml").read_text(encoding="utf-8")
        assert "TAILNET_NAME: my-corp.ts.net" in wf_content

        # Check inventory updated
        inv_content = (inv_dir / "local.ini").read_text(encoding="utf-8")
        assert "ansible_host=192.168.1.100" in inv_content


def test_init_missing_env_vars_fails(tmp_path: Path) -> None:
    # Non-interactive without env vars returns 1
    with patch.dict(os.environ, {}, clear=True):
        rc = run_init(repo_root=tmp_path, non_interactive=True, skip_doctor=True)
        assert rc == 1


def test_init_idempotent(tmp_path: Path) -> None:
    (tmp_path / "values.yaml").write_text("repo:\n  url: 'old'\n", encoding="utf-8")
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "preview.yml").write_text("env:\n  TAILNET_NAME: old\n", encoding="utf-8")
    (wf_dir / "preview-closed.yml").write_text("env:\n  TAILNET_NAME: old\n", encoding="utf-8")
    inv_dir = tmp_path / "ansible" / "inventory"
    inv_dir.mkdir(parents=True)
    (inv_dir / "local.ini").write_text(
        "[k3s_server]\ndevops-server ansible_host=old\n", encoding="utf-8"
    )
    sec_dir = tmp_path / "secrets"

    env_vars = {
        "PREVIEW_REPO_URL": "https://github.com/org/repo.git",
        "PREVIEW_APP_NAME": "my-app",
        "PREVIEW_IMAGE": "ghcr.io/org/my-app",
        "PREVIEW_PORT": "3000",
        "PREVIEW_HEALTHCHECK": "/api/health",
        "PREVIEW_NS_PREFIX": "prv",
        "PREVIEW_TAILNET": "my-corp.ts.net",
        "PREVIEW_VM_IP": "192.168.1.100",
        "TS_OAUTH_CLIENT_ID": "my-client-id",
        "TS_OAUTH_CLIENT_SECRET": "my-client-secret",
        "GITHUB_TOKEN": "gh" + "p_" + "K" * 36,
    }

    with patch.dict(os.environ, env_vars):
        # Run 1
        rc1 = run_init(
            repo_root=tmp_path,
            non_interactive=True,
            yes=True,
            skip_doctor=True,
            secrets_dir=sec_dir,
        )
        assert rc1 == 0
        content1_val = (tmp_path / "values.yaml").read_text(encoding="utf-8")
        content1_wf = (wf_dir / "preview.yml").read_text(encoding="utf-8")

        # Run 2 with identical settings
        rc2 = run_init(
            repo_root=tmp_path,
            non_interactive=True,
            yes=True,
            skip_doctor=True,
            secrets_dir=sec_dir,
        )
        assert rc2 == 0
        content2_val = (tmp_path / "values.yaml").read_text(encoding="utf-8")
        content2_wf = (wf_dir / "preview.yml").read_text(encoding="utf-8")

        # Identical byte content on second run
        assert content1_val == content2_val
        assert content1_wf == content2_wf
