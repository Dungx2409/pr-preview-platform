"""Unit tests for PR Preview Platform Exporter (T-6.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError

import pytest

from exporter import (
    K8sClient,
    PreviewCollector,
    PreviewMetrics,
    format_prometheus,
    parse_rfc3339,
)


class MockK8sClient(K8sClient):
    """Mock Kubernetes API client returning pre-configured fixture data."""

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        super().__init__(api_server="http://mock-k8s")
        self.routes = routes or {}

    def get(self, path: str) -> dict[str, Any]:
        if path in self.routes:
            val = self.routes[path]
            if isinstance(val, Exception):
                raise val
            return val
        return {"items": []}


def test_parse_rfc3339() -> None:
    dt = parse_rfc3339("2026-10-26T10:00:00Z")
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 26
    assert dt.hour == 10
    assert dt.tzinfo == timezone.utc

    dt_offset = parse_rfc3339("2026-10-26T17:00:00+07:00")
    assert dt_offset.hour == 17


def test_format_prometheus() -> None:
    metrics = PreviewMetrics(
        active_total=2,
        age_seconds={"15": 3600.0, "26": 120.5},
        ready_seconds={"15": 45.2, "26": 38.0},
        reaped_total=3,
        scrape_duration_seconds=0.012345,
        scrape_success=True,
    )
    rendered = format_prometheus(metrics)

    assert "# HELP preview_active_total Total number of active PR preview environments" in rendered
    assert "# TYPE preview_active_total gauge" in rendered
    assert "preview_active_total 2" in rendered
    assert 'preview_age_seconds{pr="15"} 3600.0' in rendered
    assert 'preview_age_seconds{pr="26"} 120.5' in rendered
    assert 'preview_ready_seconds{pr="15"} 45.2' in rendered
    assert 'preview_ready_seconds{pr="26"} 38.0' in rendered
    assert "preview_reaped_total 3" in rendered
    assert "preview_exporter_scrape_duration_seconds 0.012345" in rendered
    assert "preview_exporter_up 1" in rendered


def test_preview_collector_empty() -> None:
    client = MockK8sClient(
        {
            "/api/v1/namespaces": {
                "items": [
                    {"metadata": {"name": "default"}},
                    {"metadata": {"name": "kube-system"}},
                    {"metadata": {"name": "shared"}},
                ]
            }
        }
    )
    collector = PreviewCollector(client)
    metrics = collector.collect()

    assert metrics.active_total == 0
    assert metrics.age_seconds == {}
    assert metrics.ready_seconds == {}
    assert metrics.scrape_success is True


def test_preview_collector_active_previews() -> None:
    now = datetime(2026, 10, 26, 10, 10, 0, tzinfo=timezone.utc)
    client = MockK8sClient(
        {
            "/api/v1/namespaces": {
                "items": [
                    {
                        "metadata": {
                            "name": "pr-42",
                            "creationTimestamp": "2026-10-26T10:00:00Z",
                        }
                    },
                    {
                        "metadata": {
                            "name": "pr-99",
                            "creationTimestamp": "2026-10-26T10:05:00Z",
                        }
                    },
                    {"metadata": {"name": "shared"}},
                ]
            },
            "/apis/apps/v1/namespaces/pr-42/deployments": {
                "items": [
                    {
                        "metadata": {
                            "name": "pr-42-app",
                            "labels": {"app.kubernetes.io/component": "app"},
                        },
                        "status": {
                            "conditions": [
                                {
                                    "type": "Available",
                                    "status": "True",
                                    "lastTransitionTime": "2026-10-26T10:00:45Z",
                                }
                            ]
                        },
                    }
                ]
            },
            "/apis/apps/v1/namespaces/pr-99/deployments": {
                "items": [
                    {
                        "metadata": {
                            "name": "pr-99-app",
                            "labels": {"app.kubernetes.io/component": "app"},
                        },
                        "status": {
                            "conditions": [
                                # Still progressing, not yet Available
                                {
                                    "type": "Progressing",
                                    "status": "True",
                                    "lastTransitionTime": "2026-10-26T10:05:10Z",
                                }
                            ]
                        },
                    }
                ]
            },
        }
    )

    collector = PreviewCollector(client)
    collector.record_reaped(5)
    metrics = collector.collect(now=now)

    assert metrics.active_total == 2
    # pr-42: 10:10:00 - 10:00:00 = 600s
    assert metrics.age_seconds["42"] == pytest.approx(600.0, 0.1)
    # pr-42 time to ready: 10:00:45 - 10:00:00 = 45s
    assert metrics.ready_seconds["42"] == pytest.approx(45.0, 0.1)
    # pr-99: 10:10:00 - 10:05:00 = 300s
    assert metrics.age_seconds["99"] == pytest.approx(300.0, 0.1)
    # pr-99 not yet Available -> omitted from ready_seconds
    assert "99" not in metrics.ready_seconds
    assert metrics.reaped_total == 5
    assert metrics.scrape_success is True


def test_preview_collector_api_failure_fallback() -> None:
    client = MockK8sClient(
        {
            "/api/v1/namespaces": URLError("Connection refused"),
        }
    )
    collector = PreviewCollector(client)
    metrics = collector.collect()

    assert metrics.active_total == 0
    assert metrics.scrape_success is False


def test_preview_collector_configmap_sync() -> None:
    client = MockK8sClient(
        {
            "/api/v1/namespaces": {"items": []},
            "/api/v1/namespaces/monitoring/configmaps/preview-exporter-stats": {
                "data": {"reaped_total": "14"}
            },
        }
    )
    collector = PreviewCollector(client)
    metrics = collector.collect()

    assert metrics.reaped_total == 14
