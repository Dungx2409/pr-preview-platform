"""Pytest configuration and fixtures for demo app tests."""

import sys
from pathlib import Path

# Ensure demo-app/src is on sys.path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest
from database import reset_db_connection
from fastapi.testclient import TestClient
from main import app


@pytest.fixture(autouse=True)
def clean_env_and_db(monkeypatch):
    """Reset database state and environment variables before and after each test."""
    reset_db_connection()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.delenv("ENV_NAME", raising=False)
    monkeypatch.delenv("PR_NUMBER", raising=False)
    monkeypatch.delenv("GIT_SHA", raising=False)
    yield
    reset_db_connection()


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app) as test_client:
        yield test_client
