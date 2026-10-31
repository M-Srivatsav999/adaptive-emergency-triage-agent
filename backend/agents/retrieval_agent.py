"""
retrieval_agent.py — Owner: Shreyas (RAG & Knowledge Base)

Grounds the pipeline in real reference data by searching the local
knowledge base for conditions matching the patient's symptoms.
"""

from backend.rag.retriever import build_retriever

_retriever = None  # built lazily once, reused across requests


def get_retriever():
    """Public accessor so other modules (e.g. the /dt/start endpoint) can
    reuse this same retriever instance instead of loading a second copy.
    Hybrid (symptom-overlap + TF-IDF [+ pgvector]) - see retriever.py."""
    global _retriever
    if _retriever is None:
        _retriever = build_retriever()
    return _retriever


def reset_retriever() -> None:
    """Force a rebuild (e.g. after ingesting new knowledge)."""
    global _retriever
    _retriever = None


def run(intake_result: dict, top_k: int = 3) -> dict:
    symptoms = intake_result.get("extracted_symptoms", [])
    raw_input = intake_result.get("raw_input", "")

    # Search using both extracted symptoms and the raw text, so a poor
    # intake extraction doesn't fully block retrieval quality.
    query = " ".join(symptoms) + " " + raw_input
    matches = get_retriever().retrieve(query, top_k=top_k)

    reasoning_lines = [
        f"Searched local knowledge base ({len(get_retriever().kb)} conditions) using {getattr(get_retriever(), 'backend_name', 'TF-IDF')} retrieval.",
    ]
    if matches:
        for i, m in enumerate(matches, 1):
            reasoning_lines.append(
                f"Match {i}: '{m['condition']}' (similarity={m['similarity']:.2f}, source: {m['source']})"
            )
    else:
        reasoning_lines.append("No knowledge base entry matched with meaningful similarity.")

    return {
        "matches": matches,
        "top_match": matches[0] if matches else None,
        "reasoning": " ".join(reasoning_lines),
    }


def run_with_forced_match(intake_result: dict, forced_entry: dict, top_k: int = 3) -> dict:
    """
    Used by the decision-tree intake flow. The decision tree already knows
    the correct condition — including which symptoms were explicitly ruled
    out, which a plain text search over "yes" symptoms alone would lose.
    So here, the decision tree's prediction is authoritative and becomes
    top_match directly.

    TF-IDF search still runs, purely as a transparency cross-check shown to
    the user (does an independent text-similarity method agree?) — but it
    does NOT override the decision tree's conclusion, precisely because it
    can't see the "no" answers that the tree reasoned over.
    """
    symptoms = intake_result.get("extracted_symptoms", [])
    raw_input = intake_result.get("raw_input", "")
    query = " ".join(symptoms) + " " + raw_input
    cross_check_matches = get_retriever().retrieve(query, top_k=top_k)

    forced_with_score = dict(forced_entry)
    forced_with_score["similarity"] = 1.0  # exact match: decision tree walked directly to this leaf

    reasoning_lines = [
        f"Decision tree already identified '{forced_entry['condition']}' based on the full yes/no answer "
        f"set (including ruled-out symptoms) — using it as the grounding match.",
    ]
    if cross_check_matches:
        agree = cross_check_matches[0]["condition"] == forced_entry["condition"]
        reasoning_lines.append(
            f"Independent TF-IDF cross-check on positive symptoms alone {'agrees' if agree else 'suggests a different top result, but is not used here since it only sees confirmed-present symptoms, not the ruled-out ones'}: "
            f"'{cross_check_matches[0]['condition']}' (similarity={cross_check_matches[0]['similarity']:.2f})."
        )

    return {
        "matches": [forced_with_score] + cross_check_matches,
        "top_match": forced_with_score,
        "cross_check_matches": cross_check_matches,
        "reasoning": " ".join(reasoning_lines),
    }
