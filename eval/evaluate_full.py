"""
evaluate_full.py — Full-scale evaluation over the whole knowledge base.

For EVERY condition there is one natural-language patient case (eval/cases.json,
written in everyday and rural phrasing, not copied from the keyword lists).
A simulated patient then answers the yes/no questions truthfully for the
true condition — but only reports ~75% of its symptoms (seeded), to mimic
incomplete information.

Reported:
  * Retrieval  : true condition in top-1 / top-3 / shortlist (recall@k)
  * Pipeline   : final condition accuracy, acuity accuracy, avg questions
  * SAFETY     : under-triage count (predicted LESS urgent than truth) vs over-triage

Run:   python -m eval.evaluate_full            (development set, 81 cases)
       python -m eval.evaluate_full --holdout  (40 fresh cases written AFTER the lexicon was frozen)
       python -m eval.evaluate_full --batch2   (15 cases for the allergy / extra-conditions module; development-style)
       python -m eval.evaluate_full --verbose
Honest caveat: cases were written by the same team that built the knowledge
base, so this measures internal consistency and robustness to paraphrase /
missing symptoms — NOT clinical validity. Use /feedback with real clinicians
for that.
"""

import json
import os
import random
import sys

os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:1")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")   # evaluation drives thousands of requests; limiter off  # force deterministic offline mode
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend import config  # noqa: E402
from backend.agents import retrieval_agent  # noqa: E402

HERE = os.path.dirname(__file__)
KB = json.load(open(os.path.join(HERE, "..", "backend", "rag", "knowledge_base.json"), encoding="utf-8"))
def _load_cases():
    def _f(n):
        return json.load(open(os.path.join(HERE, n), encoding="utf-8"))
    if "--holdout" in sys.argv:
        return _f("cases_holdout.json")
    if "--holdout2" in sys.argv:
        return _f("cases_holdout2.json")
    if "--new" in sys.argv:
        return _f("cases_new.json")
    if "--all" in sys.argv:
        return {**_f("cases.json"), **_f("cases_new.json")}
    return _f("cases.json")

CASES = _load_cases()
RANK = {"EMERGENCY": 0, "URGENT": 1, "ROUTINE": 2}


def _entry_for(fragment: str):
    hits = [e for e in KB if fragment.lower() in e["condition"].lower()]
    assert len(hits) == 1, f"case key '{fragment}' matches {len(hits)} conditions"
    return hits[0]


def run(verbose=False, recall=0.75, seed=7):
    rng = random.Random(seed)
    retr = retrieval_agent.get_retriever()
    stats = dict(n=0, top1=0, top3=0, short=0, cond=0, acu=0, under=0, over=0, qs=0, fb_n=0, low=0)
    failures = []
    with TestClient(app) as client:
        for frag, text in CASES.items():
            entry = _entry_for(frag)
            stats["n"] += 1
            ranked = [m["id"] for m in retr.retrieve(text, top_k=config.RAG_CANDIDATE_COUNT)]
            stats["top1"] += ranked[:1] == [entry["id"]]
            stats["top3"] += entry["id"] in ranked[:3]
            stats["short"] += entry["id"] in ranked

            truth = {k for k in entry["keywords"] if rng.random() < recall}
            r = client.post("/dt/start", json={"message": text}).json()
            n_q = 0
            while r["type"] == "question" and n_q < 25:
                r = client.post("/dt/answer", json={"session_id": r["session_id"], "symptom": r["symptom"],
                                                    "answer": r["symptom"] in truth}).json()
                n_q += 1
            final = r["pipeline"][-1]["result"]
            if final.get("low_confidence"):
                stats["low"] += 1
            ok_c = final["condition"] == entry["condition"]
            pa, ta = final["acuity_label"], entry["acuity_label"]
            ok_a = pa == ta
            stats["cond"] += ok_c
            stats["acu"] += ok_a
            stats["qs"] += n_q
            if RANK[pa] > RANK[ta]:
                stats["under"] += 1
            elif RANK[pa] < RANK[ta]:
                stats["over"] += 1
            if not ok_c or RANK[pa] > RANK[ta]:
                failures.append((frag, final["condition"], ta, pa, in_short(entry, ranked)))
            if verbose:
                print(f"{'OK ' if ok_c else 'BAD'} {frag:<30} -> {final['condition'][:40]:<40} {ta:>9}/{pa:<9} q={n_q}")
    return stats, failures


def in_short(entry, ranked):
    return "in shortlist" if entry["id"] in ranked else "MISSED by retrieval"


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv
    s, fails = run(verbose)
    n = s["n"]
    pct = lambda x: f"{x}/{n} = {100 * x / n:.1f}%"
    print("=" * 64)
    print(f"Knowledge base size : {len(KB)} conditions   cases: {n}")
    print(f"Retrieval top-1     : {pct(s['top1'])}")
    print(f"Retrieval top-3     : {pct(s['top3'])}")
    print(f"Retrieval shortlist : {pct(s['short'])}   (top-{config.RAG_CANDIDATE_COUNT}; Triage can only pick from this)")
    print(f"Final condition     : {pct(s['cond'])}")
    print(f"Final acuity        : {pct(s['acu'])}")
    print(f"Over-triage (safe)  : {s['over']}     UNDER-triage (unsafe): {s['under']}")
    print(f"Avg questions asked : {s['qs'] / n:.1f}")
    print(f"Low-confidence ('cannot assess') outcomes: {s['low']}")
    print("=" * 64)
    if fails:
        print("Failures / unsafe cases:")
        for f in fails:
            print("  ", f)
