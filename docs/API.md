# API Reference

Base URL: `http://localhost:8001` · Interactive docs: `/docs` (Swagger) · `/redoc`

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Serves the frontend |
| GET | `/health` | Status, Ollama connectivity, model, KB size |
| POST | `/dt/start` | `{message}` → Intake → RAG shortlist → first yes/no question |
| POST | `/dt/answer` | `{session_id, symptom, answer}` → next question **or** final result |
| POST | `/triage` | `{symptoms}` → single-shot final result |
| POST | `/triage/stream` | Same, streamed as SSE, one event per agent |
| POST | `/chat/message` | `{session_id?, message}` → free-text conversational intake |
| POST | `/report/pdf` | `{pipeline, patient_name?}` → PDF |
| GET | `/history?limit=50` | Completed sessions (audit trail) |
| GET | `/history/{id}` | Full stored pipeline |
| GET | `/history/{id}/report.pdf` | PDF for a stored session |
| DELETE | `/history/{id}` | Delete a stored session |
| POST | `/feedback` | `{session_id, correct, corrected_condition?, corrected_acuity?, notes?}` — clinician review |
| GET | `/feedback/summary` | Agreement rate across clinician reviews |

## Result shape (`type: "result"`)

```json
{
  "type": "result",
  "session_id": "…",
  "pipeline": [
    {"stage": "intake",         "result": {"extracted_symptoms": [], "ruled_out_symptoms": [], "qa_log": []}},
    {"stage": "retrieval",      "result": {"matches": [], "top_match": {}}},
    {"stage": "triage",         "result": {"acuity_label": "URGENT", "confidence": 0.8, "reasoning": "…"}},
    {"stage": "recommendation", "result": {"final_recommendation": "…", "caution": "…"}},
    {"stage": "final",          "result": {"condition": "…", "acuity_label": "…", "reasoning_trace": []}}
  ]
}
```

## Configuration

See `.env.example`. Notable: `OLLAMA_URL`, `OLLAMA_MODEL`, `PORT` (default **8001**),
`DATABASE_URL` (PostgreSQL+pgvector), `EMBED_MODEL`, `RETRIEVER`, `AUTO_INGEST`, `EMERGENCY_CONTACTS`, `TRIAGE_DB_PATH`, `SESSION_TTL_SECONDS`.

Final results also carry `emergency_contacts`, `disclaimer` and, when the safety layer fires, `red_flags`, `urgent_banner`,
`safety_override`, `pipeline_acuity_label`. `/health` reports `retrieval` (e.g. `hybrid[... + pgvector (hashing-v1)]`) and `database`.


## Authentication (AUTH_MODE=open, the default)
Triage works with no login, for everyone. A free account only adds a **private history**: every saved result belongs to the user who ran it and nobody else can read it. There are no staff, admin or clinician roles. Callers log in once and send `Authorization: Bearer <token>`.

| Method | Path | Login | Purpose |
|---|---|---|---|
| POST | `/auth/login` | - | `{username, password}` -> `{token, role, expires_in}` (`role` is always `user`); locked for 15 min after 5 failures |
| POST | `/auth/register` | - | `{username, password}` -> free account + token (rate-limited; can be closed) |
| GET | `/auth/me` | yes | who am I |
| POST | `/auth/password` | yes | change your password |
| DELETE | `/auth/me` | yes | erase your account and all your results |
| GET | `/history`, `/history/{id}`, `/history/{id}/report.pdf` | yes | **your own** saved results only (someone else's id answers 404) |
| POST | `/feedback` | yes | mark one of your own results right or wrong (optional correction and notes) |
| DELETE | `/history/{id}` | yes | delete one of your own records |
| GET | `/ready`, `/health` | public | readiness / status |
| GET | `/metrics` | server itself only | operational counters |

Operator tasks (statistics, audit log, purge, backups, password resets) are command-line tools, not web endpoints: `python -m backend.maintenance ...`, `python -m backend.users ...`.

Results also carry `ai_mode` (`live_model` / `built_in_rules` / `mixed`) and `ai_note`.
Errors: 401 login required, 403 not allowed (e.g. registration closed), 413 too large, 422 invalid input, 429 rate limited.
