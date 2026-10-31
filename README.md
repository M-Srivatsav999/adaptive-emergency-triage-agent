# AI-Driven Clinical Triage System

**A Local-First, Explainable Multi-Agent LLM Framework for Clinical Triage and Prescription Recommendation**

Free, offline decision support for clinics, health workers and families without reliable internet. Four cooperating agents
(Intake → Retrieval/RAG → Triage → Recommendation) classify urgency (**EMERGENCY / URGENT / ROUTINE**), give safety-oriented
first-aid and referral guidance, and show a complete reasoning trace. It runs on one ordinary computer and sends nothing anywhere.

> ⚠️ **Decision-support research prototype - not a medical device, and not a substitute for a doctor.**
> The medical knowledge base is a **draft**: no entry is marked clinician-approved until a named clinician reviews it
> (see *Clinician review* below). Use it supervised, and never delay emergency care because of it.

## What is in the box
| | |
|---|---|
| **Knowledge base** | **159 conditions** (51 emergency, 56 urgent, 52 routine) with symptoms, guidance, cautions, escalation warning signs and self-care. Covers common rural priorities - snakebite, pesticide and kerosene poisoning, malaria, dengue, scrub typhus, typhoid, TB, kala-azar, leprosy, rabies signs, dehydration, child pneumonia/croup/whooping cough, newborn danger signs, pregnancy and childbirth emergencies, **allergies** (food, drug, severe skin reaction, stings, contact dermatitis, eczema, angioedema), stroke, sepsis, burns, injuries, eye/ear/dental, mental health and more |
| **Symptom lexicon** | 394 symptoms, 324 hand-written questions, ~2,500 everyday phrasings ("loose motions", "giddiness", "sugar patient") |
| **Retrieval (RAG)** | Hybrid: symptom-overlap + TF-IDF + **pgvector** semantic search (Ollama `nomic-embed-text`, or an offline embedder), rank-fused |
| **Triage** | Decision tree + calibrated Bayesian posterior, information-gain questioning, confidence stop, **worst-case-aware urgency** |
| **"I can't assess this"** | Weak evidence is never forced into a diagnosis: the tool says so, advises seeing a health worker (never ROUTINE) and lists general danger signs |
| **Safety layer** | Deterministic emergency **red-flag override** (24 rule groups, 158+ phrases: snake bite, unconscious, seizure, bleeding, self-harm, poison, drowning, carbon monoxide, labour/fetal-movement, rabies signs…) |
| **Clinician review workflow** | Spreadsheet export/import so a clinician's approval is recorded per entry with name and date, audited, and shown to users |
| **Persistence** | PostgreSQL (JSONB audit trail, clinician feedback) or SQLite |
| **Explainability** | Reasoning trace, live elimination probabilities, downloadable formal PDF report |
| **Deployment** | Docker Compose (db + ollama + backend), Windows/Linux one-click scripts, air-gapped guide |
| **Sources and citations** | 9 high-risk entries are **source-checked** against WHO / CDC / NHS-type guidance with citations shown on results (this is *not* clinical review - see `docs/SOURCES.md`) |
| **Local languages (partial)** | Everyday phrasings plus common Hindi and Telugu symptom and emergency words, in Roman and native script (needs native-speaker review; interface still English) |
| **Open to everyone** | No account needed to use the tool. Anyone can also create a **free account** on the page to keep a **private history** of their own results (view, download the PDF to show a clinician, delete), change their password, or erase their account and all their data. Nobody else can see an ordinary user's history |
| **Security and privacy** | Open access for everyone (no staff tier), private per-user history, password hashing, login lockout, rate limiting, security headers, input limits, audit log (no patient text), automatic data retention and a "save nothing" switch, one-time consent notice, production mode that **refuses unsafe settings** - see `docs/SECURITY.md`, `docs/PRIVACY.md` |
| **Operations** | Versioned database migrations, verified backups (SQLite and PostgreSQL), health/readiness/metrics endpoints, release gate for CI (`eval/ci_gate.py`), non-root container, optional HTTPS profile - see `docs/OPERATIONS.md` |
| **Operator tools** (command line, not a web page) | `python -m backend.maintenance stats` / `audit` / `backup` / `purge`, and `python -m backend.users` for password resets. There are no staff or admin logins in the web app: everyone is an ordinary user |
| **Installable app** | Works as an installable offline web app on phones and tablets (service worker caches only the page shell, never patient data) |
| **Honest AI reporting** | Every result says whether the AI model or the built-in rules wrote the wording; probabilities are never shown as 0% or 100% |
| **Tests** | 162 automated tests (151 offline + 11 real-PostgreSQL) plus evaluation, ablation, red-flag and release-gate harnesses |

