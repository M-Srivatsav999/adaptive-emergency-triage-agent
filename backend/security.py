"""
security.py - authentication, authorisation, rate limiting and HTTP hardening.

Design for an OFFLINE, open-access deployment (no external identity provider):
  * Everyone is an ordinary user. Accounts live in the local database (PBKDF2-SHA256 hashes, per-user salt).
  * Login returns a short-lived HMAC-signed token (no extra dependencies, no cloud).
  * Anyone can use triage and download their PDF without an account. An account only adds a PRIVATE
    history: every stored result belongs to one user and nobody else can read it.   AUTH_MODE=open (default)
  * AUTH_MODE=off disables login entirely - for a single-user local demo ONLY.
There are no staff, admin or clinician roles in the web application (operator tasks are command-line tools).
"""
import base64
import collections
import hashlib
import hmac
import json
import secrets
import threading
import time

from fastapi import Depends, HTTPException, Request

from backend import config

ROLES = {"user": 0}
PBKDF2_ITERATIONS = 200_000
_DEV_SECRET = secrets.token_hex(32)   # per-process fallback for development; production requires SECRET_KEY


# ---------------------------------------------------------------- passwords --
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(PBKDF2_ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt_b64, hash_b64 = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


def password_problem(password: str, min_len: int = 10):
    """None if acceptable, else a message. Length matters more than complexity rules."""
    if len(password) < min_len:
        return f"password must be at least {min_len} characters"
    if password.lower() in {"password123", "1234567890", "qwertyuiop", "triage12345"}:
        return "password is too common"
    return None


# ------------------------------------------------------------------- tokens --
def _key() -> bytes:
    return (config.SECRET_KEY or _DEV_SECRET).encode("utf-8")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(username: str, role: str, ttl: int = None) -> str:
    payload = {"u": username, "r": role, "exp": int(time.time()) + (ttl or config.TOKEN_TTL_SECONDS)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str):
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        payload = json.loads(_unb64(body))
        if payload["exp"] < time.time() or payload["r"] not in ROLES:
            return None
        return {"username": payload["u"], "role": payload["r"]}
    except Exception:
        return None


def _bearer(request: Request):
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def current_user(request: Request):
    tok = _bearer(request)
    return verify_token(tok) if tok else None


def optional_user(request: Request):
    """The logged-in user if a valid token was sent, else None (nobody needs an account to use the tool)."""
    return current_user(request)


def require(min_role: str):
    """FastAPI dependency: require a logged-in user (no-op when AUTH_MODE=off)."""
    need = ROLES[min_role]

    def dep(request: Request):
        if config.AUTH_MODE == "off":
            return {"username": "local", "role": "user"}
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Login required", headers={"WWW-Authenticate": "Bearer"})
        if ROLES[user["role"]] < need:
            raise HTTPException(status_code=403, detail="Your role does not allow this action")
        return user

    return Depends(dep)


# ------------------------------------------------------------ login lockout --
_lock = threading.Lock()
_failures = {}   # username -> (count, locked_until)


def login_locked(username: str) -> bool:
    with _lock:
        c = _failures.get(username)
        return bool(c and c[1] > time.time())


def record_login_failure(username: str) -> None:
    with _lock:
        count, _ = _failures.get(username, (0, 0))
        count += 1
        locked = time.time() + config.LOGIN_LOCK_SECONDS if count >= config.LOGIN_MAX_FAILURES else 0
        _failures[username] = (0 if locked else count, locked)


def record_login_success(username: str) -> None:
    with _lock:
        _failures.pop(username, None)


def clear_lockouts() -> None:   # used by tests
    with _lock:
        _failures.clear()


# -------------------------------------------------------------- rate limits --
class RateLimiter:
    """Sliding-window limiter keyed by client address (in memory; fine for a single clinic hub)."""

    def __init__(self):
        self._hits = collections.defaultdict(collections.deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        if limit <= 0:
            return True
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
PATIENT_PATH_PREFIXES = ("/triage", "/dt/", "/chat/", "/report/")


def client_key(request: Request) -> str:
    """Who is calling? Behind our own reverse proxy (TRUST_PROXY=true) use the forwarded address,
    otherwise the proxy would make every user look like one client and share one rate limit."""
    if config.TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if fwd:
            return fwd
    return request.client.host if request.client else "unknown"


# ------------------------------------------------------------ HTTP hardening --
def security_headers(request: Request) -> dict:
    h = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cache-Control": "no-store" if request.url.path.startswith(("/history", "/auth", "/feedback")) else "no-cache",
    }
    if config.ENV == "production":
        h["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return h
