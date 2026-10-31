"""
decision_tree.py — Owner: Sai (Evaluation) + Srivatsav (integration into intake flow)

WHAT THIS DOES
--------------
Trains a real scikit-learn DecisionTreeClassifier over the knowledge base's
symptom keywords, then uses the trained tree's structure to drive an
interactive yes/no question flow: at each step, it asks about whichever
symptom the tree needs to distinguish between remaining candidate
conditions, walks down the appropriate branch based on the answer, and
stops once it reaches a leaf (a predicted condition).

This is deliberately NOT a hardcoded if/else chain — it's a genuinely
trained classifier, which is also the classical-ML baseline referenced in
our evaluation section (comparing a structured decision-tree diagnosis path
against the LLM-driven free-text path).

WHY THIS FITS THE PROJECT
--------------------------
- Yes/no answers are faster for a patient than free text, and each
  question is chosen by real information gain, not a fixed script.
- The decision path IS the explanation: "you said yes to chest pain, yes
  to sudden onset -> Suspected Myocardial Infarction" is a natural,
  auditable reasoning trace with zero extra work.
- It's fully deterministic and requires no LLM call at all for the
  question-asking phase, so it works identically whether or not Ollama is
  running — a genuinely offline-capable component, not just a fallback.
"""

import json
import os
import random
import re
from functools import lru_cache

from sklearn.tree import DecisionTreeClassifier, _tree

from backend.llm_client import call_llm, is_ollama_live

KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")

SEVERITY_WORDS = {"severe", "sudden", "worst", "cannot", "radiating"}

MAX_QUESTIONS = 20  # pure safety net against a degenerate infinite loop —
# NOT a target question count. The tree is not asked to hit this number;
# next_question() returns None (i.e. "enough is known, finalize") the
# moment its own trained structure reaches a leaf, which happens
# naturally after however many questions the specific case needs — could
# be 1, could be more, driven entirely by the classifier's own splits,
# never by a fixed target.

