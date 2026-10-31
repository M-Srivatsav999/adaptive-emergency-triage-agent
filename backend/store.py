"""
store.py — Persistence for completed triage sessions (audit trail) and
clinician feedback.

Backend is chosen at startup:
  * PostgreSQL (JSONB)  when DATABASE_URL is set and reachable
  * SQLite file         otherwise (zero-setup, ideal for a single offline PC)

Active yes/no sessions hold live scikit-learn trees, so they stay in memory
(with a TTL sweep in main.py). Once a session finishes, the full explainable
pipeline is written here so it can be reviewed and its PDF regenerated later.
"""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from backend import config, database

_backend = "sqlite"


def backend_name() -> str:
    return _backend


# ----------------------------------------------------------------- SQLite ---
@contextmanager
def _sqlite():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _sqlite_init() -> None:
    with _sqlite() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS triage_sessions (
                   id TEXT PRIMARY KEY, created_at REAL NOT NULL, mode TEXT NOT NULL,
                   condition TEXT, acuity TEXT, confidence REAL, pipeline_json TEXT NOT NULL)"""
        )
        c.execute("UPDATE users SET role='user' WHERE role!='user'") if c.execute("SELECT name FROM sqlite_master WHERE name='users'").fetchone() else None
        if "owner" not in {r[1] for r in c.execute("PRAGMA table_info(triage_sessions)")}:
            c.execute("ALTER TABLE triage_sessions ADD COLUMN owner TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS triage_sessions_owner_idx ON triage_sessions (owner, created_at)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                   username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, role TEXT NOT NULL,
                   disabled INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS audit_log (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, actor TEXT,
                   action TEXT NOT NULL, target TEXT, detail TEXT)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS clinician_feedback (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                   correct INTEGER NOT NULL, corrected_condition TEXT, corrected_acuity TEXT,
                   notes TEXT, created_at REAL NOT NULL)"""
        )


# --------------------------------------------------------------- public API --
def init_db() -> None:
    global _backend
    if database.pg_available():
        try:
            database.init_schema()
            _backend = "postgres"
            return
        except Exception as e:
            print(f"[store] PostgreSQL init failed ({e}); falling back to SQLite.")
    _backend = "sqlite"
    _sqlite_init()


def _final_of(pipeline: list) -> dict:
    return next((s["result"] for s in pipeline if s.get("stage") == "final"), {}) or {}


def save_session(session_id: str, mode: str, pipeline: list, owner: str = None) -> None:
    if not config.STORE_SESSIONS:   # privacy option: keep nothing
        return
    session_id = session_id or str(uuid.uuid4())
    final = _final_of(pipeline)
    cond, acu, conf = final.get("condition"), final.get("acuity_label"), final.get("confidence")
    if _backend == "postgres":
        from psycopg.types.json import Jsonb

        with database.connect() as conn:
            conn.execute(
                """INSERT INTO triage_sessions (id, mode, condition, acuity, confidence, pipeline, owner)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET mode=EXCLUDED.mode, condition=EXCLUDED.condition,
                       acuity=EXCLUDED.acuity, confidence=EXCLUDED.confidence, pipeline=EXCLUDED.pipeline,
                       owner=EXCLUDED.owner""",
                (session_id, mode, cond, acu, conf, Jsonb(pipeline), owner),
            )
    else:
        with _sqlite() as c:
            c.execute(
                "INSERT OR REPLACE INTO triage_sessions (id, created_at, mode, condition, acuity, confidence, pipeline_json, owner) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (session_id, time.time(), mode, cond, acu, conf, json.dumps(pipeline), owner),
            )


