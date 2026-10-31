import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.rag.decision_tree import keyword_extract_known_symptoms as extract
from backend.safety import RED_FLAGS, detect_red_flags

ROOT = Path(__file__).resolve().parent.parent
KB = {e["condition"]: e for e in json.loads((ROOT / "backend/rag/knowledge_base.json").read_text(encoding="utf-8"))}
LEX = json.loads((ROOT / "backend/rag/symptom_lexicon.json").read_text(encoding="utf-8"))
DEV = re.compile("[\u0900-\u097F]")
TEL = re.compile("[\u0C00-\u0C7F]")


def _entry(prefix):
    return next(v for k, v in KB.items() if k.startswith(prefix))


def test_source_checked_entries_have_valid_references():
    checked = [e for e in KB.values() if e.get("source_check")]
    assert len(checked) >= 9
    for e in checked:
        assert e["references"], e["condition"]
        for r in e["references"]:
            assert r["title"] and r["url"].startswith("https://"), e["condition"]
        sc = e["source_check"]
        assert sc["checked_on"] and sc["points_confirmed"]
        assert "not a clinician" in sc["status"]          # never confused with clinical review


def test_source_check_does_not_imply_clinical_approval():
    for e in KB.values():
        if e.get("source_check"):
            assert not e["review_status"] == "APPROVED" or e.get("reviewed_by")


def test_corrections_from_source_check_are_present():
    assert "stitched" in _entry("Animal Bite")["caution"]
    heart = _entry("Suspected Myocardial")["caution"].lower()
    assert "allergic" in heart and "under 16" in heart
    for name in ("Gastroenteritis", "Severe Dehydration", "Dysentery"):
        assert "zinc" in _entry(name)["self_care"].lower()
    dengue = _entry("Dengue")
    assert "ibuprofen" in dengue["caution"].lower() and "rapid breathing" in dengue["red_flags"]
    assert "20 minutes" in _entry("Minor Burn")["recommendation"] and "chemical or electrical" in _entry("Minor Burn")["caution"]


def test_result_carries_references_for_checked_entry():
    with TestClient(app) as c:
        r = c.post("/triage", json={"symptoms": "snake bit my leg, two puncture marks"}).json()
    assert r["references"] and r["references"][0]["url"].startswith("https://www.who.int")


@pytest.mark.parametrize("text,expected", [
    ("mujhe bukhar hai aur sir dard, pet dard aur ulti ho rahi hai", {"fever", "headache", "abdominal pain", "vomiting"}),
    ("naku jwaram undi, daggu, kadupu noppi, vantulu", {"fever", "cough", "abdominal pain", "vomiting"}),
    ("मुझे बुखार और खांसी है, सीने में दर्द", {"fever", "cough", "chest pain"}),
    ("తలనొప్పి మరియు జ్వరం", {"headache", "fever"}),
])
def test_hindi_and_telugu_symptom_words_recognised(text, expected):
    found = {k for k, v in extract(text).items() if v == 1}
    assert expected <= found


@pytest.mark.parametrize("text", [
    "mere bete ko saanp ne kaata", "पापा को साँप ने काटा", "మా నాన్నకు పాము కాటు",
    "amma spruha tappindi", "అమ్మ స్పృహ తప్పింది", "bacche ko mirgi ka daura pad raha hai", "aatmahatya ka khayal aa raha hai",
])
def test_hindi_and_telugu_emergencies_flagged(text):
    assert detect_red_flags(text)


def test_benign_hindi_telugu_not_flagged():
    for t in ["mujhe bukhar hai aur sir dard", "naku jwaram undi", "pet dard aur ulti ho rahi hai"]:
        assert detect_red_flags(t) == []


def test_no_mixed_script_or_empty_phrases_anywhere():
    for sym, phrases in LEX["synonyms"].items():
        for p in phrases:
            assert p.strip() and not (DEV.search(p) and TEL.search(p)), (sym, p)
    for label, phrases in RED_FLAGS:
        for p in phrases:
            assert p.strip() and not (DEV.search(p) and TEL.search(p)), (label, p)