# Friendlier phrasing for keywords that read awkwardly as raw
# "Do you have {keyword}?" templates. Covers every keyword in the
# knowledge base so no question reaches the patient sounding robotic.
QUESTION_OVERRIDES = {
    "unable to sit still": "Are you so uncomfortable that you are unable to sit still or find a comfortable position?",
    "cough": "Do you have a cough?",
    "confusion": "Are you feeling confused or having trouble thinking clearly?",
    "memory loss": "Have you had any memory loss, such as not remembering what happened?",
    "head injury": "Did you recently hit or injure your head?",
    "headache after injury": "Did your headache start after an injury or a blow to the head?",
    "gritty feeling in eye": "Does your eye feel gritty, as if there is sand in it?",
    "recent unusual meal": "Did you recently eat something unusual, undercooked or from an unfamiliar place?",
    "red eye": "Is your eye red or bloodshot?",
    "itchy eyes": "Are your eyes itchy?",
    "watery eyes": "Are your eyes watery?",
    "eye discharge": "Is there discharge or crusting coming from your eye?",
    "blood in urine": "Have you noticed blood in your urine?",
    "severe flank pain": "Do you have severe pain in your side or lower back (flank)?",
    "severe sore throat": "Is your sore throat severe?",
    "pain radiating to groin": "Does the pain travel down toward your groin?",
    "left arm": "Is the pain radiating down your left arm?",
    "radiating pain": "Is the pain spreading or radiating to another part of your body?",
    "chest pressure": "Does it feel like pressure or tightness in your chest, rather than a sharp pain?",
    "cannot speak full sentences": "Are you having so much trouble breathing that you can't speak in full sentences?",
    "pain moving to right side": "Did the pain start near your belly button and move toward your lower right abdomen?",
    "lower right abdominal pain": "Is the pain specifically in your lower right abdomen?",
    "lower abdominal pain": "Is the pain in your lower abdomen?",
    "chest pain when breathing": "Does your chest hurt more when you breathe in deeply or cough?",
    "throat tightness": "Does your throat feel tight or like it's closing up?",
    "difficulty breathing": "Are you having difficulty breathing?",
    "shortness of breath": "Are you short of breath?",
    "tight chest": "Does your chest feel tight?",
    "wheezing": "Are you wheezing when you breathe?",
    "rash after eating": "Did a rash or reaction start shortly after eating something?",
    "allergic reaction": "Do you think this could be an allergic reaction?",
    "hives": "Do you have hives or raised, itchy welts on your skin?",
    "burning urination": "Do you feel a burning sensation when you urinate?",
    "frequent urination": "Are you urinating more frequently than usual?",
    "cloudy urine": "Is your urine cloudy or unusually colored?",
    "urinary pain": "Do you have pain while urinating?",
    "pelvic pain": "Do you have pelvic pain?",
    "persistent cough": "Have you had a persistent cough?",
    "mild cough": "Is your cough mild?",
    "phlegm": "Are you coughing up phlegm or mucus?",
    "chills": "Are you experiencing chills?",
    "fever": "Do you have a fever?",
    "mild fever": "Do you have a low-grade or mild fever?",
    "fatigue": "Are you feeling unusually fatigued or tired?",
    "severe headache": "Would you describe your headache as severe?",
    "throbbing headache": "Is the headache throbbing or pulsing?",
    "headache with vomiting": "Does your headache come with vomiting?",
    "light sensitivity": "Are you sensitive to light right now?",
    "visual aura": "Are you seeing flashing lights, zigzag lines, or blind spots?",
    "diarrhea": "Do you have diarrhea?",
    "vomiting": "Have you been vomiting?",
    "stomach cramps": "Do you have stomach cramps?",
    "dehydration": "Do you feel very thirsty, dizzy when standing, or otherwise dehydrated?",
    "nausea": "Do you feel nauseous?",
    "runny nose": "Do you have a runny nose?",
    "sneezing": "Are you sneezing a lot?",
    "sore throat": "Do you have a sore throat?",
    "congestion": "Do you have nasal congestion?",
    "ankle pain": "Do you have pain in your ankle?",
    "twisted ankle": "Did you twist or roll your ankle?",
    "sprain": "Does it feel like a sprain (a twist or overstretch), rather than a break?",
    "swelling": "Is there any swelling?",
    "swelling in foot": "Is there swelling in your foot or ankle?",
    "mild swelling": "Would you describe the swelling as mild?",
    "pain when walking": "Does it hurt when you put weight on it or walk?",
    "abdominal pain": "Do you have abdominal pain?",
    "chest pain": "Do you have chest pain?",
    "dizzy": "Do you feel dizzy or lightheaded?",
    "sweating": "Have you been sweating more than usual, without an obvious reason?",
}


