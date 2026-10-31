"""
evaluate_redflags.py — Sensitivity / false-positive check of the deterministic
red-flag layer (backend/safety.py) on a small hand-written phrase set.

   30 positive phrases (should fire)   30 negative phrases (should not fire)
   4 'hard negatives' that mention an emergency topic without an emergency
   -> these are EXPECTED to false-fire: the layer is rule-based and deliberately
      over-cautious; they document a known limitation.
Run:  python -m eval.evaluate_redflags      Caveat: author-written phrases.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.safety import detect_red_flags  # noqa: E402

D = json.load(open(os.path.join(os.path.dirname(__file__), "redflag_cases.json"), encoding="utf-8"))


def main(verbose=False):
    pos_hit = [t for t in D["positive"] if detect_red_flags(t)]
    pos_miss = [t for t in D["positive"] if not detect_red_flags(t)]
    neg_fp = [t for t in D["negative"] if detect_red_flags(t)]
    hard_fp = [t for t in D["hard_negative_known_limitations"] if detect_red_flags(t)]
    print(f"Sensitivity (positives flagged): {len(pos_hit)}/{len(D['positive'])} = {100 * len(pos_hit) / len(D['positive']):.1f}%")
    print(f"False positives on ordinary negatives: {len(neg_fp)}/{len(D['negative'])}")
    print(f"False positives on hard negatives (known limitation): {len(hard_fp)}/{len(D['hard_negative_known_limitations'])}")
    for t in pos_miss: print("  MISSED:", t)
    for t in neg_fp: print("  FALSE+:", t)
    return dict(pos=len(D["positive"]), hit=len(pos_hit), neg=len(D["negative"]), fp=len(neg_fp),
                hard=len(D["hard_negative_known_limitations"]), hard_fp=len(hard_fp))


if __name__ == "__main__":
    main()
