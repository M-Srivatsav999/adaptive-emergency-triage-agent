"""A live language model must never be able to lower (or set) the urgency label."""
from backend.agents import triage_agent


def test_model_cannot_lower_urgency(monkeypatch):
    monkeypatch.setattr(triage_agent, "call_llm",
                        lambda prompt, fallback_fn=None: '{"acuity_label": "ROUTINE", "confidence": 0.99, "reasoning": "fine"}')
    top = {"condition": "Snake Bite", "acuity_label": "EMERGENCY", "description": "d"}
    out = triage_agent.run({"extracted_symptoms": ["bite"], "severity_flags": [], "ruled_out_symptoms": []},
                           {"top_match": top})
    assert out["acuity_label"] == "EMERGENCY"
    assert out["model_acuity_label"] == "ROUTINE"


def test_severity_flag_raises_to_emergency(monkeypatch):
    monkeypatch.setattr(triage_agent, "call_llm",
                        lambda prompt, fallback_fn=None: '{"acuity_label": "ROUTINE"}')
    top = {"condition": "Sprain", "acuity_label": "ROUTINE", "description": "d"}
    out = triage_agent.run({"extracted_symptoms": ["pain"], "severity_flags": ["severe"], "ruled_out_symptoms": []},
                           {"top_match": top})
    assert out["acuity_label"] == "EMERGENCY"