# Synonym map: common everyday phrasings -> canonical knowledge-base keyword.
# This is what lets intake work whether the patient writes a short opener
# ("chest pain") or a long, differently-worded paragraph ("I've had this
# awful tightness in my chest and I can't seem to catch my breath properly
# for the last hour or so") — literal substring matching alone would miss
# the second case entirely, since "shortness of breath" never appears
# verbatim. Every entry maps a common alternate phrasing to the exact
# keyword string used in knowledge_base.json.
SYMPTOM_SYNONYMS = {
    "shortness of breath": ["short of breath", "can't breathe", "cant breathe", "cannot breathe",
                             "trouble breathing", "hard to breathe", "catch my breath",
                             "breathless", "out of breath", "gasping for air", "can't get enough air"],
    "difficulty breathing": ["struggling to breathe", "hard time breathing", "labored breathing"],
    "chest pain": ["chest hurts", "pain in my chest", "chest ache", "chest discomfort", "my chest is killing me"],
    "chest pressure": ["pressure in my chest", "chest feels tight", "tightness in my chest"],
    "dizzy": ["lightheaded", "light-headed", "feel faint", "woozy", "room spinning"],
    "nausea": ["nauseous", "feel sick", "want to throw up", "queasy"],
    "vomiting": ["throwing up", "been sick", "puking", "threw up"],
    "sweating": ["sweaty", "cold sweat", "sweating a lot", "perspiring"],
    "fever": ["running a temperature", "feel feverish", "hot and cold", "high temperature"],
    "chills": ["shivering", "cold shivers"],
    "fatigue": ["exhausted", "so tired", "no energy", "worn out"],
    "abdominal pain": ["stomach ache", "stomach pain", "belly pain", "tummy ache", "my stomach hurts"],
    "lower abdominal pain": ["lower stomach pain", "lower belly pain"],
    "lower right abdominal pain": ["lower right stomach pain", "pain on my lower right side"],
    "diarrhea": ["the runs", "loose stools", "watery stools"],
    "stomach cramps": ["cramping", "stomach cramping", "belly cramps"],
    "burning urination": ["burns when i pee", "burning when i urinate", "hurts to pee", "stings when i urinate"],
    "frequent urination": ["peeing a lot", "going to the bathroom a lot", "urinating often"],
    "cloudy urine": ["urine looks cloudy", "murky urine"],
    "urinary pain": ["pain when i pee", "hurts to urinate"],
    "pelvic pain": ["pain in my pelvis"],
    "persistent cough": ["can't stop coughing", "cough won't go away", "coughing a lot"],
    "cough": ["coughing"],
    "phlegm": ["coughing up mucus", "bringing up mucus", "phlegmy cough"],
    "runny nose": ["nose won't stop running", "nose is running"],
    "sore throat": ["throat hurts", "my throat is sore", "scratchy throat"],
    "severe sore throat": ["throat really hurts", "throat is killing me", "excruciating sore throat"],
    "difficulty swallowing": ["hurts to swallow", "painful to swallow", "hard to swallow"],
    "swollen tonsils": ["tonsils are swollen"],
    "swollen lymph nodes": ["swollen glands", "lumps in my neck", "swollen neck glands"],
    "congestion": ["stuffy nose", "stuffed up", "blocked nose"],
    "sneezing": ["sneezing a lot"],
    "severe headache": ["really bad headache", "terrible headache", "splitting headache", "awful headache",
                         "head is paining", "head hurts", "my head hurts", "headache", "head pain", "head is hurting"],
    "headache after injury": ["headache since i hit my head", "head hurts after the fall"],
    "throbbing headache": ["pounding headache", "pulsing headache"],
    "light sensitivity": ["light hurts my eyes", "bright light bothers me", "sensitive to light"],
    "visual aura": ["seeing flashing lights", "seeing zigzag lines", "seeing spots"],
    "head injury": ["hit my head", "bumped my head", "banged my head", "fell and hit my head"],
    "confusion": ["feel confused", "can't think straight", "disoriented"],
    "memory loss": ["can't remember", "memory is fuzzy", "forgot what happened"],
    "wheezing": ["wheezy", "whistling sound when i breathe"],
    "tight chest": ["chest feels tight", "chest tightness"],
    "cannot speak full sentences": ["can barely talk", "too breathless to talk", "can't finish a sentence"],
    "swelling": ["swollen", "puffy", "puffed up"],
    "swelling in foot": ["foot is swollen", "ankle is swollen"],
    "mild swelling": ["a little swollen", "slightly puffy"],
    "ankle pain": ["ankle hurts", "my ankle is sore"],
    "twisted ankle": ["rolled my ankle", "twisted my foot"],
    "pain when walking": ["hurts to walk", "painful to walk on"],
    "throat tightness": ["throat feels tight", "throat closing up", "throat is closing"],
    "hives": ["itchy welts", "raised itchy bumps", "welts on my skin"],
    "rash after eating": ["broke out after eating", "reaction after eating"],
    "allergic reaction": ["allergic to something", "having an allergic reaction"],
    "radiating pain": ["pain spreading", "pain moving", "pain traveling"],
    "left arm": ["down my left arm", "in my left arm"],
    "pain moving to right side": ["pain moved to my right side", "pain shifted to the right"],
    "lower right abdominal pain": ["pain in my lower right belly"],
    "severe flank pain": ["awful pain in my side", "excruciating pain in my back and side"],
    "pain radiating to groin": ["pain going down to my groin", "pain spreading to my groin"],
    "blood in urine": ["blood in my urine", "urine is bloody", "pink or red urine"],
    "unable to sit still": ["can't sit still", "can't get comfortable", "pacing from the pain"],
    "recent unusual meal": ["ate something bad", "food poisoning", "something i ate", "ate at a restaurant"],
    "red eye": ["eye is red", "eyes are red"],
    "itchy eyes": ["eyes are itchy", "itchy eye"],
    "watery eyes": ["eyes are watering", "eye is watering"],
    "eye discharge": ["discharge from my eye", "gunk in my eye", "crusty eye"],
    "gritty feeling in eye": ["feels gritty", "sand in my eye feeling"],
    "mild fever": ["slight fever", "low grade fever"],
    "mild cough": ["light cough", "slight cough"],
    "dehydration": ["very thirsty", "dehydrated", "dizzy when i stand up"],
}


