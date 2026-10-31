"""
ablation.py — Component ablations for the paper (offline deterministic mode, no LLM).

Part 1  Retrieval ablation   : TF-IDF vs symptom-overlap vs hybrid vs hybrid+pgvector
                               (top-1 / top-3 / recall@6 / MRR on dev and holdout sets)
Part 2  End-to-end ablation  : full system vs. removing one component at a time
                               (retrieval prior, worst-case escalation, safety layer,
                                Bayesian questioning => "tree-only" prototype-style baseline)

Run:  python -m eval.ablation            (all parts; slow)
      python -m eval.ablation retrieval | e2e <0-4> | combine   (step by step)
      add DATABASE_URL=... to include pgvector variants
"""
import json
import os
import sys

os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:1")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")   # evaluation drives thousands of requests; limiter off
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sklearn.tree import _tree  # noqa: E402

from backend import config, database, safety  # noqa: E402
from backend.agents import retrieval_agent  # noqa: E402
from backend.rag import decision_tree as dtm  # noqa: E402
from backend.rag.retriever import (HybridRetriever, PgVectorRetriever,  # noqa: E402
                                   SymptomOverlapRetriever, TfidfRetriever)
import eval.evaluate_full as ef  # noqa: E402

HERE = os.path.dirname(__file__)
SETS = {"dev": "cases.json", "holdout": "cases_holdout.json"}
KB = ef.KB


def load(name):
    return json.load(open(os.path.join(HERE, SETS[name]), encoding="utf-8"))


# ------------------------------------------------------------- Part 1 ------
def retrieval_table():
    tf, ov = TfidfRetriever(), SymptomOverlapRetriever()
    variants = {
        "TF-IDF only": tf,
        "Symptom-overlap only": ov,
        "Hybrid (overlap+TF-IDF)": HybridRetriever([ov, tf], tf.kb),
    }
    if database.pg_available():
        try:
            pg = PgVectorRetriever()
            # label shows the embedder actually in use (hashing offline, or nomic-embed-text with Ollama)
            variants[f"{pg.backend_name} only"] = pg
            variants[f"Hybrid + {pg.backend_name}"] = HybridRetriever([ov, tf, pg], tf.kb)
        except Exception as e:
            print("pgvector variants skipped:", e)
    rows = []
    for vname, r in variants.items():
        row = {"variant": vname}
        for sname in SETS:
            cases = load(sname)
            n = top1 = top3 = rec6 = 0
            rr = 0.0
            for frag, text in cases.items():
                e = ef._entry_for(frag)
                ids = [m["id"] for m in r.retrieve(text, top_k=6)]
                n += 1
                top1 += ids[:1] == [e["id"]]
                top3 += e["id"] in ids[:3]
                rec6 += e["id"] in ids
                rr += 1.0 / (ids.index(e["id"]) + 1) if e["id"] in ids else 0.0
            row[sname] = dict(n=n, top1=top1, top3=top3, rec6=rec6, mrr=round(rr / n, 3))
        rows.append(row)
    return rows


# ------------------------------------------------------------- Part 2 ------
def _tree_only_next_question(self, known):
    if self.clf is None:
        return None
    t, node = self.clf.tree_, 0
    while t.feature[node] != _tree.TREE_UNDEFINED:
        sym = self.symptoms[t.feature[node]]
        if sym not in known:
            return sym, dtm.QUESTION_OVERRIDES.get(sym, f"Do you have {sym}?")
        node = t.children_left[node] if known[sym] <= t.threshold[node] else t.children_right[node]
    return None


def _tree_only_blended(self, known):
    if self.clf is None:
        return {c["id"]: 1.0 / len(self.candidates) for c in self.candidates}
    row = [known.get(s, 0) for s in self.symptoms]
    return {cid: float(p) for cid, p in zip(self.clf.classes_, self.clf.predict_proba([row])[0])}


