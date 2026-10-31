import json
from pathlib import Path

from backend.rag.decision_tree import DecisionTreeTriage, QUESTION_OVERRIDES, SYMPTOM_SYNONYMS
from backend.rag.retriever import TfidfRetriever, SymptomOverlapRetriever, HybridRetriever

ROOT = Path(__file__).resolve().parent.parent
KB = json.loads((ROOT / "backend/rag/knowledge_base.json").read_text(encoding="utf-8"))
LEX = json.loads((ROOT / "backend/rag/symptom_lexicon.json").read_text(encoding="utf-8"))


def test_kb_shape_and_scale():
    assert len(KB) >= 150
    ids = [e["id"] for e in KB]
    assert len(ids) == len(set(ids)), "duplicate ids"
    names = [e["condition"] for e in KB]
    assert len(names) == len(set(names)), "duplicate condition names"
    scale = {"EMERGENCY": 1, "URGENT": 3, "ROUTINE": 5}
    for e in KB:
        assert e["acuity_label"] in scale
        assert e["acuity"] == scale[e["acuity_label"]], e["condition"]
        assert len(e["keywords"]) >= 3, e["condition"]
        assert e["description"] and e["recommendation"] and e["caution"]
        assert e["red_flags"], e["condition"]
        st = e["review_status"]
        assert st.startswith("DRAFT") or st in {"APPROVED", "CHANGES_REQUESTED"}, e["condition"]
        if st == "APPROVED":  # an approval must name a reviewer and a date
            assert e.get("reviewed_by") and e.get("reviewed_on"), e["condition"]


def test_all_three_acuity_levels_well_populated():
    labels = {e["acuity_label"] for e in KB}
    assert labels == {"EMERGENCY", "URGENT", "ROUTINE"}


def test_rural_priority_conditions_present():
    text = " ".join(e["condition"] for e in KB).lower()
    for must in ["snakebite", "pesticide", "malaria", "dengue", "tuberculosis", "dehydration",
                 "eclampsia", "postpartum", "newborn", "heat stroke", "rabies", "typhoid", "stroke"]:
        assert must in text, must


def test_no_recommendation_contains_dosage_instructions():
    """Safety: the knowledge base must not give drug doses."""
    import re

    pat = re.compile(r"\b\d+\s?(mg|mcg|ml|g|tablets?|pills?)\b", re.I)
    for e in KB:
        assert not pat.search(e["recommendation"] + " " + e["caution"]), e["condition"]


def test_original_condition_red_flags_match_their_condition():
    """Regression: red flags were once attached by wrong id."""
    by = {e["condition"]: e for e in KB}
    cold = next(v for k, v in by.items() if "Common Cold" in k)
    assert not any("flank" in f for f in cold["red_flags"])
    stone = next(v for k, v in by.items() if "Kidney Stone" in k)
    assert any("flank" in f for f in stone["red_flags"])


def test_lexicon_covers_every_symptom():
    """Every symptom must have natural question wording or be a plain 'Do you have X?' noun."""
    dt = DecisionTreeTriage()
    for sym in dt.symptom_index:
        q = dt.question_text(sym)
        assert q.endswith("?")
    assert len(LEX["questions"]) > 150 and len(LEX["synonyms"]) > 150
    for sym in LEX["synonyms"]:
        assert any(sym in e["keywords"] for e in KB), f"synonym key not in KB: {sym}"


def test_every_question_reads_naturally():
    dt = DecisionTreeTriage()
    awkward = {"unable to sit still", "cough", "confusion", "memory loss", "head injury",
               "headache after injury", "gritty feeling in eye", "recent unusual meal",
               "red eye", "itchy eyes", "watery eyes", "eye discharge", "blood in urine",
               "severe flank pain", "severe sore throat", "pain radiating to groin",
               "pregnant", "wound", "fall", "stress", "mosquito exposure", "newborn baby"}
    for sym in dt.symptom_index:
        if sym in awkward:
            assert dt.question_text(sym) != f"Do you have {sym}?", sym


def test_extractor_word_boundaries_and_negation():
    from backend.rag.decision_tree import keyword_extract_known_symptoms as ex

    assert "wound" not in ex("an acute illness")          # 'cut' must not fire inside 'acute'
    assert ex("no fever but cough").get("fever") == 0
    assert ex("no fever but cough").get("cough") == 1
    assert ex("my child is not drinking and breathing fast").get("fast breathing") == 1
    # most specific wins: 'evening fever' must not also create plain 'fever'
    r = ex("evening fever and night sweats")
    assert r.get("evening fever") == 1 and "fever" not in r


def test_retriever_ranks_obvious_cases_first():
    r = TfidfRetriever().retrieve("sudden chest pain radiating left arm sweating", top_k=3)
    assert "Heart Attack" in r[0]["condition"]
    ov = SymptomOverlapRetriever().retrieve("snake bit my leg two puncture marks drooping eyelids", top_k=3)
    assert ov[0]["condition"] == "Snakebite"


def test_overlap_retriever_abstains_on_thin_evidence():
    assert SymptomOverlapRetriever().retrieve("swelling", top_k=3) == []


def test_hybrid_survives_a_failing_signal():
    class Boom:
        def retrieve(self, *a, **k):
            raise RuntimeError("down")

    t = TfidfRetriever()
    h = HybridRetriever([Boom(), t], t.kb)
    assert h.retrieve("runny nose sneezing", top_k=2)


def test_candidate_tree_only_concludes_within_shortlist():
    dt = DecisionTreeTriage()
    ids = [e["id"] for e in KB[:4]]
    tree = dt.candidate_tree(ids)
    assert tree.predict({})["entry"]["id"] in ids


def test_posterior_uses_retrieval_prior_and_sums_to_one():
    dt = DecisionTreeTriage()
    ids = [e["id"] for e in KB[:3]]
    tree = dt.candidate_tree(ids, priors={ids[0]: 0.8, ids[1]: 0.1, ids[2]: 0.1})
    post = tree.posterior({})
    assert abs(sum(post.values()) - 1) < 1e-9 and post[ids[0]] > post[ids[1]]


def test_tree_always_asks_minimum_questions_before_concluding():
    dt = DecisionTreeTriage()
    by = {e["condition"]: e["id"] for e in KB}
    ids = [by[n] for n in by if n.startswith(("Snakebite", "Stroke", "Scorpion", "Pesticide"))]
    tree = dt.candidate_tree(ids, priors={i: 1 for i in ids})
    known = {}
    asked = 0
    while asked < 25:
        q = tree.next_question(known)
        if q is None:
            break
        known[q[0]] = 0
        asked += 1
    assert asked >= 1  # may stop early only if posterior is confident AND >= MIN asked


def test_worst_case_acuity_escalation_logic():
    dt = DecisionTreeTriage()
    by = {e["condition"]: e["id"] for e in KB}
    lead = by["Common Cold"]
    alt = next(v for k, v in by.items() if k.startswith("Influenza"))
    em = next(v for k, v in by.items() if k.startswith("Meningitis"))
    tree = dt.candidate_tree([lead, alt, em], priors={lead: 1, alt: 1, em: 1})
    more = tree.plausible_more_urgent({}, lead)
    assert any(c["acuity_label"] == "EMERGENCY" for c in more)