LEXICON_PATH = os.path.join(os.path.dirname(__file__), "symptom_lexicon.json")


def _merge_lexicon() -> None:
    """Merge the data-driven lexicon (natural question wording + everyday /
    rural phrasings for every knowledge-base symptom) into the hand-written
    tables above. Hand-written entries win on question text; synonyms are
    unioned. Adding a condition = editing JSON, never code."""
    if not os.path.exists(LEXICON_PATH):
        return
    with open(LEXICON_PATH, encoding="utf-8") as f:
        lex = json.load(f)
    for sym, q in lex.get("questions", {}).items():
        QUESTION_OVERRIDES.setdefault(sym, q)
    for sym, phrases in lex.get("synonyms", {}).items():
        merged = list(dict.fromkeys(SYMPTOM_SYNONYMS.get(sym, []) + phrases))
        SYMPTOM_SYNONYMS[sym] = merged


_merge_lexicon()


@lru_cache(maxsize=1)
def _kb_symptoms() -> tuple:
    with open(KB_PATH, encoding="utf-8") as f:
        kb = json.load(f)
    return tuple(sorted({kw for e in kb for kw in e["keywords"]}))


NEGATORS = {"no", "not", "never", "without", "denies", "denied", "none", "neither", "nor",
            "isn't", "isnt", "aren't", "arent", "doesn't", "doesnt", "don't", "dont",
            "hasn't", "hasnt", "haven't", "havent", "wasn't", "wasnt", "nothing", "nahi"}
# Conservative scope: a negator only reaches 2 words and never across a conjunction.
# Wrongly ruling a symptom OUT risks under-triage; wrongly keeping it IN only risks
# a cautious over-triage, so ambiguity resolves to "present".
_CLAUSE_BREAK = re.compile(r"[.;!?,]|\b(?:but|however|although|though|and|or|with|plus|also)\b")


def _occurrences(lower: str, phrase: str) -> list:
    """All whole-word matches of `phrase` as (start, end, negated). A match is
    negated when a negator sits within 2 words before it, in the same clause
    (so 'no fever' is negated but 'not drinking and breathing fast' is not)."""
    pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    out = []
    for m in re.finditer(pattern, lower):
        parts = _CLAUSE_BREAK.split(lower[: m.start()])
        clause = parts[-1] if parts else ""
        window = re.findall(r"[a-z']+", clause)[-2:]
        out.append((m.start(), m.end(), any(w in NEGATORS for w in window)))
    return out


def _find_phrase(lower: str, phrase: str):
    """(found, negated) - negated only if EVERY occurrence is negated."""
    occ = _occurrences(lower, phrase)
    if not occ:
        return False, False
    return True, all(n for _, _, n in occ)


def keyword_extract_known_symptoms(text: str) -> dict:
    """
    Fallback extractor — literal substring matching plus a hand-built
    synonym map (see SYMPTOM_SYNONYMS above). This has a hard ceiling: any
    phrasing not anticipated in the synonym list will be missed entirely
    ("head is paining", "eyes are red and are paining" won't match
    anything here, for example). It exists purely so the system still
    functions when Ollama isn't running — it is NOT a substitute for real
    language understanding, which is why extract_known_symptoms() below
    prefers the LLM whenever it's available.
    """
    lower = text.lower().replace("\u2019", "'")

    # Collect every phrase hit (keyword itself + synonyms) with its span.
    hits = []  # (symptom, start, end, negated)
    for symptom in _kb_symptoms():
        for st, en, neg in _occurrences(lower, symptom):
            hits.append((symptom, st, en, neg))
    for canonical, phrases in SYMPTOM_SYNONYMS.items():
        for phrase in phrases:
            for st, en, neg in _occurrences(lower, phrase):
                hits.append((canonical, st, en, neg))

    # Most-specific-wins: drop a hit whose span lies inside a longer hit for a
    # DIFFERENT symptom ("fever" inside "evening fever", "sputum" inside
    # "blood in sputum"), so substrings never invent extra symptoms.
    kept = []
    for sym, st, en, neg in hits:
        inside_longer = any(
            o_sym != sym and o_st <= st and en <= o_en and (o_en - o_st) > (en - st)
            for o_sym, o_st, o_en, _ in hits
        )
        if not inside_longer:
            kept.append((sym, neg))

    found = {}
    for sym, neg in kept:
        if not neg:
            found[sym] = 1
        else:
            found.setdefault(sym, 0)
    return found


