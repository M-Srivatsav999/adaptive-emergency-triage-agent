"""
maintenance.py - backups, verification, pruning and retention purge.

    python -m backend.maintenance backup            # SQLite file copy (online-safe) or PostgreSQL pg_dump
    python -m backend.maintenance verify FILE       # prove a backup is readable BEFORE you need it
    python -m backend.maintenance prune --keep 14   # keep only the newest N backups
    python -m backend.maintenance purge             # delete sessions older than RETENTION_DAYS now
    python -m backend.maintenance stats              # anonymous counts + clinician feedback summary (no patient text)
    python -m backend.maintenance audit --limit 100  # recent audit-log entries (no patient text)

Schedule `backup` daily (cron / Windows Task Scheduler) and copy the backup folder to a second device.
"""
import argparse
import datetime
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from backend import config, store


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _pg_args():
    u = urlparse(config.DATABASE_URL)
    env = dict(os.environ, PGPASSWORD=unquote(u.password or ""))   # keep the password out of the process list
    return ["-h", u.hostname or "localhost", "-p", str(u.port or 5432), "-U", unquote(u.username or ""), "-d", (u.path or "/").lstrip("/")], env


def backup(out_dir: Path = None) -> Path:
    out_dir = Path(out_dir or config.BACKUP_DIR); out_dir.mkdir(parents=True, exist_ok=True)
    store.init_db()
    if store.backend_name() == "postgres":
        if not shutil.which("pg_dump"):
            raise RuntimeError("pg_dump not found. In Docker run:  docker compose exec db pg_dump -U triage -Fc triage > backup.dump")
        target = out_dir / f"triage-{_stamp()}.dump"
        args, env = _pg_args()
        subprocess.run(["pg_dump", "--format=custom", "--file", str(target)] + args, check=True, env=env)
    else:
        target = out_dir / f"triage-{_stamp()}.db"
        src = sqlite3.connect(config.DB_PATH)
        try:
            dst = sqlite3.connect(target)
            with dst:
                src.backup(dst)          # consistent snapshot even while the app is running
            dst.close()
        finally:
            src.close()
    return target


def verify(path) -> dict:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("backup file missing or empty")
    if path.suffix == ".db":
        c = sqlite3.connect(path)
        try:
            ok = c.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            sessions = c.execute("SELECT count(*) FROM triage_sessions").fetchone()[0] if "triage_sessions" in tables else 0
        finally:
            c.close()
        if ok != "ok" or "triage_sessions" not in tables:
            raise RuntimeError(f"backup failed verification (integrity={ok}, tables={sorted(tables)})")
        return {"format": "sqlite", "sessions": sessions, "integrity": ok}
    if not shutil.which("pg_restore"):
        raise RuntimeError("pg_restore not found - cannot verify a PostgreSQL dump on this machine")
    toc = subprocess.run(["pg_restore", "--list", str(path)], capture_output=True, text=True, check=True).stdout
    if "triage_sessions" not in toc or "conditions" not in toc:
        raise RuntimeError("dump does not contain the expected tables")
    return {"format": "postgres", "tables_found": True}


def prune(keep: int, out_dir: Path = None) -> int:
    out_dir = Path(out_dir or config.BACKUP_DIR)
    files = sorted([f for f in out_dir.glob("triage-*") if f.suffix in (".db", ".dump")], key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[keep:]:
        f.unlink()
    return max(0, len(files) - keep)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup"); sub.add_parser("purge"); sub.add_parser("stats")
    au = sub.add_parser("audit"); au.add_argument("--limit", type=int, default=100)
    v = sub.add_parser("verify"); v.add_argument("file")
    p = sub.add_parser("prune"); p.add_argument("--keep", type=int, default=14)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "backup":
            t = backup(); print(f"Backup written: {t}"); print("Verified:", verify(t))
        elif a.cmd == "verify":
            print("OK:", verify(a.file))
        elif a.cmd == "prune":
            print(f"Removed {prune(a.keep)} old backup(s)")
        elif a.cmd == "stats":
            import json
            from backend.rag import review
            store.init_db()
            print(json.dumps({"sessions": store.session_stats(), "feedback": store.feedback_summary(),
                              "knowledge_review": review.status(), "retention_days": config.RETENTION_DAYS}, indent=2, default=str))
        elif a.cmd == "audit":
            import json
            store.init_db()
            for e in store.list_audit(min(max(a.limit, 1), 500)):
                print(json.dumps(e, default=str))
        else:
            store.init_db(); print(f"Purged {store.purge_older_than(config.RETENTION_DAYS)} session(s) older than {config.RETENTION_DAYS} days")
    except Exception as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
