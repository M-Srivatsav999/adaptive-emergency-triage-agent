"""
config.py — Central, environment-driven settings.

Every tunable lives here so Docker, Windows and Linux runs all behave the
same. Override any value with an environment variable or a `.env` file
(see `.env.example`).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Tiny .env loader (no extra dependency). Real env vars win."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# --- LLM (Ollama) ---------------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "45"))

# --- Server ---------------------------------------------------------------
PORT = int(os.getenv("PORT", "8001"))  # 8001: avoids clash with Auraxenith on 8000
HOST = os.getenv("HOST", "0.0.0.0")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# --- Triage ---------------------------------------------------------------
RAG_CANDIDATE_COUNT = int(os.getenv("RAG_CANDIDATE_COUNT", "6"))

# --- Persistence ----------------------------------------------------------
DB_PATH = Path(os.getenv("TRIAGE_DB_PATH", str(BASE_DIR / "data" / "triage.db")))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))

# --- PostgreSQL + pgvector (optional; everything degrades gracefully offline) --
# Example: postgresql://triage:triage@localhost:5432/triage
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AUTO_INGEST = os.getenv("AUTO_INGEST", "true").lower() in ("1", "true", "yes")
RETRIEVER = os.getenv("RETRIEVER", "auto").lower()      # auto | tfidf | pgvector
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 768  # nomic-embed-text native size; the offline hashing embedder matches it

# --- Locale -----------------------------------------------------------------
# Shown on every result and in the PDF. Override per country/region in .env.
EMERGENCY_CONTACTS = os.getenv(
    "EMERGENCY_CONTACTS",
    "Emergency: 112 (India) / ambulance 108 in many states; mental-health helpline Tele-MANAS 14416",
)

# --- Production hardening -------------------------------------------------------
ENV = os.getenv("ENV", "development").lower()            # development | production
AUTH_MODE = os.getenv("AUTH_MODE", "open").lower()       # off | open | strict
if AUTH_MODE == "clinic":                                 # old name from v6, same behaviour as "open"
    AUTH_MODE = "open"
#   off    : no login anywhere (single-user local demo only)
#   open   : EVERYONE can use triage/PDF with no account; a free account adds a private history (default)
#   strict : everything needs a login
SECRET_KEY = os.getenv("SECRET_KEY", "")                  # signs login tokens; REQUIRED in production
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "28800"))   # 8 hours
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "90"))  # stored sessions older than this are purged; 0 = keep forever
STORE_SESSIONS = os.getenv("STORE_SESSIONS", "true").lower() in ("1", "true", "yes")
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
LOGIN_RATE_LIMIT_PER_MINUTE = int(os.getenv("LOGIN_RATE_LIMIT_PER_MINUTE", "10"))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "2000"))
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))        # then the account is locked for a while
LOGIN_LOCK_SECONDS = int(os.getenv("LOGIN_LOCK_SECONDS", "900"))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(BASE_DIR / "backups")))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
REGISTRATION_OPEN = os.getenv("REGISTRATION_OPEN", "true").lower() in ("1", "true", "yes")   # anyone may create a free account
MIN_USER_PASSWORD_LEN = int(os.getenv("MIN_USER_PASSWORD_LEN", "8"))
REGISTER_LIMIT_PER_HOUR = int(os.getenv("REGISTER_LIMIT_PER_HOUR", "20"))   # per address, stops mass sign-ups
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() in ("1", "true", "yes")   # true only behind your own HTTPS proxy


def production_problems() -> list:
    """Unsafe settings that must not reach a production deployment."""
    problems = []
    if ENV != "production":
        return problems
    if len(SECRET_KEY) < 32:
        problems.append("SECRET_KEY must be set to a random string of at least 32 characters")
    if "*" in CORS_ORIGINS:
        problems.append("CORS_ORIGINS must not be '*' (list the exact origins, or leave unset for same-origin)")
    if AUTH_MODE == "off":
        problems.append("AUTH_MODE must not be 'off'")
    if DATABASE_URL and (":triage@" in DATABASE_URL):
        problems.append("the default database password 'triage' must be changed")
    return problems