EXTRACTION_PROMPT = """You are a medical intake assistant. Below is the fixed list of symptom
terms used in our clinical knowledge base. Read the patient's message,
however casually or unusually phrased, and identify which of these exact
terms apply — including symptoms described in completely different words
than the term itself (e.g. "head is paining" means "headache" or "severe
headache"; "eyes are red and paining" means "red eye").

Known symptom terms (choose only from this exact list):
{symptom_list}

Patient message: "{text}"

Think about what the patient is actually describing in plain language,
then output ONLY a JSON array of the exact matching terms from the list
above (copied exactly, verbatim). If nothing applies, output [].

Example output: ["chest pain", "shortness of breath"]
"""


def _llm_extract(text: str, all_symptoms: list) -> dict:
    symptom_list = ", ".join(all_symptoms)
    prompt = EXTRACTION_PROMPT.format(symptom_list=symptom_list, text=text)
    raw = call_llm(prompt, fallback_fn=lambda: "[]")

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("["), cleaned.rfind("]")
        try:
            items = json.loads(cleaned[start:end + 1]) if start != -1 and end != -1 else []
        except Exception:
            items = []

    valid = set(all_symptoms)
    return {item: 1 for item in items if isinstance(item, str) and item in valid}


def extract_known_symptoms(text: str) -> dict:
    """
    Main entry point for intake extraction. Prefers the LLM (real semantic
    understanding — handles any phrasing, not just anticipated synonyms)
    when Ollama is running, and always also runs the keyword/synonym
    matcher as a supplementary safety net (their union is used), so a
    literal exact-keyword match is never lost even if the LLM call has an
    off moment. Falls back to keyword/synonym matching alone if Ollama
    isn't available at all.
    """
    all_symptoms = list(_kb_symptoms())

    keyword_matches = keyword_extract_known_symptoms(text)

    if is_ollama_live():
        llm_matches = _llm_extract(text, all_symptoms)
        merged = {**keyword_matches, **llm_matches}
        # An explicit patient negation ("no fever") outranks an LLM guess.
        for sym, val in keyword_matches.items():
            if val == 0 and sym in merged:
                merged[sym] = 0
        return merged

    return keyword_matches


