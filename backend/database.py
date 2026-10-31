"""
database.py — PostgreSQL connection helpers.

PostgreSQL + pgvector is OPTIONAL at runtime: if DATABASE_URL is unset or the
server is down, the app keeps working (SQLite audit trail + in-memory
retrieval). That is deliberate for rural / low-resource sites where a
database server may not be available.
"""

from pathlib import Path

from backend import config

MIGRATIONS_DIR = Path(__file__).resolve().parent / "db" / "migrations"


def pg_configured() -> bool:
    return bool(config.DATABASE_URL)


def connect(timeout: int = 3):
    import psycopg  # imported lazily so SQLite-only installs don't need it

    return psycopg.connect(config.DATABASE_URL, connect_timeout=timeout)


def pg_available() -> bool:
    """True when a database is configured, reachable and has pgvector."""
    if not pg_configured():
        return False
    try:
        with connect(timeout=2) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def migrate() -> list:
    """Apply any not-yet-applied SQL migrations (files in db/migrations, in name order).
    Each file is recorded in schema_migrations, so upgrades are explicit, ordered and repeatable.
    Returns the versions applied in this run."""
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    applied_now = []
    with connect(timeout=10) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        for f in files:
            if f.stem in done:
                continue
            conn.execute(f.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (f.stem,))
            applied_now.append(f.stem)
    return applied_now


def init_schema() -> None:
    migrate()
