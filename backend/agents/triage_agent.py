"""
triage_agent.py — Owner: Srivatsav (Backend & Agent Orchestration)

Classifies patient urgency (EMERGENCY / URGENT / ROUTINE) using the
retrieved knowledge base context and the intake agent's severity flags.
This is the agent whose reasoning becomes the core of the explainability
trace shown to the user.
"""

from backend.llm_client import call_llm, parse_json_response

PROMPT_TEMPLATE = """You are a triage nurse AI. Based on the patient's confirmed symptoms and
the retrieved medical reference context below, classify urgency as one of:
EMERGENCY, URGENT, or ROUTINE.

IMPORTANT: Base your reasoning ONLY on the symptoms explicitly listed below.
Do not assume or invent details (such as onset timing or severity) that
were not explicitly confirmed. If something is listed as "ruled out" /
"confirmed absent", treat it as genuinely absent — do not reason as if it
might still be present. The retrieved reference condition below is already
the conclusion of a decision-tree process that considered and eliminated
other candidates — do not second-guess or override it with a different
condition; your job is to classify its urgency and explain why, not to
re-diagnose.

Think step by step, then output ONLY valid JSON in this exact format:

{{
  "acuity_label": "EMERGENCY | URGENT | ROUTINE",
  "confidence": 0.0-1.0,
  "reasoning": "step-by-step chain of thought citing only the confirmed symptoms below"
}}

Confirmed present: {symptoms}
Confirmed absent (explicitly ruled out): {ruled_out}
Severity flags noted during intake: {severity_flags}
Other candidate conditions considered and ruled out: {ruled_out_candidates}
Retrieved reference condition: {condition} (reference acuity: {ref_acuity})
Reference description: {description}
"""


def _fallback(top_match: dict, severity_flags: list) -> str:
    """Deterministic stand-in used only when Ollama is unavailable."""
    if not top_match:
        return '{"acuity_label": "UNKNOWN", "confidence": 0.0, "reasoning": "No retrieved context available to ground a classification."}'

    acuity = top_match["acuity_label"]
    confidence = 0.6 + top_match.get("similarity", 0) * 0.3
    if severity_flags and acuity != "EMERGENCY":
        acuity = "EMERGENCY"
        confidence = 0.85
        note = " Severity flags triggered an escalation override."
    else:
        note = ""
    return (
        f'{{"acuity_label": "{acuity}", "confidence": {round(confidence, 2)}, '
        f'"reasoning": "Built-in rules used (AI model unavailable or too slow) — classification '
        f'based on retrieved reference condition \'{top_match["condition"]}\'.{note}"}}'
    )


def run(intake_result: dict, retrieval_result: dict) -> dict:
    top_match = retrieval_result.get("top_match")
    severity_flags = intake_result.get("severity_flags", [])
    ruled_out_symptoms = intake_result.get("ruled_out_symptoms", [])
    ruled_out_candidates = intake_result.get("ruled_out_candidates", [])

    if not top_match:
        return {
            "acuity_label": "UNKNOWN",
            "confidence": 0.0,
            "reasoning": "No knowledge base match was retrieved, so a safe classification cannot be made. Recommend direct clinician consultation.",
            "matched_condition": None,
        }

    prompt = PROMPT_TEMPLATE.format(
        symptoms=", ".join(intake_result.get("extracted_symptoms", [])) or intake_result.get("raw_input", ""),
        ruled_out=", ".join(ruled_out_symptoms) or "none recorded",
        severity_flags=", ".join(severity_flags) or "none",
        ruled_out_candidates=", ".join(ruled_out_candidates) or "none",
        condition=top_match["condition"],
        ref_acuity=top_match["acuity_label"],
        description=top_match["description"],
    )
    raw = call_llm(prompt, fallback_fn=lambda: _fallback(top_match, severity_flags))
    parsed = parse_json_response(raw)

    # The urgency label is NEVER taken from the language model. It comes from the matched
    # knowledge-base entry (raised to EMERGENCY by severity flags), so a live model can only
    # influence wording and confidence text, not the routing decision.
    parsed["model_acuity_label"] = parsed.get("acuity_label")
    parsed["acuity_label"] = "EMERGENCY" if severity_flags else top_match["acuity_label"]
    parsed.setdefault("confidence", 0.7)
    parsed.setdefault("reasoning", "")
    parsed["matched_condition"] = top_match["condition"]
    parsed["recommendation_source"] = top_match
    parsed["ruled_out_candidates"] = ruled_out_candidates
    return parsed