## Quick start
| Platform | Command | Then open |
|---|---|---|
| **Docker (full stack)** | `docker compose up --build` | http://localhost:8001/ |
| Windows (no Docker) | double-click `run.bat` | http://localhost:8001/ |
| Linux / macOS | `./run.sh` | http://localhost:8001/ |

**No account is needed to use the tool, and there are no staff or admin logins.** Everyone is the same kind of user. Anyone can create a free account in the page (top bar) to keep a private history that only they can see. Password resets for a user: `python -m backend.users passwd NAME` (Docker: `docker compose exec backend python -m backend.users passwd NAME`).

Port **8001** (not 8000). Docker needs internet **once** to pull images and models, then runs offline. Without Docker, PostgreSQL
or Ollama it still works in a clearly-labelled fallback mode. For live-model timeouts on slow machines set `OLLAMA_TIMEOUT=180` in `.env`.

## Clinician review (how his help becomes part of the app)
```bash
python -m backend.rag.review export                 # writes review_sheet.csv, emergencies first
python -m backend.rag.review import review_sheet.csv # records APPROVED / CHANGES_REQUESTED + name + date
python -m backend.rag.review status                  # how many entries are reviewed
```
Give the clinician `docs/CLINICIAN_REVIEW_GUIDE.md` and `review_sheet.csv`. After import, each result shows
"Reviewed and approved by Dr. … on …" for approved entries and "Draft - not yet reviewed" for the rest. Import never edits the
medical text; requested changes are made by a developer and the entry returns to draft. **Currently all 159 entries are DRAFT.**

