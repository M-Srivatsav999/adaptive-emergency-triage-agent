"""
main.py — Owner: Srivatsav (Backend & Agent Orchestration)

FastAPI application exposing the triage pipeline over HTTP.

  POST /triage          — single-shot, runs the full pipeline, returns the final result
  POST /triage/stream    — same, but streams each agent's result via SSE
  POST /chat/message     — free-text conversational intake (LLM asks follow-ups)
  POST /dt/start         — yes/no intake: Intake extracts initial symptoms,
                            RAG (Retrieval Agent) retrieves a candidate
                            shortlist of plausible conditions, then Triage
                            begins asking yes/no questions scoped to ONLY
                            that shortlist
  POST /dt/answer        — submits an answer, continues Triage's narrowing
                            within the RAG shortlist, returns the next
                            question or the final result once resolved

Pipeline flow (matches the intended design):
  Intake (extract symptoms)
    -> Retrieval/RAG (shortlist plausible candidate conditions)
      -> Triage (asks targeted yes/no questions to disambiguate WITHIN
                 that shortlist, then classifies urgency)
        -> Recommendation (uses the full path — including which
                            candidates were considered and ruled out — to
                            produce guidance and relevant cautions)

Run locally:
  python -m backend.main        (serves API + frontend on http://localhost:8001)
"""

import asyncio
import os
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend import config, metrics, security, store
from backend.orchestrator import finalize, attach_knowledge_status
from backend import safety
from backend import confidence

from backend.orchestrator import run_pipeline, run_pipeline_sync, run_from_intake
from backend.agents import intake_agent, retrieval_agent, triage_agent, recommendation_agent
from backend.rag.decision_tree import DecisionTreeTriage, extract_known_symptoms
from backend.llm_client import is_ollama_live

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO), format="%(message)s")
log = logging.getLogger("triage")
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


