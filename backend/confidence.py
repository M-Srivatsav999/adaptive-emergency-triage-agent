"""
confidence.py - 'I cannot assess this' safety net.

A triage tool that always names *some* condition is dangerous once the knowledge
base is large but still finite: a presentation outside its scope would be forced
into the nearest-looking entry. When the evidence is weak we therefore say so
plainly, advise seeing a health worker soon (never ROUTINE), and list general
danger signs that mean 'go to emergency care now'.
"""

LOW_CONFIDENCE = 0.40        # top blended probability below this => low confidence
LOW_SIMILARITY = 0.12        # free-text path: best retrieval similarity below this
TRUST_SIMILARITY = 0.50      # with zero recognised symptoms, trust text similarity only above this

GENERAL_DANGER_SIGNS = (
    "Go to emergency care immediately for any of these: difficulty breathing; chest pain; "
    "fainting or being unable to wake the person; fits; heavy bleeding; severe or worsening pain; "
    "confusion or unusual drowsiness; being unable to drink or feed; very high fever with a stiff neck "
    "or a rash that does not fade; a pregnant woman with bleeding, severe headache or reduced baby "
    "movements; swallowing poison; or thoughts of harming yourself."
)

_RANK = {"EMERGENCY": 0, "URGENT": 1, "ROUTINE": 2}


def interactive_low_confidence(top_prob: float, yes_symptoms: list, entry_keywords: list):
    """Reason string if the yes/no session ended with weak evidence, else None."""
    if not yes_symptoms:
        return "no symptoms were recognised from the description"
    if not (set(yes_symptoms) & set(entry_keywords)):
        return "none of the reported symptoms is typical of the best-matching condition"
    if top_prob < LOW_CONFIDENCE:
        return f"confidence in the best match is low ({top_prob:.0%})"
    return None


def text_low_confidence(top_similarity: float, n_recognised: int):
    """
    Reason string for the free-text path, else None.
    `n_recognised` = number of known symptoms the lexicon extractor actually found
    in the patient's words. Text-similarity alone is NOT trusted: junk or vague text
    still has some word overlap with some condition.
    """
    if n_recognised == 0 and top_similarity < TRUST_SIMILARITY:
        return "no known symptom was recognised in the description"
    if top_similarity < LOW_SIMILARITY:
        return "the description matches no condition in the knowledge base closely"
    return None


def apply_low_confidence(final: dict, reason: str, candidates: list) -> dict:
    """Rewrite a final result as an honest 'cannot assess' outcome."""
    from backend import metrics

    metrics.inc("triage_low_confidence_total")
    final = dict(final)
    names = [c for c in candidates if c][:3]
    final["low_confidence"] = True
    final["low_confidence_reason"] = reason
    final["considered_conditions"] = names
    final["condition"] = "No clear match - a health worker needs to assess this"
    if _RANK.get(final.get("acuity_label"), 9) > _RANK["URGENT"]:
        final["pipeline_acuity_label"] = final.get("acuity_label")
        final["acuity_label"] = "URGENT"
    seen = (" The tool considered: " + "; ".join(names) + " (not a diagnosis).") if names else ""
    final["recommendation"] = (
        "The symptoms described do not clearly match a condition this tool knows well, so it cannot give "
        "a specific assessment. Please see a doctor or health worker soon - today if you feel worse." + seen
    )
    final["caution"] = GENERAL_DANGER_SIGNS
    final["differential_note"] = None
    final["knowledge_status"] = "No knowledge-base entry matched this description"
    final["references"] = []
    trace = list(final.get("reasoning_trace") or [])
    trace.append(f"Low-confidence outcome: {reason}. The tool did not force a diagnosis.")
    final["reasoning_trace"] = trace
    return final