class DecisionTreeTriage:
    def __init__(self, kb_path: str = KB_PATH, random_state: int = 42):
        with open(kb_path, "r") as f:
            self.kb = json.load(f)

        self.symptoms = sorted({kw for e in self.kb for kw in e["keywords"]})
        self.symptom_index = {s: i for i, s in enumerate(self.symptoms)}
        self.condition_ids = [e["id"] for e in self.kb]
        self.kb_by_id = {e["id"]: e for e in self.kb}

        X, y = self._build_training_data(random_state)
        self.clf = DecisionTreeClassifier(
            criterion="entropy", max_depth=MAX_QUESTIONS, random_state=random_state
        )
        self.clf.fit(X, y)

    def _build_training_data(self, random_state: int):
        """
        Synthetic training set: for each condition, generate several samples
        where its own keywords are present with high probability and other
        symptoms are present with low probability (simulating overlap /
        comorbidity noise), so the tree learns meaningful, slightly robust
        splits rather than a single brittle path per class.
        """
        rng = random.Random(random_state)
        X, y = [], []
        n_features = len(self.symptoms)

        for entry in self.kb:
            own = set(entry["keywords"])
            for _ in range(20):  # samples per condition
                row = [0] * n_features
                for s in self.symptoms:
                    if s in own:
                        present = rng.random() < 0.9
                    else:
                        present = rng.random() < 0.02
                    if present:
                        row[self.symptom_index[s]] = 1
                X.append(row)
                y.append(entry["id"])
        return X, y

    def question_text(self, symptom: str) -> str:
        return QUESTION_OVERRIDES.get(symptom, f"Do you have {symptom}?")

    def next_question(self, known_answers: dict):
        """
        Walks the trained tree using known_answers (symptom -> 0/1).
        Returns (symptom, question_text) for the next unanswered symptom
        the tree needs, or None if a leaf has been reached (i.e. enough
        is known to predict).
        """
        tree_ = self.clf.tree_
        node = 0
        questions_asked = sum(1 for s in known_answers if s in self.symptom_index)

        while tree_.feature[node] != _tree.TREE_UNDEFINED:
            feature_idx = tree_.feature[node]
            symptom = self.symptoms[feature_idx]

            if symptom not in known_answers:
                if questions_asked >= MAX_QUESTIONS:
                    return None  # force a prediction rather than asking more
                return symptom, self.question_text(symptom)

            value = known_answers[symptom]
            threshold = tree_.threshold[node]
            node = tree_.children_left[node] if value <= threshold else tree_.children_right[node]

        return None  # reached a leaf

    def predict(self, known_answers: dict) -> dict:
        """
        Returns the predicted knowledge base entry once enough is known
        (next_question() returned None), plus the decision path taken as a
        human-readable reasoning trace.
        """
        row = [known_answers.get(s, 0) for s in self.symptoms]
        pred_id = self.clf.predict([row])[0]
        entry = self.kb_by_id[pred_id]

        answered_yes = [s for s, v in known_answers.items() if v == 1 and s in self.symptom_index]
        answered_no = [s for s, v in known_answers.items() if v == 0 and s in self.symptom_index]

        trace = (
            f"Decision tree traversal: confirmed present -> [{', '.join(answered_yes) or 'none'}]; "
            f"confirmed absent -> [{', '.join(answered_no) or 'none'}]. "
            f"Path converged on '{entry['condition']}'."
        )
        return {"entry": entry, "reasoning": trace}

    def candidate_tree(self, candidate_ids: list, random_state: int = 42, priors: dict = None, prefilled: set = None) -> "CandidateTree":
        """
        Trains a SECOND, SMALLER tree restricted to only the given candidate
        condition ids (e.g. the shortlist RAG retrieval already returned).

        This is the fix for asking irrelevant questions: once RAG has
        narrowed 10 conditions down to, say, 3 plausible candidates, there's
        no clinical reason to keep asking about symptoms belonging to the
        7 conditions that were never retrieved as relevant. Restricting the
        tree to just the candidate set means every question asked is
        actually discriminating between the specific possibilities RAG
        already flagged as relevant to this patient — this is also how a
        real differential diagnosis process works (broad retrieval, then
        narrow with targeted questions).

        If only one candidate is given, no questions are needed at all —
        the tree resolves immediately.
        """
        return CandidateTree(self.kb_by_id, candidate_ids, random_state=random_state, priors=priors, prefilled=prefilled)


