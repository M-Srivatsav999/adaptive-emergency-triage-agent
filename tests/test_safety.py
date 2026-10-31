import pytest

from backend.safety import detect_red_flags, apply_safety_override


@pytest.mark.parametrize("text", [
    "my father collapsed and is not responding",
    "I have chest pain and sweating",
    "snake bit my leg",
    "he drank pesticide",
    "I want to die",
    "she is pregnant and bleeding",
    "heavy bleeding after delivery",
    "baby is not feeding and very sleepy newborn not feeding",
    "he is not breathing",
    "child is choking",
    "I am thinking of suicide",
    "I feel like hurting myself tonight",
    "the baby is a newborn and not feeding, very sleepy",
    "my 2 year old drank kerosene",
    "we pulled him out of the well and he is not breathing properly",
    "he fell from a height and cannot feel his legs",
    "I am 8 months pregnant and the baby has stopped moving",
    "dog bite last month and now he is afraid of water and drooling",
    "we slept with the charcoal stove in the closed room and now we have a headache and are dizzy",
    "he drank illicit liquor and now has blurred vision",
    "she swallowed rat killer",
])
def test_red_flags_detected(text):
    assert detect_red_flags(text), text


@pytest.mark.parametrize("text", [
    "runny nose and sore throat",
    "no chest pain just a cold",
    "mild headache since morning",
    "twisted my ankle yesterday",
    "I am afraid of water because I cannot swim",
    "we cooked on the stove and the room is warm",
    "the baby is moving a lot and kicking well",
    "I cut my hand while cooking",
])
def test_benign_text_not_flagged(text):
    assert detect_red_flags(text) == []


def test_override_escalates_but_never_downgrades():
    low = {"acuity_label": "ROUTINE", "recommendation": "rest"}
    out = apply_safety_override(low, ["Seizure / fit"])
    assert out["acuity_label"] == "EMERGENCY" and out["pipeline_acuity_label"] == "ROUTINE"
    assert out["recommendation"].startswith("Possible emergency")
    already = apply_safety_override({"acuity_label": "EMERGENCY", "recommendation": "go"}, ["Seizure / fit"])
    assert already["acuity_label"] == "EMERGENCY"
    untouched = apply_safety_override({"acuity_label": "ROUTINE"}, [])
    assert untouched["acuity_label"] == "ROUTINE"
