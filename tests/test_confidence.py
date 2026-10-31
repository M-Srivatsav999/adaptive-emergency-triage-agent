import pytest
from fastapi.testclient import TestClient

from backend import confidence
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_interactive_rules():
    assert confidence.interactive_low_confidence(0.9, [], ["a"]) is not None            # nothing recognised
    assert confidence.interactive_low_confidence(0.9, ["x"], ["a", "b"]) is not None     # symptoms do not fit best match
    assert confidence.interactive_low_confidence(0.2, ["a"], ["a", "b"]) is not None     # low posterior
    assert confidence.interactive_low_confidence(0.8, ["a"], ["a", "b"]) is None


def test_text_rules_do_not_trust_similarity_alone():
    assert confidence.text_low_confidence(0.40, 0) is not None   # junk text can still have word overlap
    assert confidence.text_low_confidence(0.05, 2) is not None
    assert confidence.text_low_confidence(0.30, 2) is None
    assert confidence.text_low_confidence(0.80, 0) is None       # condition named directly with strong match


def test_apply_never_returns_routine_and_lists_danger_signs():
    out = confidence.apply_low_confidence({"acuity_label": "ROUTINE", "condition": "X", "reasoning_trace": []}, "why", ["A", "B"])
    assert out["acuity_label"] == "URGENT" and out["low_confidence"] is True
    assert "emergency care immediately" in out["caution"] and "A" in out["recommendation"]
    kept = confidence.apply_low_confidence({"acuity_label": "EMERGENCY"}, "why", [])
    assert kept["acuity_label"] == "EMERGENCY"


@pytest.mark.parametrize("text", ["I feel strange and not myself, hard to explain",
                                  "I just feel unwell and tired and something is not right"])
def test_vague_input_gets_honest_cannot_assess(client, text):
    r = client.post("/triage", json={"symptoms": text}).json()
    assert r["low_confidence"] is True and r["acuity_label"] in {"URGENT", "EMERGENCY"}
    assert "No clear match" in r["condition"]


def test_clear_cases_are_not_flagged_low_confidence(client):
    for text in ["runny nose and sneezing since two days", "sudden chest pain going to my left arm and sweating"]:
        assert not client.post("/triage", json={"symptoms": text}).json().get("low_confidence")


def test_red_flag_overrides_low_confidence(client):
    r = client.post("/triage", json={"symptoms": "I feel strange and my father is unconscious and not responding"}).json()
    assert r["acuity_label"] == "EMERGENCY" and not r.get("low_confidence")


def test_result_carries_knowledge_status(client):
    r = client.post("/triage", json={"symptoms": "runny nose and sneezing since two days"}).json()
    assert "reviewed" in r["knowledge_status"].lower()
