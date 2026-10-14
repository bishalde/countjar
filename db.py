"""Tiny storage layer: Postgres when DATABASE_URL is set (production), SQLite otherwise (local dev)."""
import os
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS counters (
    namespace  TEXT NOT NULL,
    name       TEXT NOT NULL,
    count      BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (namespace, name)
)
"""


def connect():
    if DATABASE_URL:
        import psycopg

        return psycopg.connect(DATABASE_URL, autocommit=True)
    # Vercel's filesystem is read-only except /tmp (which is wiped between instances).
    default = "/tmp/countjar.db" if os.environ.get("VERCEL") else "countjar.db"
    conn = sqlite3.connect(os.environ.get("SQLITE_PATH", default))
    conn.isolation_level = None  # autocommit
    return conn


def execute(sql, params=()):
    """Run one statement and return all rows. SQL uses %s placeholders."""
    conn = connect()
    try:
        if not DATABASE_URL:
            sql = sql.replace("%s", "?")
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []
    finally:
        conn.close()


def init():
    execute(SCHEMA)


def get(namespace, name):
    rows = execute(
        "SELECT count, created_at, updated_at FROM counters WHERE namespace = %s AND name = %s",
        (namespace, name),
    )
    return rows[0] if rows else None


def add(namespace, name, delta):
    rows = execute(
        """
        INSERT INTO counters (namespace, name, count) VALUES (%s, %s, %s)
        ON CONFLICT (namespace, name)
        DO UPDATE SET count = counters.count + excluded.count, updated_at = CURRENT_TIMESTAMP
        RETURNING count
        """,
        (namespace, name, delta),
    )
    return rows[0][0]


def reset(namespace, name):
    execute(
        "UPDATE counters SET count = 0, updated_at = CURRENT_TIMESTAMP WHERE namespace = %s AND name = %s",
        (namespace, name),
    )


def list_namespace(namespace):
    return execute(
        "SELECT name, count, updated_at FROM counters WHERE namespace = %s ORDER BY name",
        (namespace,),
    )
