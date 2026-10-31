"""
intake_agent.py — Owner: Srivatsav (Backend & Agent Orchestration)

Extracts structured symptom data from the patient's description.

Two modes:
  run(text)           — original single-shot extraction (kept for
                         backward compatibility with eval scripts / anyone
                         calling the pipeline directly with one message).
  run_turn(history)    — NEW: conversational mode. A real triage nurse
                         doesn't act on one sentence — she asks follow-up
                         questions (duration? sudden or gradual? how
                         severe?) before deciding urgency. This function
                         checks the conversation so far and either:
                           (a) asks ONE clarifying question, or
                           (b) returns a finalized structured extraction,
                               once enough information has been gathered
                               (or after a turn limit, so the conversation
                               can't stall forever).
"""

import json

from backend.llm_client import call_llm, parse_json_response

MAX_CLARIFYING_TURNS = 2  # ask at most this many follow-up questions

EXTRACT_PROMPT = """You are a medical intake assistant. Read the patient's description
below and extract structured information. Think step by step, then output ONLY
valid JSON in this exact format, nothing else:

{{
  "extracted_symptoms": ["symptom1", "symptom2", ...],
  "duration": "as stated, or 'not specified'",
  "severity_flags": ["any words indicating high severity, e.g. sudden, severe, worst"],
  "reasoning": "one or two sentences explaining your extraction"
}}

Patient input: "{patient_text}"
"""

TURN_PROMPT = """You are a triage intake nurse AI having a short conversation with a
patient to gather the information needed for urgency classification.

Conversation so far:
{conversation}

Decide: do you have enough information to proceed (symptoms described, roughly
how long they've had it, and whether it came on suddenly/severely or
gradually/mildly)? A real nurse would ask about at most 2 things before
moving on — don't over-question a clearly urgent case.

Output ONLY valid JSON in ONE of these two formats:

If you need more information, ask exactly ONE short, natural follow-up question:
{{"status": "needs_info", "question": "..."}}

If you have enough to proceed, extract the final structured summary:
{{"status": "complete", "extracted_symptoms": ["..."], "duration": "...",
  "severity_flags": ["..."], "reasoning": "..."}}
"""


def _fallback_extract(patient_text: str) -> str:
    lower = patient_text.lower()
    severity_words = ["severe", "sudden", "worst", "cannot", "radiating"]
    flags = [w for w in severity_words if w in lower]
    return json.dumps({
        "extracted_symptoms": ["see raw text"],
        "duration": "not specified",
        "severity_flags": flags,
        "reasoning": "Built-in rules used (AI model unavailable or too slow) — "
                     "raw text passed through to retrieval agent for keyword matching.",
    })


def run(patient_text: str) -> dict:
    """Original single-shot extraction. Kept for backward compatibility."""
    prompt = EXTRACT_PROMPT.format(patient_text=patient_text)
    raw = call_llm(prompt, fallback_fn=lambda: _fallback_extract(patient_text))
    parsed = parse_json_response(raw)

    parsed.setdefault("extracted_symptoms", [])
    parsed.setdefault("duration", "not specified")
    parsed.setdefault("severity_flags", [])
    parsed.setdefault("reasoning", "")
    parsed["raw_input"] = patient_text
    return parsed


# ---------------------------------------------------------------------------
# Conversational (multi-turn) intake
# ---------------------------------------------------------------------------

DURATION_WORDS = ["day", "days", "hour", "hours", "week", "weeks", "minute",
                   "minutes", "month", "since", "started", "began", "ago"]
SEVERITY_WORDS = ["severe", "sudden", "worst", "cannot", "radiating",
                   "mild", "moderate", "sharp", "dull", "gradually", "slowly"]


def _fallback_turn(history: list) -> str:
    """
    Deterministic fallback conversation logic — used only when Ollama isn't
    running. Asks about whatever's still missing (duration, then severity
    character), then finalizes.
    """
    full_text = " ".join(history).lower()
    has_duration = any(w in full_text for w in DURATION_WORDS)
    has_severity = any(w in full_text for w in SEVERITY_WORDS)
    turns_so_far = len(history)

    if not has_duration and turns_so_far <= MAX_CLARIFYING_TURNS:
        return json.dumps({
            "status": "needs_info",
            "question": "How long have you had these symptoms — hours, days, or longer?"
        })
    if not has_severity and turns_so_far <= MAX_CLARIFYING_TURNS:
        return json.dumps({
            "status": "needs_info",
            "question": "Did this come on suddenly, or has it been building up gradually? "
                        "And would you say it's mild, moderate, or severe?"
        })

    severity_flags = [w for w in ["severe", "sudden", "worst", "cannot", "radiating"] if w in full_text]
    return json.dumps({
        "status": "complete",
        "extracted_symptoms": ["see conversation transcript"],
        "duration": "mentioned in conversation" if has_duration else "not specified",
        "severity_flags": severity_flags,
        "reasoning": "Built-in rules used (AI model unavailable or too slow) — gathered duration and "
                     "severity context across the conversation before finalizing intake.",
    })


def run_turn(history: list) -> dict:
    """
    history: list of patient messages so far (oldest first), e.g.
      ["Chest pain and shortness of breath", "About an hour, came on suddenly"]

    Returns either:
      {"status": "needs_info", "question": "..."}
    or:
      {"status": "complete", "extracted_symptoms": [...], "duration": ...,
       "severity_flags": [...], "reasoning": ..., "raw_input": "<joined text>"}
    """
    joined = " ".join(history)

    # Hard stop: don't ask more than MAX_CLARIFYING_TURNS questions —
    # a real nurse also has to move on eventually, especially if the case
    # already looks urgent.
    if len(history) > MAX_CLARIFYING_TURNS:
        result = run(joined)
        result["status"] = "complete"
        return result

    conversation_text = "\n".join(f"Patient: {m}" for m in history)
    prompt = TURN_PROMPT.format(conversation=conversation_text)
    raw = call_llm(prompt, fallback_fn=lambda: _fallback_turn(history))
    parsed = parse_json_response(raw)

    if parsed.get("status") == "needs_info" and "question" in parsed:
        return {"status": "needs_info", "question": parsed["question"]}

    # treat anything else (including malformed output) as "complete" so the
    # conversation can't get stuck
    parsed.setdefault("status", "complete")
    parsed.setdefault("extracted_symptoms", [])
    parsed.setdefault("duration", "not specified")
    parsed.setdefault("severity_flags", [])
    parsed.setdefault("reasoning", "")
    parsed["raw_input"] = joined
    return parsed
