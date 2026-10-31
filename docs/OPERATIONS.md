# Operating the system

## First start
1. Copy `.env.example` to `.env`; set at least `SECRET_KEY` and `POSTGRES_PASSWORD`; set `ENV=production` once you move beyond a demo.
2. `docker compose up -d --build`. The app applies database migrations and seeds the knowledge base.
3. Open `http://<hub>:8001/` (or `https://<hub>/`). Everyone uses the same page; people create their own free accounts there if they want a private history. There is no staff login to set up.
4. Operator tools run from the server's command line: `python -m backend.maintenance stats|audit|backup|purge`, `python -m backend.users passwd NAME`.
Without Docker: `run.bat`/`run.sh`.

## Daily / weekly
| Task | How |
|---|---|
| Backup (daily) | `python -m backend.maintenance backup` (creates **and verifies** a backup in `backups/`). Docker: `docker compose exec backend python -m backend.maintenance backup` |
| Copy backups off the machine | Weekly, to a second device (USB drive stored securely - backups contain patient text) |
| Keep only recent backups | `python -m backend.maintenance prune --keep 14` |
| Check health | `/ready` (database reachable), `/health` (mode, model, auth, retention), `/metrics` (counters, from the server itself) |
| Accuracy data | Users mark their own results right or wrong; `python -m backend.maintenance stats` summarises agreement (no patient text) |
| Purge old data | Automatic every 6 hours (`RETENTION_DAYS`, default 90); manual: `python -m backend.maintenance purge` |

Schedule the backup with Windows Task Scheduler or cron. **Test a restore at least once** before relying on it.

## Restore
* SQLite: stop the app, copy the verified `.db` backup over `data/triage.db`, start the app.
* PostgreSQL: `docker compose exec -T db pg_restore -U triage -d triage --clean --if-exists < backups/triage-YYYYMMDD-HHMMSS.dump`
Always run `python -m backend.maintenance verify FILE` first.

## Upgrading
1. Back up. 2. Replace the project files (keep `.env`, `data/`, `backups/`). 3. `docker compose up -d --build`. Migrations run automatically, in order, once each (recorded in `schema_migrations`). 4. Check `/ready`, then run `python -m pytest -q` and `python -m eval.ci_gate` if you changed knowledge content.
Roll back by restoring the backup and the previous project files.

## When the AI model is slow or down
The system keeps working with built-in rules, and every result says so (`ai_mode`, shown on every result). On a CPU-only machine raise `OLLAMA_TIMEOUT` (e.g. 180) and warm the model once after boot.

## Monitoring (simple)
`/metrics` exposes counters: results by urgency, red-flag firings, "cannot assess" outcomes, AI mode, rate-limited requests, failed logins. Watch for: a spike of failed logins; many rate-limited requests; every result in `built_in_rules` mode when the model should be running; "cannot assess" rising (users describing things the knowledge base lacks - a signal of missing conditions).

## Account and incident basics
* Forgotten password (ordinary user): there is no email recovery. The operator can set a new one: `python -m backend.users passwd NAME` (after checking who is asking), or the person creates a new account.
* Too many spam accounts: set `REGISTRATION_OPEN=false` temporarily, or lower `REGISTER_LIMIT_PER_HOUR`.
* Leaver: `python -m backend.users disable NAME`; also change `SECRET_KEY` and restart to end their session immediately.
* Suspected misuse: `python -m backend.maintenance audit` shows who viewed or deleted what (record ids only).
* Suspected data exposure: take the hub off the network, preserve logs and backups, change all passwords and `SECRET_KEY`, and follow your institution's data-breach procedure (health data is regulated - involve your college).
* A wrong or dangerous answer: record it with the feedback form, tell the clinician reviewer, and consider disabling the affected knowledge entry (`review.py` workflow) until fixed.

## Release checklist (every change to knowledge or code)
`python -m pytest -q` -> `python -m eval.ci_gate` (must show **0 unsafe under-triage**) -> clinician sign-off for any changed advice -> backup -> deploy -> `/ready` and one test case of each urgency.
