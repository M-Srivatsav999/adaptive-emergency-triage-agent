"""
ci_gate.py - release gate. Fails (exit 1) if any evaluation set shows an UNSAFE under-triage
or falls below its minimum accuracy. Run in CI and before every release:

    python -m eval.ci_gate                 # all four sets (several minutes)
    python -m eval.ci_gate --sets holdout2
"""
import json
import os
import sys

os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:1")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import eval.evaluate_full as ef  # noqa: E402

HERE = os.path.dirname(__file__)
# set name -> (file, minimum final-condition accuracy). Under-triage must be 0 everywhere.
GATES = {
    "dev": ("cases.json", 0.95),
    "new": ("cases_new.json", 0.95),
    "holdout": ("cases_holdout.json", 0.90),
    "holdout2": ("cases_holdout2.json", 0.90),
}


def main():
    wanted = sys.argv[sys.argv.index("--sets") + 1].split(",") if "--sets" in sys.argv else list(GATES)
    failed = []
    for name in wanted:
        fname, min_acc = GATES[name]
        ef.CASES = json.load(open(os.path.join(HERE, fname), encoding="utf-8"))
        s, _ = ef.run(verbose=False)
        n = s["n"]
        acc = s["cond"] / n
        status = "OK " if (s["under"] == 0 and acc >= min_acc) else "FAIL"
        print(f"{status} {name:<9} cases={n:<3} condition={acc:.1%} (min {min_acc:.0%}) under-triage={s['under']} over-triage={s['over']}")
        if status == "FAIL":
            failed.append(name)
    if failed:
        sys.exit(f"Release gate FAILED for: {', '.join(failed)}")
    print("Release gate passed: 0 unsafe under-triage and accuracy above thresholds.")


if __name__ == "__main__":
    main()
