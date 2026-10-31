"""
evaluate.py — Owner: Sai (Evaluation, Documentation & Paper)

Runs the full pipeline against a labeled test set (one representative
symptom description per knowledge base condition) and reports accuracy
against the known ground-truth acuity label. This is the evaluation
harness referenced in the project report and, later, the paper.

Run:
    python3 -m eval.evaluate
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.orchestrator import run_pipeline_sync

TEST_CASES = [
    {"text": "Sudden chest pain radiating to my left arm, sweating and dizzy",
     "expected_condition": "Suspected Myocardial Infarction (Heart Attack)", "expected_acuity": "EMERGENCY"},
    {"text": "My throat is swelling up and I'm having trouble breathing after eating peanuts, I have hives",
     "expected_condition": "Anaphylaxis (Severe Allergic Reaction)", "expected_acuity": "EMERGENCY"},
    {"text": "Sharp pain that moved from my belly button to my lower right abdomen, fever and vomiting",
     "expected_condition": "Acute Appendicitis", "expected_acuity": "EMERGENCY"},
    {"text": "Wheezing badly, chest feels very tight, I can barely speak full sentences",
     "expected_condition": "Asthma Exacerbation", "expected_acuity": "EMERGENCY"},
    {"text": "Burning sensation when I urinate and going very frequently, cloudy urine",
     "expected_condition": "Urinary Tract Infection", "expected_acuity": "URGENT"},
    {"text": "Persistent cough with phlegm, fever, chills and chest pain when breathing",
     "expected_condition": "Bacterial Pneumonia", "expected_acuity": "URGENT"},
    {"text": "Severe throbbing headache with light sensitivity and vomiting",
     "expected_condition": "Migraine (Severe)", "expected_acuity": "URGENT"},
    {"text": "Diarrhea and vomiting for a day, can't keep fluids down, stomach cramps",
     "expected_condition": "Gastroenteritis with Dehydration Risk", "expected_acuity": "URGENT"},
    {"text": "Runny nose, sneezing and a mild sore throat for two days",
     "expected_condition": "Common Cold", "expected_acuity": "ROUTINE"},
    {"text": "Twisted my ankle playing football, some swelling but I can still walk",
     "expected_condition": "Mild Ankle Sprain", "expected_acuity": "ROUTINE"},
    {"text": "Sudden severe pain in my lower back and side that comes in waves, radiating to my groin, with blood in my urine",
     "expected_condition": "Kidney Stone (Renal Colic)", "expected_acuity": "URGENT"},
    {"text": "Hit my head playing sports, now I have a headache, feel confused and dizzy",
     "expected_condition": "Concussion (Mild Head Injury)", "expected_acuity": "URGENT"},
    {"text": "Started vomiting and had diarrhea a few hours after eating at a restaurant, with stomach cramps",
     "expected_condition": "Food Poisoning", "expected_acuity": "URGENT"},
    {"text": "My eye is red, itchy, and watery with some discharge, feels gritty",
     "expected_condition": "Conjunctivitis (Pink Eye)", "expected_acuity": "ROUTINE"},
    {"text": "Severe sore throat, painful to swallow, swollen tonsils and fever, swollen glands in my neck",
     "expected_condition": "Strep Throat", "expected_acuity": "URGENT"},
]


def run_evaluation():
    correct_condition = 0
    correct_acuity = 0
    rows = []

    for case in TEST_CASES:
        result = run_pipeline_sync(case["text"])
        cond_match = result["condition"] == case["expected_condition"]
        acuity_match = result["acuity_label"] == case["expected_acuity"]
        correct_condition += cond_match
        correct_acuity += acuity_match

        rows.append({
            "input": case["text"][:50] + "...",
            "expected": case["expected_condition"],
            "predicted": result["condition"],
            "condition_match": "✓" if cond_match else "✗",
            "expected_acuity": case["expected_acuity"],
            "predicted_acuity": result["acuity_label"],
            "acuity_match": "✓" if acuity_match else "✗",
            "confidence": result["confidence"],
        })

    n = len(TEST_CASES)
    print(f"{'INPUT':<52} {'EXPECTED CONDITION':<38} {'MATCH':<6} {'ACUITY':<10} {'MATCH'}")
    print("-" * 120)
    for r in rows:
        print(f"{r['input']:<52} {r['expected']:<38} {r['condition_match']:<6} "
              f"{r['predicted_acuity']:<10} {r['acuity_match']}")

    print("\n" + "=" * 50)
    print(f"Condition-match accuracy: {correct_condition}/{n} = {correct_condition/n*100:.1f}%")
    print(f"Acuity-match accuracy:    {correct_acuity}/{n} = {correct_acuity/n*100:.1f}%")
    print("=" * 50)
    return rows


if __name__ == "__main__":
    run_evaluation()
