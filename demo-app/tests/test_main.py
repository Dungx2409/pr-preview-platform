"""Unit tests for FastAPI demo app validating SPEC §6.6 requirements."""

import pytest
from database import init_db
from fastapi.testclient import TestClient


def test_healthz(client: TestClient):
    """GET /healthz returns 200 without DB check."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_default_no_db(client: TestClient):
    """GET / with default env vars and no database configured."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["env"] == "development"
    assert data["pr"] == "local"
    assert data["sha"] == "unknown"
    assert "hostname" in data and len(data["hostname"]) > 0
    assert data["db"] == "error"


def test_readyz_fails_when_no_db(client: TestClient):
    """GET /readyz returns 503 when DB is not configured or offline."""
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["detail"] == {"status": "not ready", "db": "error"}


def test_counter_fails_when_no_db(client: TestClient):
    """GET /counter and POST /counter return 503 when DB is not configured."""
    get_res = client.get("/counter")
    assert get_res.status_code == 503

    post_res = client.post("/counter")
    assert post_res.status_code == 503


def test_with_active_database(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Verify full contract with an active SQLite in-memory database."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ENV_NAME", "pr-42")
    monkeypatch.setenv("PR_NUMBER", "42")
    monkeypatch.setenv("GIT_SHA", "abcdef123456")

    # Initialize schema
    assert init_db() is True

    # Check root endpoint
    root_res = client.get("/")
    assert root_res.status_code == 200
    root_data = root_res.json()
    assert root_data["env"] == "pr-42"
    assert root_data["pr"] == "42"
    assert root_data["sha"] == "abcdef123456"
    assert root_data["db"] == "ok"

    # Check readiness probe
    ready_res = client.get("/readyz")
    assert ready_res.status_code == 200
    assert ready_res.json() == {"status": "ready", "db": "ok"}

    # Counter initially 0
    counter_res = client.get("/counter")
    assert counter_res.status_code == 200
    assert counter_res.json() == {"counter": 0}

    # Increment counter: 1
    inc1 = client.post("/counter")
    assert inc1.status_code == 200
    assert inc1.json() == {"counter": 1}

    # Increment counter: 2
    inc2 = client.post("/counter")
    assert inc2.status_code == 200
    assert inc2.json() == {"counter": 2}

    # Fetch counter: still 2
    counter_res2 = client.get("/counter")
    assert counter_res2.status_code == 200
    assert counter_res2.json() == {"counter": 2}


def test_liveness_remains_ok_even_if_db_unreachable(client: TestClient):
    """Liveness probe /healthz must return 200 regardless of DB availability."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
