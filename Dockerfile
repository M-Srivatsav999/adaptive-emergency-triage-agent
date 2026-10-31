FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# pg_dump / pg_restore so `python -m backend.maintenance backup` works against the PostgreSQL container
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY eval/ ./eval/
COPY tests/ ./tests/
COPY docs/ ./docs/

# Run as an unprivileged user, never root
RUN useradd --system --create-home --uid 10001 app \
    && mkdir -p /app/data /app/backups \
    && chown -R app:app /app/data /app/backups /app/backend/rag
USER app

ENV PORT=8001 HOST=0.0.0.0 TRIAGE_DB_PATH=/app/data/triage.db BACKUP_DIR=/app/backups
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/ready', timeout=4)" || exit 1

# The app migrates and seeds PostgreSQL/pgvector itself on startup (idempotent) when DATABASE_URL is set.
CMD ["python", "-m", "backend.main"]