class CandidateTree:
    """
    A decision tree scoped to a specific subset of conditions (a RAG
    shortlist), rather than the full knowledge base. Same interactive
    next_question()/predict() interface as DecisionTreeTriage, but trained
    fresh — and cheaply, given how small the dataset is — for just this
    candidate set each time.
    """

    # Confidence gate: keep asking (beyond the tree's own leaf) until the
    # calibrated posterior for the leading candidate reaches this level.
    CONFIDENCE_GATE = 0.85
    MIN_QUESTIONS = 3  # always confirm with a few real questions before concluding
    P_OWN, P_OTHER = 0.75, 0.10  # open-world: patients omit some own symptoms and report extras
    # A more-urgent alternative counts as "plausible" at/above this share of the lead.
    ALT_ABS, ALT_REL = 0.15, 0.30

    def __init__(self, kb_by_id: dict, candidate_ids: list, random_state: int = 42, priors: dict = None, prefilled: set = None):
        self.kb_by_id = kb_by_id
        self.prefilled = set(prefilled or ())  # symptoms taken from the opener, not asked
        self.candidates = [kb_by_id[cid] for cid in candidate_ids]
        # Retrieval-derived prior over candidates (sums to 1). Uniform if absent.
        raw = {c["id"]: max((priors or {}).get(c["id"], 1.0), 1e-6) for c in self.candidates}
        tot = sum(raw.values())
        self.priors = {k: v / tot for k, v in raw.items()}

        # Only ask about symptoms that actually appear in at least one
        # candidate — no point asking about symptoms irrelevant to every
        # remaining possibility.
        self.symptoms = sorted({kw for c in self.candidates for kw in c["keywords"]})
        self.symptom_index = {s: i for i, s in enumerate(self.symptoms)}

        if len(self.candidates) <= 1:
            self.clf = None  # nothing to disambiguate
            return

        rng = random.Random(random_state)
        X, y = [], []
        n_features = len(self.symptoms)
        for entry in self.candidates:
            own = set(entry["keywords"])
            for _ in range(20):
                row = [0] * n_features
                for s in self.symptoms:
                    present = (rng.random() < 0.9) if s in own else (rng.random() < 0.02)
                    if present:
                        row[self.symptom_index[s]] = 1
                X.append(row)
                y.append(entry["id"])

        self.clf = DecisionTreeClassifier(criterion="entropy", max_depth=10, random_state=random_state)
        self.clf.fit(X, y)

    def next_question(self, known_answers: dict):
        """
        Next yes/no question, or None when done.

        1. Stop when the calibrated posterior is confident (>= CONFIDENCE_GATE),
           or when the question cap is reached, or no question is informative.
        2. Otherwise follow the scikit-learn tree's own next split - but only if
           it is nearly as informative (expected information gain) as the best
           available question; else ask the most informative one. This keeps the
           tree's learned structure while never wasting a question.
        """
        if self.clf is None:
            return None  # single candidate - already resolved

        questions_asked = sum(1 for s in known_answers if s in self.symptom_index)
        if questions_asked >= MAX_QUESTIONS:
            return None
        post = self.posterior(known_answers)
        asked = sum(1 for s_ in known_answers if s_ in self.symptom_index and s_ not in self.prefilled)
        if max(post.values()) >= self.CONFIDENCE_GATE and asked >= self.MIN_QUESTIONS:
            return None

        # the tree's own next split given the answers so far
        tree_sym = None
        tree_ = self.clf.tree_
        node = 0
        while tree_.feature[node] != _tree.TREE_UNDEFINED:
            symptom = self.symptoms[tree_.feature[node]]
            if symptom not in known_answers:
                tree_sym = symptom
                break
            value = known_answers[symptom]
            node = tree_.children_left[node] if value <= tree_.threshold[node] else tree_.children_right[node]

        best = self._best_unasked(known_answers, post)
        if best is None:
            return None
        pick = best
        if tree_sym is not None and self._gain(tree_sym, post) >= 0.5 * self._gain(best, post):
            pick = tree_sym
        return pick, QUESTION_OVERRIDES.get(pick, f"Do you have {pick}?")

    # ---- Bayesian posterior (with retrieval prior) ------------------------
    def _p(self, symptom: str, cand: dict) -> float:
        return self.P_OWN if symptom in cand["keywords"] else self.P_OTHER

    def posterior(self, known_answers: dict) -> dict:
        import math

        logp = {}
        for c in self.candidates:
            lp = math.log(self.priors[c["id"]])
            for sym, v in known_answers.items():
                if sym not in self.symptom_index:
                    continue
                p = self._p(sym, c)
                lp += math.log(p) if v == 1 else math.log(1 - p)
            logp[c["id"]] = lp
        m = max(logp.values())
        exp = {k: math.exp(v - m) for k, v in logp.items()}
        z = sum(exp.values())
        return {k: v / z for k, v in exp.items()}

    @staticmethod
    def _entropy(d: dict) -> float:
        import math

        return -sum(p * math.log(p) for p in d.values() if p > 0)

    def _gain(self, sym: str, post: dict) -> float:
        """Expected information gain (nats) of asking about `sym`."""
        p_yes = sum(post[c["id"]] * self._p(sym, c) for c in self.candidates)
        if p_yes <= 0 or p_yes >= 1:
            return 0.0
        yes = {c["id"]: post[c["id"]] * self._p(sym, c) / p_yes for c in self.candidates}
        no = {c["id"]: post[c["id"]] * (1 - self._p(sym, c)) / (1 - p_yes) for c in self.candidates}
        return self._entropy(post) - (p_yes * self._entropy(yes) + (1 - p_yes) * self._entropy(no))

    def _best_unasked(self, known_answers: dict, post: dict):
        """Unanswered symptom with the highest expected information gain."""
        best, best_gain = None, 0.01
        for sym in self.symptoms:
            if sym in known_answers:
                continue
            g = self._gain(sym, post)
            if g > best_gain:
                best, best_gain = sym, g
        return best

    def blended(self, known_answers: dict) -> dict:
        """0.3 x decision-tree predict_proba + 0.7 x Bayesian posterior (retrieval prior)."""
        post = self.posterior(known_answers)
        if self.clf is None:
            return post
        row = [known_answers.get(s, 0) for s in self.symptoms]
        tp = dict(zip(self.clf.classes_, self.clf.predict_proba([row])[0]))
        return {cid: 0.3 * float(tp.get(cid, 0.0)) + 0.7 * post[cid] for cid in post}

    def plausible_more_urgent(self, known_answers: dict, lead_id: str) -> list:
        """Candidates more urgent than the lead that remain plausible - triage is
        worst-case aware: the urgency level must not undershoot a plausible emergency."""
        bl = self.blended(known_answers)
        lead = self.kb_by_id[lead_id]
        top = bl.get(lead_id, 0.0)
        out = []
        for c in self.candidates:
            if c["id"] == lead_id or c["acuity"] >= lead["acuity"]:
                continue
            if bl[c["id"]] >= max(self.ALT_ABS, self.ALT_REL * top):
                out.append(c)
        return sorted(out, key=lambda c: (c["acuity"], -bl[c["id"]]))

    def current_standings(self, known_answers: dict) -> list:
        """
        Returns the classifier's real, current probability estimate for
        each remaining candidate condition, given whatever is known so
        far — this is genuine sklearn output (predict_proba), not a
        cosmetic progress bar. Used to show, after every single answer,
        which candidates are becoming more or less likely and why —
        exactly what lets the reasoning log explain *as it happens* why a
        condition is being deprioritized, rather than only revealing the
        elimination logic at the very end.
        """
        if self.clf is None:
            return [{"condition": self.candidates[0]["condition"], "probability": 1.0}]

        blended = self.blended(known_answers)
        standings = [
            {"condition": self.kb_by_id[cid]["condition"], "probability": round(float(p), 3)}
            for cid, p in blended.items()
        ]
        standings.sort(key=lambda x: -x["probability"])
        return standings

    def predict(self, known_answers: dict) -> dict:
        if self.clf is None:
            entry = self.candidates[0]
        else:
            blended = self.blended(known_answers)
            entry = self.kb_by_id[max(blended, key=blended.get)]

        answered_yes = [s for s, v in known_answers.items() if v == 1 and s in self.symptom_index]
        answered_no = [s for s, v in known_answers.items() if v == 0 and s in self.symptom_index]
        other_candidates = [c["condition"] for c in self.candidates if c["id"] != entry["id"]]

        trace_parts = [
            f"Within the RAG-retrieved candidate set ({', '.join(c['condition'] for c in self.candidates)}), "
            f"confirmed present -> [{', '.join(answered_yes) or 'none'}]; "
            f"confirmed absent -> [{', '.join(answered_no) or 'none'}].",
            f"Path converged on '{entry['condition']}'.",
        ]
        if other_candidates:
            trace_parts.append(f"Ruled out from the candidate set: {', '.join(other_candidates)}.")

        return {
            "entry": entry,
            "reasoning": " ".join(trace_parts),
            "ruled_out_candidates": other_candidates,
        }


if __name__ == "__main__":
    # Manual walkthrough for sanity checking
    dt = DecisionTreeTriage()
    known = {}
    known["chest pain"] = 1
    print(dt.next_question(known))
    known["radiating pain"] = 1
    print(dt.next_question(known))
    known["sweating"] = 1
    print(dt.next_question(known))
    print(dt.predict(known))
