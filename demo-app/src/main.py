"""FastAPI Demo Application for PR Preview Platform.

Implements the contract defined in SPEC §6.6:
- GET /        -> JSON {env, pr, sha, hostname, db: "ok"|"error"}
- GET /healthz -> 200 (liveness probe, no DB check)
- GET /readyz  -> 200/503 (readiness probe, checks DB)
- GET /counter -> read counter value from DB
- POST /counter -> increment counter value in DB
"""

import os
import socket
from contextlib import asynccontextmanager

from database import check_db, get_counter, increment_counter, init_db
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel


class RootResponse(BaseModel):
    env: str
    pr: str
    sha: str
    hostname: str
    db: str


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    db: str


class CounterResponse(BaseModel):
    counter: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager."""
    init_db()
    yield


app = FastAPI(
    title="PR Preview Demo App",
    description="FastAPI service for validating isolated PR preview environments.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", response_model=RootResponse)
def get_root():
    """Environment details and service status."""
    env_name = os.getenv("ENV_NAME", "development")
    pr_number = os.getenv("PR_NUMBER", "local")
    git_sha = os.getenv("GIT_SHA", "unknown")
    hostname = socket.gethostname()
    db_status = "ok" if check_db() else "error"

    return RootResponse(
        env=env_name,
        pr=pr_number,
        sha=git_sha,
        hostname=hostname,
        db=db_status,
    )


@app.get("/healthz", response_model=HealthResponse)
def get_healthz():
    """Liveness probe: verifies web server process is responsive."""
    return HealthResponse(status="ok")


@app.get("/readyz", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
def get_readyz():
    """Readiness probe: verifies backing database connectivity."""
    if check_db():
        return ReadyResponse(status="ready", db="ok")

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"status": "not ready", "db": "error"},
    )


@app.get("/counter", response_model=CounterResponse)
def read_counter():
    """Read isolated environment counter value."""
    try:
        val = get_counter()
        return CounterResponse(counter=val)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unavailable: {str(e)}",
        ) from e


@app.post("/counter", response_model=CounterResponse)
def update_counter():
    """Increment isolated environment counter value."""
    try:
        val = increment_counter()
        return CounterResponse(counter=val)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unavailable: {str(e)}",
        ) from e