def list_sessions(limit: int = 50, owner: str = None, only_owner: bool = False) -> list:
    """Sessions, or - with only_owner=True - just the ones owned by `owner`."""
    if _backend == "postgres":
        where, args = ("WHERE owner = %s ", (owner,)) if only_owner else ("", ())
        with database.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, EXTRACT(EPOCH FROM created_at), mode, condition, acuity, confidence, owner "
                "FROM triage_sessions " + where + "ORDER BY created_at DESC LIMIT %s", args + (limit,))
            return [dict(id=r[0], created_at=float(r[1]), mode=r[2], condition=r[3],
                         acuity=r[4], confidence=r[5], owner=r[6]) for r in cur.fetchall()]
    where, args = ("WHERE owner = ? ", (owner,)) if only_owner else ("", ())
    with _sqlite() as c:
        rows = c.execute(
            "SELECT id, created_at, mode, condition, acuity, confidence, owner "
            "FROM triage_sessions " + where + "ORDER BY created_at DESC LIMIT ?", args + (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str):
    if _backend == "postgres":
        with database.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, EXTRACT(EPOCH FROM created_at), mode, condition, acuity, confidence, pipeline, owner "
                "FROM triage_sessions WHERE id=%s", (session_id,))
            r = cur.fetchone()
        if not r:
            return None
        return dict(id=r[0], created_at=float(r[1]), mode=r[2], condition=r[3], acuity=r[4],
                    confidence=r[5], pipeline=r[6], owner=r[7])
    with _sqlite() as c:
        row = c.execute("SELECT * FROM triage_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["pipeline"] = json.loads(d.pop("pipeline_json"))
    return d


def delete_user(username: str) -> int:
    """Erase an account and everything it owns (right to erasure). Returns how many sessions were deleted."""
    if _backend == "postgres":
        with database.connect() as conn:
            conn.execute("DELETE FROM clinician_feedback WHERE session_id IN (SELECT id FROM triage_sessions WHERE owner=%s)", (username,))
            n = conn.execute("DELETE FROM triage_sessions WHERE owner=%s", (username,)).rowcount
            conn.execute("DELETE FROM users WHERE username=%s", (username,))
            return n
    with _sqlite() as c:
        c.execute("DELETE FROM clinician_feedback WHERE session_id IN (SELECT id FROM triage_sessions WHERE owner=?)", (username,))
        n = c.execute("DELETE FROM triage_sessions WHERE owner=?", (username,)).rowcount
        c.execute("DELETE FROM users WHERE username=?", (username,))
    return n


def delete_session(session_id: str) -> bool:
    if _backend == "postgres":
        with database.connect() as conn:
            cur = conn.execute("DELETE FROM triage_sessions WHERE id=%s", (session_id,))
            conn.execute("DELETE FROM clinician_feedback WHERE session_id=%s", (session_id,))
            return cur.rowcount > 0
    with _sqlite() as c:
        cur = c.execute("DELETE FROM triage_sessions WHERE id = ?", (session_id,))
        c.execute("DELETE FROM clinician_feedback WHERE session_id = ?", (session_id,))
    return cur.rowcount > 0


def add_feedback(session_id: str, correct: bool, corrected_condition=None,
                 corrected_acuity=None, notes=None) -> None:
    if _backend == "postgres":
        with database.connect() as conn:
            conn.execute(
                "INSERT INTO clinician_feedback (session_id, correct, corrected_condition, corrected_acuity, notes) "
                "VALUES (%s,%s,%s,%s,%s)", (session_id, correct, corrected_condition, corrected_acuity, notes))
        return
    with _sqlite() as c:
        c.execute(
            "INSERT INTO clinician_feedback (session_id, correct, corrected_condition, corrected_acuity, notes, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, 1 if correct else 0, corrected_condition, corrected_acuity, notes, time.time()))


def feedback_summary() -> dict:
    """Aggregate clinician agreement - the real-world accuracy signal."""
    if _backend == "postgres":
        with database.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*), count(*) FILTER (WHERE correct) FROM clinician_feedback")
            total, ok = cur.fetchone()
    else:
        with _sqlite() as c:
            r = c.execute("SELECT count(*), coalesce(sum(correct),0) FROM clinician_feedback").fetchone()
            total, ok = r[0], r[1]
    return {"reviews": total, "agreed": ok, "agreement_rate": round(ok / total, 3) if total else None}


# ----------------------------------------------------------------- accounts --
def count_users() -> int:
    if _backend == "postgres":
        with database.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM users"); return cur.fetchone()[0]
    with _sqlite() as c:
        return c.execute("SELECT count(*) FROM users").fetchone()[0]


def create_user(username: str, password_hash: str, role: str) -> None:
    if _backend == "postgres":
        with database.connect() as conn:
            conn.execute("INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s)", (username, password_hash, role))
        return
    with _sqlite() as c:
        c.execute("INSERT INTO users (username, password_hash, role, disabled, created_at) VALUES (?,?,?,0,?)",
                  (username, password_hash, role, time.time()))


def get_user(username: str):
    if _backend == "postgres":
        with database.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT username, password_hash, role, disabled FROM users WHERE username=%s", (username,))
            r = cur.fetchone()
        return dict(username=r[0], password_hash=r[1], role=r[2], disabled=bool(r[3])) if r else None
    with _sqlite() as c:
        r = c.execute("SELECT username, password_hash, role, disabled FROM users WHERE username=?", (username,)).fetchone()
    return dict(username=r[0], password_hash=r[1], role=r[2], disabled=bool(r[3])) if r else None


def list_users() -> list:
    if _backend == "postgres":
        with database.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT username, role, disabled FROM users ORDER BY username")
            return [dict(username=r[0], role=r[1], disabled=bool(r[2])) for r in cur.fetchall()]
    with _sqlite() as c:
        return [dict(username=r[0], role=r[1], disabled=bool(r[2])) for r in c.execute("SELECT username, role, disabled FROM users ORDER BY username")]


def set_user_password(username: str, password_hash: str) -> bool:
    if _backend == "postgres":
        with database.connect() as conn:
            return conn.execute("UPDATE users SET password_hash=%s WHERE username=%s", (password_hash, username)).rowcount > 0
    with _sqlite() as c:
        return c.execute("UPDATE users SET password_hash=? WHERE username=?", (password_hash, username)).rowcount > 0


def set_user_disabled(username: str, disabled: bool) -> bool:
    if _backend == "postgres":
        with database.connect() as conn:
            return conn.execute("UPDATE users SET disabled=%s WHERE username=%s", (disabled, username)).rowcount > 0
    with _sqlite() as c:
        return c.execute("UPDATE users SET disabled=? WHERE username=?", (1 if disabled else 0, username)).rowcount > 0


# ----------------------------------------------------------------- audit log --
def audit(actor: str, action: str, target: str = None, detail: str = None) -> None:
    """Record WHO did WHAT to WHICH record. Never put patient text in `detail`."""
    try:
        if _backend == "postgres":
            with database.connect() as conn:
                conn.execute("INSERT INTO audit_log (actor, action, target, detail) VALUES (%s,%s,%s,%s)", (actor, action, target, detail))
        else:
            with _sqlite() as c:
                c.execute("INSERT INTO audit_log (at, actor, action, target, detail) VALUES (?,?,?,?,?)", (time.time(), actor, action, target, detail))
    except Exception as e:   # auditing must never take the service down
        print(f"[audit] could not write audit entry: {type(e).__name__}")


def list_audit(limit: int = 100) -> list:
    if _backend == "postgres":
        with database.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT EXTRACT(EPOCH FROM at), actor, action, target, detail FROM audit_log ORDER BY at DESC, id DESC LIMIT %s", (limit,))
            return [dict(at=float(r[0]), actor=r[1], action=r[2], target=r[3], detail=r[4]) for r in cur.fetchall()]
    with _sqlite() as c:
        rows = c.execute("SELECT at, actor, action, target, detail FROM audit_log ORDER BY at DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(at=r[0], actor=r[1], action=r[2], target=r[3], detail=r[4]) for r in rows]


# ------------------------------------------------------------------ retention --
def purge_older_than(days: int) -> int:
    """Delete stored sessions (and their feedback) older than `days`. 0 = keep forever."""
    if days <= 0:
        return 0
    if _backend == "postgres":
        with database.connect() as conn:
            conn.execute("DELETE FROM clinician_feedback WHERE session_id IN "
                         "(SELECT id FROM triage_sessions WHERE created_at < now() - make_interval(days => %s))", (days,))
            return conn.execute("DELETE FROM triage_sessions WHERE created_at < now() - make_interval(days => %s)", (days,)).rowcount
    cutoff = time.time() - days * 86400
    with _sqlite() as c:
        c.execute("DELETE FROM clinician_feedback WHERE session_id IN (SELECT id FROM triage_sessions WHERE created_at < ?)", (cutoff,))
        return c.execute("DELETE FROM triage_sessions WHERE created_at < ?", (cutoff,)).rowcount


def session_stats() -> dict:
    """Counts only - no patient text."""
    if _backend == "postgres":
        with database.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT acuity, count(*) FROM triage_sessions GROUP BY acuity")
            by = {r[0] or "unknown": r[1] for r in cur.fetchall()}
    else:
        with _sqlite() as c:
            by = {(r[0] or "unknown"): r[1] for r in c.execute("SELECT acuity, count(*) FROM triage_sessions GROUP BY acuity")}
    return {"total": sum(by.values()), "by_acuity": by}
