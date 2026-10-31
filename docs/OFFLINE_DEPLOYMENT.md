# Offline / low-resource deployment

The system is designed so that **no patient data leaves the machine** and **no internet is needed after setup**.

## Capability tiers (it degrades gracefully, never refuses to start)

| Tier | Needs | What you get |
|---|---|---|
| 0 — Minimal | Python 3.11, ~300 MB RAM | Deterministic fallback agents, SQLite, symptom-overlap + TF-IDF retrieval, decision-tree questioning, PDF reports, red-flag safety layer. Runs on very old hardware. |
| 1 — + PostgreSQL/pgvector | Postgres 16 + `vector` ext. | Hybrid retrieval with offline hashing embeddings, JSONB audit trail, clinician feedback table |
| 2 — + Ollama | ~8 GB RAM (CPU ok) | LLM intake understanding, reasoning text, `nomic-embed-text` semantic search (switches on automatically after ingest) |

Ollama connectivity is re-checked on every request, so starting it later needs no restart.

## First-time setup with internet (one time)
```bash
docker compose up --build        # pulls images + llama3.2:3b + nomic-embed-text into Docker volumes
```
Afterwards: `docker compose up` works with the cable unplugged.

## Fully air-gapped install (no internet at the site)
On a machine **with** internet:
```bash
docker compose build
docker compose pull db ollama
docker compose up -d ollama && docker compose run --rm ollama-pull       # fills the ollama volume
docker save -o triage-images.tar pgvector/pgvector:pg16 ollama/ollama:latest triage_system-backend
# export the model volume
docker run --rm -v triage_system_ollama_data:/m -v "$PWD":/o alpine tar czf /o/ollama-models.tgz -C /m .
```
Copy `triage-images.tar`, `ollama-models.tgz` and the project folder (USB drive) to the clinic machine:
```bash
docker load -i triage-images.tar
docker volume create triage_system_ollama_data
docker run --rm -v triage_system_ollama_data:/m -v "$PWD":/o alpine tar xzf /o/ollama-models.tgz -C /m
docker compose up -d
```
(Volume/image names depend on your project folder name; check with `docker volume ls` / `docker images`.)

## Sizing guidance (indicative — measure on your hardware)
* Tier 0–1: any modern PC or low-end laptop.
* Tier 2: `llama3.2:3b` is intended for CPU-only machines with ~8 GB RAM; responses take seconds, not milliseconds.
  A GPU is optional (see the commented block in `docker-compose.yml`).

## Data protection
* Postgres is **not** published to the host by default. Change `POSTGRES_PASSWORD`.
* Sessions contain symptoms. Use `DELETE /history/{id}` to erase a record; consider disk encryption on shared machines.
* Restrict `CORS_ORIGINS` if the API is reachable on a network.
* Set `EMERGENCY_CONTACTS` to the correct local numbers (default is India: 112 / 108 / Tele-MANAS 14416 — **verify**).

## Backup
```bash
docker compose exec db pg_dump -U triage triage > triage-backup.sql
```
