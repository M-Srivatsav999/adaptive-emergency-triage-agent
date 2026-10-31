#!/usr/bin/env bash
# One-command launcher (Linux/macOS). Serves API + frontend on http://localhost:8001/
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
echo "Tip: set DATABASE_URL in .env to use PostgreSQL+pgvector (see docker-compose.yml)."
echo "Open http://localhost:8001/  (Ctrl+C to stop)"
python -m backend.main
