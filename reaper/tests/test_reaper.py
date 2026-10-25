"""Unit tests for the Reaper safety-net worker (T-5.1)."""

from __future__ import annotations

import json
from datetime import timezone
from unittest.mock import MagicMock, patch

from reaper import K8sClient, get_open_preview_prs, parse_rfc3339, reap_cycle


def test_parse_rfc3339() -> None:
    ts = "2026-10-25T05:46:02Z"
    dt = parse_rfc3339(ts)
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 25
    assert dt.hour == 5
    assert dt.minute == 46
    assert dt.second == 2
    assert dt.tzinfo == timezone.utc


def test_get_open_preview_prs() -> None:
    mock_response = [
        {"number": 10, "labels": [{"name": "preview"}, {"name": "bug"}]},
        {"number": 11, "labels": [{"name": "documentation"}]},
        {"number": 12, "labels": [{"name": "preview"}]},
    ]
    json_bytes = json.dumps(mock_response).encode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json_bytes
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        prs = get_open_preview_prs("Dungx2409/pr-preview-platform", "mock-token")
        assert prs == {10, 12}


def test_reap_cycle_dry_run_orphan() -> None:
    mock_k8s = MagicMock(spec=K8sClient)
    # Cluster has pr-10 (valid open PR) and pr-99 (closed/orphan PR)
    mock_k8s.list_namespaces.return_value = [
        {"metadata": {"name": "default"}},
        {"metadata": {"name": "pr-10", "creationTimestamp": "2026-10-25T05:00:00Z"}},
        {"metadata": {"name": "pr-99", "creationTimestamp": "2026-10-25T04:00:00Z"}},
    ]
    mock_k8s.list_argo_applications.return_value = [
        {"metadata": {"name": "preview-pr-10"}},
        {"metadata": {"name": "preview-pr-99"}},
    ]
    mock_k8s.list_tailscale_proxy_pods.return_value = []

    with patch("reaper.get_open_preview_prs", return_value={10}):
        summary = reap_cycle(
            k8s=mock_k8s,
            github_repo="test/repo",
            github_token="fake",
            ttl_hours=24.0,
            dry_run=True,
        )

    assert summary["scanned"] == 2
    assert summary["candidates"] == 1
    assert summary["reaped"] == 1
    # Verify no deletions in dry-run
    mock_k8s.delete_namespace.assert_not_called()
    mock_k8s.delete_argo_application.assert_not_called()


def test_reap_cycle_active_delete_orphan() -> None:
    mock_k8s = MagicMock(spec=K8sClient)
    mock_k8s.list_namespaces.return_value = [
        {"metadata": {"name": "pr-99", "creationTimestamp": "2026-10-25T04:00:00Z"}},
    ]
    mock_k8s.list_argo_applications.return_value = [
        {"metadata": {"name": "preview-pr-99"}},
    ]
    mock_k8s.list_tailscale_proxy_pods.return_value = []

    with patch("reaper.get_open_preview_prs", return_value=set()):
        summary = reap_cycle(
            k8s=mock_k8s,
            github_repo="test/repo",
            github_token="fake",
            ttl_hours=24.0,
            dry_run=False,
        )

    assert summary["scanned"] == 1
    assert summary["candidates"] == 1
    assert summary["reaped"] == 1
    # Verify deletions executed in active mode
    mock_k8s.delete_argo_application.assert_called_once_with("preview-pr-99", namespace="argocd")
    mock_k8s.delete_namespace.assert_called_once_with("pr-99")


def test_reap_cycle_ttl_expired() -> None:
    mock_k8s = MagicMock(spec=K8sClient)
    # PR 10 is open, but created 48 hours ago (TTL is 24h)
    mock_k8s.list_namespaces.return_value = [
        {"metadata": {"name": "pr-10", "creationTimestamp": "2026-10-20T00:00:00Z"}},
    ]
    mock_k8s.list_argo_applications.return_value = []
    mock_k8s.list_tailscale_proxy_pods.return_value = []

    with patch("reaper.get_open_preview_prs", return_value={10}):
        summary = reap_cycle(
            k8s=mock_k8s,
            github_repo="test/repo",
            github_token="fake",
            ttl_hours=24.0,
            dry_run=True,
        )

    assert summary["scanned"] == 1
    assert summary["candidates"] == 1
    assert summary["reaped"] == 1


def test_reap_cycle_stale_tailscale_proxy() -> None:
    mock_k8s = MagicMock(spec=K8sClient)
    mock_k8s.list_namespaces.return_value = [
        {"metadata": {"name": "pr-10", "creationTimestamp": "2026-10-25T05:00:00Z"}},
    ]
    mock_k8s.list_argo_applications.return_value = []
    # Proxy pod for pr-88 exists even though namespace pr-88 is completely gone
    mock_k8s.list_tailscale_proxy_pods.return_value = [
        {"metadata": {"name": "ts-preview-pr-10-app-abc-0"}},
        {"metadata": {"name": "ts-preview-pr-88-app-xyz-0"}},
    ]

    with patch("reaper.get_open_preview_prs", return_value={10}):
        summary = reap_cycle(
            k8s=mock_k8s,
            github_repo="test/repo",
            github_token="fake",
            ttl_hours=24.0,
            dry_run=True,
        )

    assert summary["scanned"] == 1
    assert summary["candidates"] == 0
    assert summary["stale_proxies"] == 1
