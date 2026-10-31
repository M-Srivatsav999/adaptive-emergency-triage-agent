"""
orchestrator.py — Owner: Srivatsav (Backend & Agent Orchestration)

Coordinates the four-agent pipeline in a fixed sequence:
  Intake -> Retrieval -> Triage -> Recommendation

Each stage's output feeds the next. Yields progress after each stage so
the API layer can stream results to the frontend via Server-Sent Events,
giving the explainability layer real-time, step-by-step visibility.
"""

from backend.agents import intake_agent, retrieval_agent, triage_agent, recommendation_agent


DISCLAIMER = ("Decision-support only - not a diagnosis and not a substitute for a doctor. "
              "If you are worried or symptoms get worse, seek care.")


def finalize(final: dict, patient_text: str) -> dict:
    """Attach the deterministic red-flag safety override, local emergency
    contacts and the standard disclaimer to every final result."""
    from backend import config, safety

    final = safety.apply_safety_override(final, safety.detect_red_flags(patient_text))
    final["emergency_contacts"] = config.EMERGENCY_CONTACTS
    from backend import llm_client

    final.update(llm_client.ai_mode())
    from backend import metrics

    metrics.inc("triage_results_total", acuity=str(final.get("acuity_label")))
    metrics.inc("ai_mode_total", mode=final.get("ai_mode", "unknown"))
    if final.get("red_flags"):
        metrics.inc("triage_red_flag_total")
    final["disclaimer"] = DISCLAIMER
    return final


def attach_knowledge_status(final: dict, entry: dict) -> dict:
    """Record how much clinician review stands behind the matched entry (shown in UI and PDF)."""
    from backend.rag.review import status_label

    final = dict(final)
    final["knowledge_status"] = status_label(entry or {})
    # Sources the entry was checked against (links + titles only; our wording is our own)
    final["references"] = [{"title": r.get("title"), "url": r.get("url")} for r in (entry or {}).get("references", [])][:3]
    return final


def run_from_intake(intake_result: dict, patient_text: str = ""):
    """
    Generator that continues the pipeline from an already-finalized intake
    result (used by the conversational /chat flow once enough information
    has been gathered), running Retrieval -> Triage -> Recommendation.
    Yields the same stage events as run_pipeline(), minus "intake".
    """
    retrieval_result = retrieval_agent.run(intake_result)
    yield {"stage": "retrieval", "result": retrieval_result}

    triage_result = triage_agent.run(intake_result, retrieval_result)
    yield {"stage": "triage", "result": triage_result}

    recommendation_result = recommendation_agent.run(triage_result, intake_result)
    yield {"stage": "recommendation", "result": recommendation_result}

    final = finalize({
        "acuity_label": triage_result.get("acuity_label"),
        "confidence": triage_result.get("confidence"),
        "condition": triage_result.get("matched_condition"),
        "recommendation": recommendation_result.get("final_recommendation"),
        "caution": recommendation_result.get("caution"),
        "reasoning_trace": [
            intake_result.get("reasoning", ""),
            retrieval_result.get("reasoning", ""),
            triage_result.get("reasoning", ""),
            recommendation_result.get("reasoning", ""),
        ],
    }, patient_text)

    # Honest 'cannot assess' outcome when retrieval found nothing convincing
    # (a detected red flag always stands).
    from backend import confidence

    final = attach_knowledge_status(final, retrieval_result.get("top_match") or {})
    if not final.get("red_flags"):
        top = (retrieval_result.get("top_match") or {}).get("similarity", 0.0) or 0.0
        from backend.rag.decision_tree import keyword_extract_known_symptoms

        n_rec = sum(1 for v in keyword_extract_known_symptoms(patient_text or "").values() if v == 1)
        reason = confidence.text_low_confidence(top, n_rec)
        if reason:
            names = [m.get("condition") for m in retrieval_result.get("matches", [])]
            final = confidence.apply_low_confidence(final, reason, names)
    yield {"stage": "final", "result": final}


def run_pipeline(patient_text: str):
    """
    Generator that yields a dict after each agent completes:
      {"stage": "intake", "result": {...}}
      {"stage": "retrieval", "result": {...}}
      {"stage": "triage", "result": {...}}
      {"stage": "recommendation", "result": {...}}
      {"stage": "final", "result": {...}}   <- consolidated output

    This is the single-shot path (one message in, full pipeline runs
    immediately). For the conversational, question-asking flow, see
    the /chat/message endpoint in main.py, which uses intake_agent.run_turn()
    plus run_from_intake() below instead.
    """
    intake_result = intake_agent.run(patient_text)
    yield {"stage": "intake", "result": intake_result}

    yield from run_from_intake(intake_result, patient_text)


def run_pipeline_sync(patient_text: str) -> dict:
    """Non-streaming convenience wrapper — runs the full pipeline and
    returns only the final consolidated result. Useful for evaluation
    scripts and tests that don't need step-by-step streaming."""
    final = None
    for step in run_pipeline(patient_text):
        if step["stage"] == "final":
            final = step["result"]
    return final
