"""
evaluate_decision_tree.py — Owner: Sai (Evaluation)

Evaluates the decision-tree component in isolation (not the full pipeline):
for each knowledge-base condition, simulates answering the tree's
questions honestly based on that condition's own keyword profile, and
checks whether the tree converges on the correct condition, and in how
many questions.

This is the number to cite specifically for "our classical ML baseline /
component" in the report, separate from the full pipeline's end-to-end
accuracy reported in evaluate.py.

Run:
    python3 -m eval.evaluate_decision_tree
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.rag.decision_tree import DecisionTreeTriage, MAX_QUESTIONS
import json


def run_evaluation():
    dt = DecisionTreeTriage()
    kb = json.load(open(os.path.join(os.path.dirname(__file__), "..", "backend", "rag", "knowledge_base.json")))

    correct = 0
    total_questions = 0

    print(f"{'CONDITION':<45} {'PREDICTED':<45} {'MATCH':<6} {'QUESTIONS'}")
    print("-" * 110)

    for entry in kb:
        own = set(entry["keywords"])
        known = {}
        n_q = 0
        for _ in range(MAX_QUESTIONS):
            q = dt.next_question(known)
            if q is None:
                break
            symptom, _ = q
            known[symptom] = 1 if symptom in own else 0
            n_q += 1

        result = dt.predict(known)
        predicted = result["entry"]["condition"]
        match = predicted == entry["condition"]
        correct += match
        total_questions += n_q

        print(f"{entry['condition']:<45} {predicted:<45} {'✓' if match else '✗':<6} {n_q}")

    n = len(kb)
    print("\n" + "=" * 50)
    print(f"Decision tree classification accuracy: {correct}/{n} = {correct/n*100:.1f}%")
    print(f"Average questions to converge: {total_questions/n:.1f}")
    print("=" * 50)


if __name__ == "__main__":
    run_evaluation()