async def _retention_loop() -> None:
    """Purge stored sessions older than RETENTION_DAYS (data minimisation), every six hours."""
    while True:
        try:
            n = await asyncio.get_running_loop().run_in_executor(None, store.purge_older_than, config.RETENTION_DAYS)
            if n:
                store.audit("system", "retention_purge", None, f"{n} sessions older than {config.RETENTION_DAYS} days")
        except Exception as e:  # never crash the app because of housekeeping
            log.warning(json.dumps({"event": "retention_error", "error": type(e).__name__}))
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def _lifespan(_app):
    problems = config.production_problems()
    if problems:
        raise RuntimeError("Refusing to start in production with unsafe settings:\n  - " + "\n  - ".join(problems))
    store.init_db()
    if config.ENV == "production" and config.DATABASE_URL and store.backend_name() != "postgres":
        # Fail closed: silently falling back to a local file would split patient records across two stores.
        raise RuntimeError("DATABASE_URL is set but PostgreSQL is not reachable (wrong password, host or database?). "
                           "Refusing to start in production on a fallback database.")
    if config.DATABASE_URL and store.backend_name() != "postgres":
        log.warning(json.dumps({"event": "database_fallback", "detail": "PostgreSQL not reachable - using local SQLite instead"}))
    if store.backend_name() == "postgres" and config.AUTO_INGEST:
        # Idempotent: only changed/new KB chunks are (re)embedded.
        try:
            from backend.rag.ingest import ingest

            ingest("auto", verbose=True)
            retrieval_agent.reset_retriever()
        except Exception as e:  # never block startup on seeding
            print(f"[startup] knowledge-base ingest skipped: {e}")
    task = asyncio.create_task(_retention_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="AI-Driven Clinical Triage System API",
    version="2.0.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,  # set CORS_ORIGINS in .env to restrict
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BODY_BYTES = 1_000_000


@app.middleware("http")
async def _guard(request: Request, call_next):
    """Request id, body-size cap, rate limiting, security headers, metrics and a PHI-free access log."""
    from backend import llm_client

    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    path = request.url.path
    start = time.time()
    llm_client.reset_ai_state()   # fresh AI-usage tracking for this request

    def reply(status: int, detail: str, group: str):
        resp = JSONResponse(status_code=status, content={"detail": detail})
        for k, v in security.security_headers(request).items():
            resp.headers[k] = v
        resp.headers["X-Request-ID"] = rid
        metrics.inc("http_requests_total", group=group, status=str(status))
        return resp

    group = path.split("/")[1] if path.count("/") >= 1 and path != "/" else "root"
    try:
        if int(request.headers.get("content-length", 0)) > MAX_BODY_BYTES:
            return reply(413, "Request too large", group)
    except ValueError:
        return reply(400, "Bad Content-Length", group)

    key = security.client_key(request)
    if path in ("/auth/login", "/auth/register"):
        if not security.limiter.allow("login:" + key, config.LOGIN_RATE_LIMIT_PER_MINUTE):
            metrics.inc("rate_limited_total", group="login")
            return reply(429, "Too many login attempts - wait a minute", group)
    elif request.method == "POST" and path.startswith(security.PATIENT_PATH_PREFIXES):
        if not security.limiter.allow("api:" + key, config.RATE_LIMIT_PER_MINUTE):
            metrics.inc("rate_limited_total", group="api")
            return reply(429, "Too many requests - please slow down", group)

    try:
        response = await call_next(request)
    except Exception as e:   # never leak stack traces to the client
        log.error(json.dumps({"event": "unhandled_error", "req": rid, "path": path, "error": type(e).__name__}))
        return reply(500, "Internal error", group)
    for k, v in security.security_headers(request).items():
        response.headers.setdefault(k, v)
    response.headers["X-Request-ID"] = rid
    metrics.inc("http_requests_total", group=group, status=str(response.status_code))
    if path not in ("/health", "/ready", "/metrics") and not path.startswith("/static"):
        log.info(json.dumps({"event": "http", "req": rid, "method": request.method, "path": path,
                             "status": response.status_code, "ms": int((time.time() - start) * 1000)}))
    return response


_decision_tree = DecisionTreeTriage()  # trained once at startup, reused per request

# In-memory conversation store: {session_id: [message1, message2, ...]}
# Prototype-scope only — a real deployment would use a proper session store
# (Redis, a DB table, etc.) instead of an in-process dict.
_sessions: dict = {}

# In-memory yes/no session store:
#   {session_id: {"known": {...}, "candidates": [...], "tree": CandidateTree}}
_dt_sessions: dict = {}

def _sweep_expired() -> None:
    """Drop abandoned in-memory sessions older than SESSION_TTL_SECONDS."""
    cutoff = time.time() - config.SESSION_TTL_SECONDS
    for sid in [k for k, v in _dt_sessions.items() if v.get("created", 0) < cutoff]:
        _dt_sessions.pop(sid, None)


RAG_CANDIDATE_COUNT = config.RAG_CANDIDATE_COUNT  # how many conditions RAG shortlists before Triage narrows further


class TriageRequest(BaseModel):
    symptoms: str = Field(max_length=config.MAX_INPUT_CHARS)


class ChatMessage(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    message: str = Field(max_length=config.MAX_INPUT_CHARS)


class DTStart(BaseModel):
    message: str = Field(default="", max_length=config.MAX_INPUT_CHARS)  # free-text opener, e.g. "I have chest pain"


class DTAnswer(BaseModel):
    session_id: str = Field(max_length=64)
    symptom: str = Field(max_length=120)
    answer: bool  # True = yes, False = no


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


_DUMMY_HASH = security.hash_password("not-a-real-password")   # equalises timing for unknown users


@app.post("/auth/login")
def login(req: LoginRequest):
    u = req.username.strip().lower()
    if security.login_locked(u):
        store.audit(u, "login_blocked_locked")
        raise HTTPException(status_code=429, detail="Too many failed attempts - this account is locked for a while")
    user = store.get_user(u)
    ok = bool(user) and not user["disabled"] and security.verify_password(req.password, user["password_hash"])
    if not user:
        security.verify_password(req.password, _DUMMY_HASH)
    if not ok:
        security.record_login_failure(u)
        metrics.inc("login_failures_total")
        store.audit(u, "login_failed")
        raise HTTPException(status_code=401, detail="Invalid username or password")
    security.record_login_success(u)
    store.audit(u, "login_ok")
    return {"token": security.make_token(u, "user"), "role": "user", "expires_in": config.TOKEN_TTL_SECONDS}


import re as _re

_RESERVED = {"admin", "administrator", "root", "system", "cli", "local", "staff", "doctor", "clinician"}


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(max_length=200)


@app.post("/auth/register", status_code=201)
def register(req: RegisterRequest, request: Request):
    """Anyone can create a free account. It only gives you a private history of your own results."""
    if not config.REGISTRATION_OPEN:
        raise HTTPException(status_code=403, detail="New accounts are closed on this system")
    if not security.limiter.allow("reg:" + security.client_key(request), config.REGISTER_LIMIT_PER_HOUR, 3600):
        metrics.inc("rate_limited_total", group="register")
        raise HTTPException(status_code=429, detail="Too many accounts created from this device - try later")
    u = req.username.strip().lower()
    if not _re.fullmatch(r"[a-z0-9._-]{3,32}", u) or u in _RESERVED:
        raise HTTPException(status_code=422, detail="Choose a username of 3-32 letters, digits, '.', '_' or '-' (do not use your real name)")
    problem = security.password_problem(req.password, config.MIN_USER_PASSWORD_LEN)
    if problem:
        raise HTTPException(status_code=422, detail=problem[0].upper() + problem[1:])
    if req.password.lower() == u:
        raise HTTPException(status_code=422, detail="Password must be different from the username")
    if store.get_user(u):
        raise HTTPException(status_code=409, detail="That username is taken - try another")
    store.create_user(u, security.hash_password(req.password), "user")
    store.audit(u, "account_created")
    metrics.inc("accounts_created_total")
    return {"token": security.make_token(u, "user"), "role": "user", "username": u, "expires_in": config.TOKEN_TTL_SECONDS}


class PasswordChange(BaseModel):
    old_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


@app.post("/auth/password")
def change_password(req: PasswordChange, user: dict = security.require("user")):
    rec = store.get_user(user["username"])
    if not rec or not security.verify_password(req.old_password, rec["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is wrong")
    problem = security.password_problem(req.new_password, config.MIN_USER_PASSWORD_LEN)
    if problem:
        raise HTTPException(status_code=422, detail=problem[0].upper() + problem[1:])
    store.set_user_password(user["username"], security.hash_password(req.new_password))
    store.audit(user["username"], "password_changed")
    return {"ok": True}


@app.delete("/auth/me")
def delete_my_account(user: dict = security.require("user")):
    """Erase your account and ALL your saved results."""
    n = store.delete_user(user["username"])
    store.audit(user["username"], "account_deleted", None, f"{n} sessions erased")
    return {"deleted": True, "sessions_erased": n}


@app.get("/auth/me")
def whoami(user: dict = security.require("user")):
    return user


@app.get("/ready")
def ready():
    """Readiness probe: can the app reach its database?"""
    try:
        store.list_sessions(limit=1)
        return {"ready": True, "database": store.backend_name()}
    except Exception:
        return JSONResponse(status_code=503, content={"ready": False})


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request):
    """Operational counters only (no patient data). Available from the server itself only."""
    local = security.client_key(request) in ("127.0.0.1", "::1", "localhost", "testclient")
    if not (config.AUTH_MODE == "off" or local):
        raise HTTPException(status_code=403, detail="Metrics are available from the server itself only")
    return PlainTextResponse(metrics.render())


@app.get("/health")
def health():
    live = is_ollama_live()
    return {
        "status": "ok",
        "ollama_connected": live,
        "mode": "live LLM" if live else f"fallback (Ollama not detected at {config.OLLAMA_BASE_URL})",
        "model": config.OLLAMA_MODEL,
        "conditions_in_knowledge_base": len(_decision_tree.kb),
        "retrieval": getattr(retrieval_agent.get_retriever(), "backend_name", "tfidf"),
        "database": store.backend_name(),
        "auth_mode": config.AUTH_MODE,
        "retention_days": config.RETENTION_DAYS,
        "store_sessions": config.STORE_SESSIONS,
    }


class Feedback(BaseModel):
    session_id: str = Field(max_length=64)
    correct: bool
    corrected_condition: str | None = Field(default=None, max_length=200)
    corrected_acuity: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


@app.post("/feedback")
def feedback(fb: Feedback, user: dict = security.require("user")):
    """You (or a clinician you showed the report to) mark one of YOUR saved results right or wrong - the real-world accuracy signal."""
    item = store.get_session(fb.session_id)
    if not item or not _can_see(user, item):
        raise HTTPException(status_code=404, detail="Session not found")
    store.add_feedback(fb.session_id, fb.correct, fb.corrected_condition, fb.corrected_acuity, fb.notes)
    store.audit(user["username"], "feedback_added", fb.session_id)
    return {"ok": True}


def _can_see(user: dict, item: dict) -> bool:
    """Every result belongs to the user who ran it. Nobody else can open it."""
    return bool(item.get("owner")) and item.get("owner") == user["username"]


@app.get("/history")
def history(limit: int = 50, user: dict = security.require("user")):
    """Your own saved results. Nobody else's are ever returned."""
    store.audit(user["username"], "history_listed")
    limit = min(max(limit, 1), 200)
    return {"sessions": store.list_sessions(limit=limit, owner=user["username"], only_owner=True)}


@app.get("/history/{session_id}")
def history_item(session_id: str, user: dict = security.require("user")):
    item = store.get_session(session_id)
    if not item or not _can_see(user, item):
        raise HTTPException(status_code=404, detail="Session not found")   # same answer whether it exists or is someone else's
    store.audit(user["username"], "history_viewed", session_id)
    return item


@app.delete("/history/{session_id}")
def history_delete(session_id: str, user: dict = security.require("user")):
    item = store.get_session(session_id)
    if not item or not _can_see(user, item):
        raise HTTPException(status_code=404, detail="Session not found")
    store.delete_session(session_id)
    store.audit(user["username"], "history_deleted", session_id)
    return {"deleted": session_id}


@app.get("/history/{session_id}/report.pdf")
def history_report(session_id: str, user: dict = security.require("user")):
    """Re-generate the PDF report for one of your saved results."""
    from fastapi import Response
    from backend.report import build_report_pdf

    item = store.get_session(session_id)
    if not item or not _can_see(user, item):
        raise HTTPException(status_code=404, detail="Session not found")
    pdf_bytes = build_report_pdf(item["pipeline"])
    store.audit(user["username"], "history_report_downloaded", session_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=triage_{session_id[:8]}.pdf"},
    )


@app.post("/triage")
def triage(req: TriageRequest):
    """Runs the full pipeline and returns only the final consolidated result."""
    result = run_pipeline_sync(req.symptoms)
    return result


@app.post("/triage/stream")
def triage_stream(req: TriageRequest):
    """
    Streams each agent's output as Server-Sent Events, in order:
    intake -> retrieval -> triage -> recommendation -> final

    NOTE: this is the single-shot path (no clarifying questions). For the
    conversational flow that asks follow-up questions like a real triage
    nurse, use /chat/message instead — see the frontend's chat mode.
    """

    def event_generator():
        for step in run_pipeline(req.symptoms):
            payload = json.dumps(step)
            yield f"data: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/chat/message")
def chat_message(req: ChatMessage, request: Request):
    """
    Conversational intake — mirrors how a real triage nurse works: gather
    symptoms, ask follow-up questions if key details (duration, severity)
    are missing, then run the full pipeline once enough is known.

    Request:  {"session_id": "<uuid or null for a new conversation>", "message": "..."}
    Response, while still gathering info:
        {"type": "question", "session_id": "...", "text": "..."}
    Response, once the pipeline has run:
        {"type": "result", "session_id": "...", "pipeline": [ ...same stage
            events as /triage/stream, collected into a list... ]}
    """
    session_id = req.session_id or str(uuid.uuid4())
    history = _sessions.setdefault(session_id, [])
    history.append(req.message)

    turn_result = intake_agent.run_turn(history)

    if turn_result.get("status") == "needs_info":
        return {
            "type": "question",
            "session_id": session_id,
            "text": turn_result["question"],
        }

    # Enough info gathered — finalize intake and run the rest of the pipeline.
    intake_result = turn_result
    steps = [{"stage": "intake", "result": intake_result}]
    steps.extend(run_from_intake(intake_result, " ".join(history)))

    # Conversation resolved — clear it so a follow-up message starts fresh.
    _sessions.pop(session_id, None)
    _u = security.optional_user(request)
    store.save_session(session_id, "free_text", steps, owner=_u["username"] if _u else None)

    return {
        "type": "result",
        "session_id": session_id,
        "pipeline": steps,
    }


@app.post("/dt/start")
def dt_start(req: DTStart, request: Request):
    """
    Step 1 (Intake): extract initial symptoms mentioned in free text.
    Step 2 (Retrieval/RAG): shortlist the most plausible candidate
        conditions from the knowledge base based on those symptoms.
    Step 3 (Triage): begin asking yes/no questions, but ONLY among
        symptoms relevant to that shortlist — not the full 10-condition
        knowledge base.

    Response includes the RAG shortlist so the frontend can show the
    "considering N possible conditions" step transparently, plus either
    the first question or an immediate result if the shortlist already
    resolves to one candidate.
    """
    _sweep_expired()
    session_id = str(uuid.uuid4())

    # Step 1 — Intake: extract symptoms mentioned in the opener, handling
    # both short openers and long, differently-worded paragraphs via the
    # synonym-aware extractor.
    known = extract_known_symptoms(req.message)

    # Step 2 — Retrieval/RAG: shortlist candidates using the same TF-IDF
    # retriever used elsewhere in the system, so this is genuinely the RAG
    # component doing the narrowing, not a separate mechanism.
    query = req.message if req.message.strip() else " ".join(known.keys())
    rag_matches = retrieval_agent.get_retriever().retrieve(query, top_k=RAG_CANDIDATE_COUNT)

    if not rag_matches:
        # Nothing matched at all — fall back to the full knowledge base
        # rather than dead-ending the conversation.
        rag_matches = [
            {**entry, "similarity": 0.0} for entry in _decision_tree.kb[:RAG_CANDIDATE_COUNT]
        ]

    candidate_ids = [m["id"] for m in rag_matches]

    # Step 3 — Triage: build a tree scoped to exactly this candidate shortlist.
    # Retrieval ranking becomes the prior, so Triage refines rather than ignores it.
    priors = {cid: 1.0 / (rank + 1.5) for rank, cid in enumerate(candidate_ids)}
    tree = _decision_tree.candidate_tree(candidate_ids, priors=priors, prefilled=set(known))

    _dt_sessions[session_id] = {
        "created": time.time(),
        "owner": (security.optional_user(request) or {}).get("username"),   # None = anonymous
        "opener": req.message,
        "known": known,
        "rag_matches": rag_matches,
        "candidate_ids": candidate_ids,
        "tree": tree,
        "qa_log": [
            {"question": f"(From your initial description, confirmed: {', '.join(k for k, v in known.items() if v == 1) or 'nothing specific'}; reported absent: {', '.join(k for k, v in known.items() if v == 0) or 'nothing'})",
             "symptom": None, "answer": True, "is_opener": True}
        ] if known else [],
    }

    resp = _dt_step(session_id)
    flags = safety.detect_red_flags(req.message)
    if flags:
        resp["red_flags"] = flags
        resp["urgent_banner"] = ("Possible emergency signs reported (" + "; ".join(flags)
                                 + "). Seek emergency help immediately - you can keep answering questions on the way.")
    resp["emergency_contacts"] = config.EMERGENCY_CONTACTS
    return resp


@app.post("/dt/answer")
def dt_answer(req: DTAnswer):
    """
    Submits a yes/no answer to the most recently asked question and returns
    either the next question or, once the tree reaches a leaf, the full
    pipeline result.
    """
    if req.session_id not in _dt_sessions:
        return {"type": "error", "text": "Unknown session_id — start a new session with /dt/start."}

    session = _dt_sessions[req.session_id]
    tree = session["tree"]
    prev_standings = tree.current_standings(session["known"])

    session["known"][req.symptom] = 1 if req.answer else 0
    new_standings = tree.current_standings(session["known"])

    elimination_note = _build_elimination_note(prev_standings, new_standings)

    session["qa_log"].append({
        "question": session.get("last_question_text", req.symptom),
        "symptom": req.symptom,
        "answer": req.answer,
        "standings": new_standings,
        "elimination_note": elimination_note,
    })
    return _dt_step(req.session_id)


def _shown(p: float) -> str:
    """Probabilities are estimates from a small model - never display certainty (0% / 100%)."""
    return f"{min(max(p, 0.02), 0.98):.0%}"


def _build_elimination_note(prev_standings: list, new_standings: list) -> str:
    """
    Compares candidate probability estimates before and after the latest
    answer and produces a short, human-readable note on what shifted —
    this is what makes the log explain *why* a condition is being ruled
    out as it happens, rather than only as a final summary.
    """
    prev = {s["condition"]: s["probability"] for s in prev_standings}
    parts = []
    for s in new_standings:
        cond, new_p = s["condition"], s["probability"]
        old_p = prev.get(cond, new_p)
        delta = new_p - old_p
        if delta <= -0.15:
            parts.append(f"{cond} now less likely (about {_shown(old_p)} -> {_shown(new_p)})")
        elif delta >= 0.15:
            parts.append(f"{cond} now more likely (about {_shown(old_p)} -> {_shown(new_p)})")
    if not parts:
        return "No major shift in likelihood from this answer alone."
    return "; ".join(parts) + "."


def _maybe_low_confidence_dt(final: dict, tree, known: dict, entry: dict, yes_symptoms: list, rag_matches: list) -> dict:
    """Turn a weak-evidence result into an honest 'cannot assess' outcome (never for red flags)."""
    if final.get("red_flags"):
        return final  # a detected emergency always stands
    top = tree.blended(known).get(entry["id"], 0.0)
    reason = confidence.interactive_low_confidence(top, yes_symptoms, entry.get("keywords", []))
    if not reason:
        return final
    out = confidence.apply_low_confidence(final, reason, [m["condition"] for m in rag_matches])
    out["confidence"] = round(top, 3)
    return out


def _dt_step(session_id: str):
    """Shared logic: ask the next question, or finalize and run the pipeline."""
    session = _dt_sessions[session_id]
    known = session["known"]
    tree = session["tree"]
    rag_matches = session["rag_matches"]

    next_q = tree.next_question(known)

    if next_q is not None:
        symptom, question_text = next_q
        session["last_question_text"] = question_text  # so the NEXT /dt/answer call can log it
        return {
            "type": "question",
            "session_id": session_id,
            "symptom": symptom,
            "text": question_text,
            "questions_so_far": sum(1 for s in known if s in tree.symptom_index),
            "candidates_considered": [m["condition"] for m in rag_matches],
            "standings": tree.current_standings(known),
            "elimination_note": session["qa_log"][-1].get("elimination_note") if session["qa_log"] else None,
        }

    # Leaf reached — Triage has resolved which candidate this is.
    prediction = tree.predict(known)
    entry = prediction["entry"]
    ruled_out_candidates = prediction["ruled_out_candidates"]
    qa_log = session["qa_log"]

    yes_symptoms = [s for s, v in known.items() if v == 1]
    no_symptoms = [s for s, v in known.items() if v == 0]

    intake_result = {
        "extracted_symptoms": yes_symptoms,
        "ruled_out_symptoms": no_symptoms,
        "duration": "not applicable (yes/no intake mode)",
        "severity_flags": [s for s in yes_symptoms if s in {"severe", "sudden", "worst", "cannot", "radiating"}],
        "reasoning": prediction["reasoning"],
        "raw_input": ", ".join(yes_symptoms),
        "candidates_considered": [m["condition"] for m in rag_matches],
        "ruled_out_candidates": ruled_out_candidates,
        "qa_log": qa_log,
    }

    # Retrieval stage, for pipeline display, reflects the ACTUAL RAG
    # shortlist gathered in /dt/start — not a fresh, potentially
    # contradicting re-search. The final entry (whatever Triage's tree
    # converged on) is surfaced as top_match so Triage and Retrieval can
    # never disagree with each other.
    reordered = [m for m in rag_matches if m["id"] == entry["id"]] + \
                [m for m in rag_matches if m["id"] != entry["id"]]
    top_match = dict(reordered[0])

    retrieval_result = {
        "matches": reordered,
        "top_match": top_match,
        "reasoning": (
            f"RAG retrieved {len(rag_matches)} candidate condition(s) from the knowledge base "
            f"based on the initial symptom description: {', '.join(m['condition'] for m in rag_matches)}. "
            f"Triage's decision-tree questioning, scoped to only this candidate set, converged on "
            f"'{entry['condition']}'" + (f", ruling out {', '.join(ruled_out_candidates)}." if ruled_out_candidates else ".")
        ),
    }

    triage_result = triage_agent.run(intake_result, retrieval_result)
    triage_result["qa_log"] = qa_log  # so the frontend can render the Q&A trail under Triage

    # Worst-case-aware urgency: never settle below the urgency of a plausible, more
    # urgent alternative that the answers have not ruled out.
    _rank = {"EMERGENCY": 0, "URGENT": 1, "ROUTINE": 2}
    alts = tree.plausible_more_urgent(known, entry["id"])
    if alts and _rank.get(alts[0]["acuity_label"], 9) < _rank.get(triage_result.get("acuity_label"), 9):
        names = ", ".join(a["condition"] for a in alts)
        triage_result["pipeline_acuity_label"] = triage_result.get("acuity_label")
        triage_result["acuity_label"] = alts[0]["acuity_label"]
        triage_result["acuity_escalated_for"] = [a["condition"] for a in alts]
        triage_result["reasoning"] = (
            f"{triage_result.get('reasoning', '')} Urgency raised to {alts[0]['acuity_label']} because a more "
            f"serious possibility remains plausible and was not ruled out: {names}."
        ).strip()
    recommendation_result = recommendation_agent.run(triage_result, intake_result)

    steps = [
        {"stage": "intake", "result": intake_result},
        {"stage": "retrieval", "result": retrieval_result},
        {"stage": "triage", "result": triage_result},
        {"stage": "recommendation", "result": recommendation_result},
        {
            "stage": "final",
            "result": _maybe_low_confidence_dt(attach_knowledge_status(finalize({
                "acuity_label": triage_result.get("acuity_label"),
                "confidence": triage_result.get("confidence"),
                "condition": triage_result.get("matched_condition"),
                "recommendation": recommendation_result.get("final_recommendation"),
                "caution": recommendation_result.get("caution"),
                "differential_note": recommendation_result.get("differential_note"),
                "qa_log": qa_log,
                "reasoning_trace": [
                    intake_result.get("reasoning", ""),
                    retrieval_result.get("reasoning", ""),
                    triage_result.get("reasoning", ""),
                    recommendation_result.get("reasoning", ""),
                ],
            }, session.get("opener", "")), entry), tree, known, entry, yes_symptoms, rag_matches),
        },
    ]

    _dt_sessions.pop(session_id, None)
    store.save_session(session_id, "yes_no", steps, owner=session.get("owner"))

    return {
        "type": "result",
        "session_id": session_id,
        "pipeline": steps,
    }


@app.post("/report/pdf")
def report_pdf(payload: dict):
    """
    Generates a formal, clinician-readable PDF summary from a completed
    pipeline result (the same `pipeline` list returned in the "result"
    response from /dt/answer or /chat/message). The frontend's "Download
    Report" button posts that data straight back here.
    """
    from backend.report import build_report_pdf
    from fastapi import Response
    from fastapi.responses import JSONResponse
    import traceback

    if len(json.dumps(payload, default=str)) > 300_000:
        return JSONResponse(status_code=413, content={"error": "Report data too large."})
    pipeline_steps = payload.get("pipeline", [])
    patient_name = payload.get("patient_name", "")

    if not pipeline_steps:
        return JSONResponse(
            status_code=400,
            content={"error": "No pipeline data provided — run a triage session first."},
        )

    try:
        pdf_bytes = build_report_pdf(pipeline_steps, patient_name=patient_name)
    except Exception as e:
        # Surface the real error instead of a bare 500 with no detail, so
        # the frontend's alert (and this log line) show exactly what broke.
        print("[report_pdf] PDF generation failed:")
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"PDF generation failed: {type(e).__name__}: {str(e)}"},
        )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=triage_report.pdf"},
    )


# Serve the single-file frontend from the same origin, so one command runs
# everything: http://localhost:8001/  (no separate http.server, no API_BASE edits).
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


_FRONT_DIR = Path(__file__).resolve().parent.parent / "frontend"
_STATIC = {
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("sw.js", "application/javascript"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}


def _static_route(path: str, fname: str, mime: str):
    def handler():
        f = _FRONT_DIR / fname
        if not f.exists():
            raise HTTPException(status_code=404, detail=f"{fname} not found")
        return FileResponse(f, media_type=mime)
    app.add_api_route(path, handler, methods=["GET"], include_in_schema=False)


for _p, (_f, _m) in _STATIC.items():
    _static_route(_p, _f, _m)


@app.get("/", include_in_schema=False)
def frontend():
    if _FRONTEND.exists():
        return FileResponse(_FRONTEND)
    raise HTTPException(status_code=404, detail="frontend/index.html not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