class Patch:
    """Context manager that temporarily patches attributes."""
    def __init__(self, *triples): self.t = triples
    def __enter__(self):
        self.old = [(o, n, getattr(o, n)) for o, n, _ in self.t]
        for o, n, v in self.t: setattr(o, n, v)
    def __exit__(self, *a):
        for o, n, v in self.old: setattr(o, n, v)


def e2e(label, patches=()):
    out = {"label": label}
    with Patch(*patches):
        for sname in SETS:
            ef.CASES = load(sname)
            s, _ = ef.run(verbose=False)
            out[sname] = s
    return out


def e2e_configs():
    CT = dtm.CandidateTree
    orig_candidate_tree = dtm.DecisionTreeTriage.candidate_tree

    def no_prior(self, ids, random_state=42, priors=None, prefilled=None):
        return orig_candidate_tree(self, ids, random_state, None, prefilled)

    return [
        ("Full system", []),
        ("- retrieval prior (uniform prior)", [(dtm.DecisionTreeTriage, "candidate_tree", no_prior)]),
        ("- worst-case escalation", [(CT, "ALT_ABS", 99.0)]),
        ("- red-flag safety layer", [(safety, "detect_red_flags", lambda t: [])]),
        ("- Bayesian questioning (tree-only)", [
            (CT, "next_question", _tree_only_next_question),
            (CT, "blended", _tree_only_blended),
            (CT, "ALT_ABS", 99.0)]),
    ]


def pct(a, b):
    return f"{100 * a / b:.1f}"


def part_retrieval():
    rt = retrieval_table()
    json.dump(rt, open(os.path.join(HERE, "_abl_retrieval.json"), "w"), indent=1)
    for r in rt:
        d, h = r["dev"], r["holdout"]
        print(f"{r['variant']:<36} dev top1 {pct(d['top1'], d['n']):>5} top3 {pct(d['top3'], d['n']):>5} "
              f"R@6 {pct(d['rec6'], d['n']):>5} MRR {d['mrr']:.3f} | holdout top1 {pct(h['top1'], h['n']):>5} "
              f"top3 {pct(h['top3'], h['n']):>5} R@6 {pct(h['rec6'], h['n']):>5} MRR {h['mrr']:.3f}")


def part_e2e(idx):
    label, patches = e2e_configs()[idx]
    r = e2e(label, patches)
    json.dump(r, open(os.path.join(HERE, f"_abl_e2e_{idx}.json"), "w"), indent=1)
    for sname in SETS:
        s = r[sname]; n = s["n"]
        print(f"{label:<38} {sname:<8} cond {pct(s['cond'], n):>5}  acuity {pct(s['acu'], n):>5}  "
              f"under {s['under']:>2}  over {s['over']:>2}  q/case {s['qs'] / n:.1f}")


def combine():
    rt = json.load(open(os.path.join(HERE, "_abl_retrieval.json")))
    et = [json.load(open(os.path.join(HERE, f"_abl_e2e_{i}.json"))) for i in range(len(e2e_configs()))]
    import glob
    for extra in sorted(glob.glob(os.path.join(HERE, "_abl_e2e_pg*.json"))):  # optional runs made with DATABASE_URL set
        et.append(json.load(open(extra)))
        os.remove(extra)
    json.dump({"retrieval": rt, "e2e": et}, open(os.path.join(HERE, "ablation_results.json"), "w"), indent=1)
    for i in range(len(e2e_configs())):
        os.remove(os.path.join(HERE, f"_abl_e2e_{i}.json"))
    os.remove(os.path.join(HERE, "_abl_retrieval.json"))
    print("saved eval/ablation_results.json")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "retrieval":
        part_retrieval()
    elif args and args[0] == "e2e":
        part_e2e(int(args[1]))
    elif args and args[0] == "combine":
        combine()
    else:
        part_retrieval()
        for i in range(len(e2e_configs())):
            part_e2e(i)
        combine()
