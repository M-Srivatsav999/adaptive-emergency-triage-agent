"""
recommendation_agent.py — Owner: Srivatsav (Backend & Agent Orchestration)

Produces the final patient-facing recommendation, including any medication
or safety cautions attached to the matched condition in the knowledge base.

Also generates a "differential note" when other candidate conditions were
considered and ruled out during triage (e.g. RAG shortlisted Common Cold
and Bacterial Pneumonia; Triage's questioning ruled out Common Cold) — if
those ruled-out possibilities share overlapping symptoms with the final
diagnosis, it's clinically responsible to mention what to watch for in
case the picture evolves, rather than silently discarding that context.
"""

from backend.llm_client import call_llm, parse_json_response

PROMPT_TEMPLATE = """You are finalizing guidance for a patient. Based on the triage
classification and reference recommendation below, write a clear, calm,
patient-facing recommendation. Do not add any medical advice beyond what is
provided in the reference material.

If other candidate conditions were considered and ruled out during triage,
briefly note (in a separate "differential_note" field, not the main
recommendation) what symptoms would suggest reconsidering one of those
alternatives, so the patient knows what to watch for if their condition
changes. Keep this brief and only include it if genuinely useful — leave
it empty if the ruled-out candidates aren't clinically relevant to mention.

Think step by step, then output ONLY valid JSON in this exact format:

{{
  "final_recommendation": "clear patient-facing guidance",
  "differential_note": "brief note on what to watch for re: ruled-out candidates, or empty string",
  "reasoning": "brief explanation of how you composed this from the reference data"
}}

Acuity: {acuity}
Reference recommendation: {rec}
Reference caution: {caution}
Other candidates considered and ruled out during triage: {ruled_out_candidates}
"""


def _fallback(rec: str, caution: str, ruled_out_candidates: list) -> str:
    note = ""
    if ruled_out_candidates:
        note = (
            f"Triage also considered {', '.join(ruled_out_candidates)} before ruling "
            f"them out based on your answers — if new symptoms develop, mention this to a clinician."
        )
    return (
        f'{{"final_recommendation": "{rec}", '
        f'"differential_note": "{note}", '
        f'"reasoning": "Built-in rules used (AI model unavailable or too slow) — reference '
        f'recommendation passed through directly."}}'
    )


def run(triage_result: dict, intake_result: dict = None) -> dict:
    source = triage_result.get("recommendation_source")
    ruled_out_candidates = (intake_result or {}).get("ruled_out_candidates") or triage_result.get("ruled_out_candidates", [])

    if not source:
        return {
            "final_recommendation": "Unable to generate a grounded recommendation. Please consult a healthcare provider directly.",
            "caution": None,
            "differential_note": "",
            "reasoning": "No matched condition was available from the triage step.",
        }

    rec = source.get("recommendation", "")
    caution = source.get("caution")

    prompt = PROMPT_TEMPLATE.format(
        acuity=triage_result.get("acuity_label"),
        rec=rec,
        caution=caution or "none",
        ruled_out_candidates=", ".join(ruled_out_candidates) or "none",
    )
    raw = call_llm(prompt, fallback_fn=lambda: _fallback(rec, caution, ruled_out_candidates))
    parsed = parse_json_response(raw)

    parsed.setdefault("final_recommendation", rec)
    parsed.setdefault("differential_note", "")
    parsed.setdefault("reasoning", "")
    parsed["caution"] = caution
    return parsed
