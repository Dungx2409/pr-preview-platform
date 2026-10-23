"""Pytest configuration and fixtures for demo app tests."""

import os
from pathlib import Path
import sys

# Ensure demo-app/src is on sys.path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest
from fastapi.testclient import TestClient

from database import reset_db_connection
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