## Free for everyone
MIT licence for the code, CC BY 4.0 for the knowledge content, no adverts, no analytics, no running costs. See `LICENSE`,
`NOTICE.md` (third-party licences, including Meta's Llama licence terms) and `docs/FREE_AND_OPEN.md`.

## How it works
```
patient text → Intake → Retrieval (hybrid RAG shortlist of 6) → Triage → Recommendation → result + PDF
                             └── retrieval ranking becomes the prior for Triage's Bayesian posterior
Safety: red-flag phrases in the patient's own words force EMERGENCY; weak evidence becomes "cannot assess", never ROUTINE.
```
Diagrams: `docs/ARCHITECTURE.md` · API: `docs/API.md` (+ Swagger at `/docs`) · offline setup: `docs/OFFLINE_DEPLOYMENT.md`.

## Evaluation (offline fallback mode, no LLM) - read the caveats
```bash
python -m eval.evaluate_full               # development, original 81 conditions
python -m eval.evaluate_full --new         # development, the 78 later-added conditions
python -m eval.evaluate_full --holdout     # holdout (original conditions)
python -m eval.evaluate_full --holdout2    # holdout (new conditions, written after the vocabulary was frozen, run once)
python -m eval.evaluate && python -m eval.evaluate_redflags && python -m eval.ablation
```
All numbers below are for the **159-condition** knowledge base.

| Set | Cases | In shortlist | Final condition | Urgency correct | **Under-triage (unsafe)** | Over-triage (cautious) |
|---|---|---|---|---|---|---|
| Development - original conditions | 81 | 100% | 100% | 93.8% | **0** | 5 |
| Development - new conditions | 78 | 100% | 100% | 93.6% | **0** | 5 |
| **Holdout - original conditions** | 40 | 97.5% | 95.0% | 87.5% | **0** | 5 |
| **Holdout - new conditions** | 41 | 100% | 97.6% | 87.8% | **0** | 5 |

Legacy 15-case set: 15/15 condition, 12/15 urgency (3 deliberate over-triages). "Cannot assess" outcomes on all of the above: 0 (it does not over-trigger).
The holdout rows are the honest ones; the development rows were used to tune the vocabulary. Growing the knowledge base from 81 to 159
slightly lowered holdout accuracy (100% → 95%, mostly look-alike pairs such as chickenpox/shingles and fracture/dislocation) - this
is the expected cost of a bigger catalogue, and errors remained on the cautious side.

**These are NOT clinical-accuracy figures.** The cases and the knowledge base were written by the same team, the simulated patient is
cooperative and reports ~75% of true symptoms, and no real patient data were used. Real validation needs clinicians and real cases - the
`/feedback` endpoint exists to collect exactly that. Details: `docs/EVALUATION.md`.

## Tests
```bash
pip install -r requirements-dev.txt
python -m pytest -q                       # 151 tests (SQLite / offline)
TEST_DATABASE_URL=postgresql://triage:triage@localhost:5432/triage_test python -m pytest -q   # +11 real PostgreSQL tests (migrations, backups, pgvector)
```

## Project layout
```
backend/   main.py orchestrator.py llm_client.py config.py store.py database.py safety.py confidence.py report.py
           agents/ (intake, retrieval, triage, recommendation)
           rag/    knowledge_base.json (159)  symptom_lexicon.json  retriever.py  decision_tree.py
                   embeddings.py  ingest.py  review.py (clinician review workflow)
           db/     migrations/ (001_baseline, 002_users_audit, 003_user_history, 004_open_access)
           security.py metrics.py users.py maintenance.py (accounts, backups, retention)
frontend/  index.html  manifest.webmanifest  sw.js  icons
eval/      evaluate*.py  ablation.py  ci_gate.py  cases*.json  redflag_cases.json
tests/     162 tests     docs/  ARCHITECTURE API OFFLINE_DEPLOYMENT EVALUATION KNOWLEDGE_BASE SOURCES CLINICIAN_REVIEW_GUIDE FREE_AND_OPEN SECURITY OPERATIONS PRIVACY PRODUCTION_READINESS
LICENSE  NOTICE.md  review_sheet.csv  docker-compose.yml  Dockerfile  run.bat  run.sh  .env.example
```

## Team ownership
Backend/agents/config/persistence/safety - M. Srivatsav · RAG, knowledge base, decision tree - K. Venkata Sai Shreyas ·
Frontend and explainability UI - P. Sai Shourya · Evaluation, documentation, tests, PDF reports - G. Sai.

## Honest limitations
**Status: ready for a supervised pilot at one clinic - NOT for unsupervised or public use.** See `docs/PRODUCTION_READINESS.md`.
1. **The knowledge base is draft and not clinician-validated** - the biggest gap. Informal approval of the approach is not a review of each entry; use the review workflow. Only 9 entries are source-checked.
2. **Our evaluations are synthetic and author-written** (offline, no live AI model): they show consistency, not real-world accuracy. Real validation needs clinicians and real cases (users can mark their own saved result right or wrong with the feedback form; `python -m backend.maintenance stats` summarises it).
3. **No password recovery by email** (there is no email or phone on file by design): a forgotten password means a new account, or the operator resets it (`python -m backend.users passwd NAME`). Free open registration can be abused, so it is rate-limited and can be closed (`REGISTRATION_OPEN=false`).
4. **Not independently security-tested.** No penetration test or load test. The Docker build, HTTPS profile and CI workflow were written but not run by us. Tokens cannot be revoked before they expire; no two-factor login. See `docs/SECURITY.md`.
5. 159 conditions are **not "all diseases"**: anything outside them should produce the honest "cannot assess" outcome. Rare diseases and multiple simultaneous illnesses are handled poorly.
6. English interface only (Hindi/Telugu symptom words are recognised but unreviewed; questions and results are English). Triage is advisory.
7. Whether health-advice software needs regulatory clearance where you deploy it is for your college and a regulatory adviser to confirm.
