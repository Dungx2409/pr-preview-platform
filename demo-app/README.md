# Demo App (`demo-app`)

A lightweight FastAPI service designed for PR Preview environments. It provides health checks, environment introspection, and per-environment database state isolation verification using PostgreSQL (or SQLite for testing).

## Contract (SPEC §6.6)

| Method | Path | Description | Expected Status |
|---|---|---|---|
| `GET` | `/` | Returns JSON `{env, pr, sha, hostname, db: "ok" \| "error"}` | `200 OK` |
| `GET` | `/healthz` | Liveness probe (process responsive, no DB check) | `200 OK` |
| `GET` | `/readyz` | Readiness probe (verifies DB connection) | `200 OK` / `503 Service Unavailable` |
| `GET` | `/counter` | Reads current isolated counter value from DB | `200 OK` / `503 Service Unavailable` |
| `POST` | `/counter` | Increments counter value atomically in DB | `200 OK` / `503 Service Unavailable` |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ENV_NAME` | `development` | Target environment label (e.g. `shared`, `pr-12`) |
| `PR_NUMBER` | `local` | PR number associated with this preview |
| `GIT_SHA` | `unknown` | Commit SHA of the deployed image |
| `DATABASE_URL` | *(none)* | Full database connection string (PostgreSQL or SQLite) |
| `DB_HOST` | *(none)* | PostgreSQL server host (alternative to `DATABASE_URL`) |
| `DB_PORT` | `5432` | PostgreSQL server port |
| `DB_USER` | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | *(none)* | PostgreSQL password |
| `DB_NAME` | `postgres` | PostgreSQL database name |

## Running Locally

### With Python
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Run unit tests
pytest -v tests/

# Run web server
uvicorn main:app --host 0.0.0.0 --port 8000
```

### With Docker
```bash
docker build -t demo-app:local .
docker run --rm -p 8000:8000 \
  -e ENV_NAME=local-test \
  -e PR_NUMBER=0 \
  -e GIT_SHA=abc1234 \
  demo-app:local
```
