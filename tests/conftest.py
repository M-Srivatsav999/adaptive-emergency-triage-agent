import os
import tempfile

# Isolate the DB before backend modules import config.
os.environ["TRIAGE_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
# Force deterministic fallback mode regardless of a local Ollama.
os.environ["OLLAMA_URL"] = "http://127.0.0.1:1"

# The suite fires hundreds of requests in seconds; the rate limiter has its own dedicated test.
os.environ["RATE_LIMIT_PER_MINUTE"] = "0"
os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "0"
os.environ["AUTH_MODE"] = "open"
