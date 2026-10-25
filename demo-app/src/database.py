"""Database helper for the PR Preview demo app.

Supports PostgreSQL via psycopg2-binary and SQLite for local development/testing.
Enforces atomic operations for per-environment database isolation verification.
"""

import os
import sqlite3

try:
    import psycopg2
except ImportError:
    psycopg2 = None

_sqlite_conn: sqlite3.Connection | None = None


def get_db_url() -> str | None:
    """Retrieve database connection URL from environment variables."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url

    host = os.getenv("DB_HOST")
    if host:
        port = os.getenv("DB_PORT", "5432")
        user = os.getenv("DB_USER", "postgres")
        password = os.getenv("DB_PASSWORD", "")
        dbname = os.getenv("DB_NAME", "postgres")
        if password:
            return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
        return f"postgresql://{user}@{host}:{port}/{dbname}"

    return None


def _get_connection():
    """Create and return a database connection based on configured URL."""
    db_url = get_db_url()
    if not db_url:
        raise ConnectionError("No database connection configured")

    if db_url.startswith("sqlite://"):
        path = db_url.replace("sqlite://", "")
        if path in (":memory:", "/:memory:"):
            global _sqlite_conn
            if _sqlite_conn is None:
                _sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
            return _sqlite_conn
        return sqlite3.connect(path, check_same_thread=False)

    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is not installed; cannot connect to PostgreSQL")
        return psycopg2.connect(db_url, connect_timeout=3)

    raise ValueError(f"Unsupported database scheme in URL: {db_url}")


def init_db() -> bool:
    """Initialize the schema if needed. Returns True on success, False on failure."""
    try:
        db_url = get_db_url()
        if not db_url:
            return False

        if db_url.startswith("sqlite://"):
            conn = _get_connection()
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS counters (id INT PRIMARY KEY, count INT NOT NULL);"
                )
            return True

        if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
            with _get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS counters "
                        "(id INT PRIMARY KEY, count INT NOT NULL);"
                    )
            return True

        return False
    except Exception:
        return False


def check_db() -> bool:
    """Check database health by running a simple query. Returns True if alive."""
    try:
        db_url = get_db_url()
        if not db_url:
            return False

        if db_url.startswith("sqlite://"):
            conn = _get_connection()
            with conn:
                cur = conn.execute("SELECT 1;")
                return cur.fetchone()[0] == 1

        if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
            with _get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    res = cur.fetchone()
                    return res is not None and res[0] == 1

        return False
    except Exception:
        return False


def get_counter() -> int:
    """Read the current counter value. Returns 0 if no row exists."""
    db_url = get_db_url()
    if not db_url:
        raise ConnectionError("No database configured")

    init_db()

    if db_url.startswith("sqlite://"):
        conn = _get_connection()
        with conn:
            cur = conn.execute("SELECT count FROM counters WHERE id = 1;")
            row = cur.fetchone()
            return row[0] if row else 0

    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        with _get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count FROM counters WHERE id = 1;")
                row = cur.fetchone()
                return row[0] if row else 0

    raise ValueError("Unsupported database connection")


def increment_counter() -> int:
    """Increment and return the counter value atomically."""
    db_url = get_db_url()
    if not db_url:
        raise ConnectionError("No database configured")

    init_db()

    query = (
        "INSERT INTO counters (id, count) VALUES (1, 1) "
        "ON CONFLICT (id) DO UPDATE SET count = counters.count + 1 "
        "RETURNING count;"
    )

    if db_url.startswith("sqlite://"):
        conn = _get_connection()
        with conn:
            cur = conn.execute(query)
            row = cur.fetchone()
            return row[0]

    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        with _get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()
                return row[0]

    raise ValueError("Unsupported database connection")


def reset_db_connection() -> None:
    """Reset database connections (used primarily in test suites)."""
    global _sqlite_conn
    if _sqlite_conn is not None:
        try:
            _sqlite_conn.close()
        except Exception:
            pass
        _sqlite_conn = None
