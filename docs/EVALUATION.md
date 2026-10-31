# Evaluation methodology & results

## Current results (159-condition knowledge base, offline mode)
| Set | Cases | In shortlist | Final condition | Urgency | Under-triage | Over-triage | Questions |
|---|---|---|---|---|---|---|---|
| Development - original conditions | 81 | 100% | 100% | 93.8% | 0 | 5 | 2.5 |
| Development - new conditions | 78 | 100% | 100% | 93.6% | 0 | 5 | 3.7 |
| **Holdout - original conditions** | 40 | 97.5% | 95.0% | 87.5% | 0 | 5 | 3.1 |
| **Holdout - new conditions** (written after the vocabulary was frozen; run once) | 41 | 100% | 97.6% | 87.8% | 0 | 5 | 3.9 |

"Cannot assess" outcomes on these sets: 0. Legacy 15-case set: 15/15 conditions, 12/15 urgency.
The holdout misses were look-alike pairs (chickenpox vs shingles, fracture vs dislocation, dysentery vs food poisoning), all on the
cautious side. The development rows were used to tune the vocabulary and are optimistic; the holdout rows are the honest ones.
Adding 78 conditions lowered holdout condition accuracy on the original conditions from 100% to 95%.

### Bugs found by testing during the expansion (and fixed)
* A single, rarely-listed but generic word ("swelling") briefly counted as a distinctive symptom - fixed with a generic-symptom stoplist.
* Free-text intake reports a placeholder instead of real symptoms, and TF-IDF similarity is high even for junk, so the "cannot assess"
  rule uses the count of symptoms actually recognised instead.
* "Pain and swelling in one testicle" was unrecognised, so a testicular torsion case drifted to a fracture (unsafe) - vocabulary fixed.
* A joint-infection case in a child was under-triaged until the everyday phrasings "hot, red, swollen knee" were added.

## Earlier results (81-condition version, used in the paper draft)

## Harnesses
| Command | What it measures |
|---|---|
| `python -m eval.evaluate` | Original 15-case regression (free-text pipeline) |
| `python -m eval.evaluate_full` | 81 development cases — one per KB condition; retrieval recall@k, final condition/acuity, under/over-triage, questions asked |
| `python -m eval.evaluate_full --holdout` | 40 fresh cases written **after** the lexicon was frozen |
| `python -m eval.evaluate_decision_tree` | A single global tree over all 81 classes (the reason scoping by retrieval exists) |

All run offline (deterministic fallback), no LLM. A simulated patient answers yes/no questions truthfully for the
true condition but reports only ~75% of its symptoms (seeded) to mimic incomplete information.

## Results
Dev (81): shortlist recall 100%, top-1 98.8%, condition 98.8%, acuity 92.6%, **under-triage 0**, over-triage 6.
Holdout (40): shortlist 100%, top-1 97.5%, condition 100%, acuity 90.0%, **under-triage 0**, over-triage 4.
Single global tree alone (no retrieval scoping): ~91% with ~10 questions — retrieval scoping is what makes 81 classes tractable.

## What changed during development (and why it matters)
1. A first run showed **3 unsafe under-triages** (e.g. meningitis and pesticide poisoning labelled URGENT). Fixes:
   Bayesian posterior seeded by retrieval; information-gain questioning; confidence gate; **worst-case-aware urgency**
   (urgency is raised to match any plausible more-urgent alternative). Under-triage fell to 0.
2. Substring matching produced phantom symptoms ("cut" inside "acute", "fever" inside "evening fever"); extraction is now
   whole-word, negation-aware ("no fever") and most-specific-match-wins.
3. The overlap retriever outvoted better signals when it had one recognised symptom → it now abstains below 2.

## Threats to validity — please cite honestly
* Authors wrote both knowledge base and test cases (shared vocabulary → optimistic).
* The dev set influenced the lexicon (holdout exists for this reason; once the holdout has been used to tune anything,
  it is no longer a holdout — write a new one).
* Textbook-style cases; no real patient notes; no multi-morbidity; no non-English input.
* The synthetic "patient" is cooperative and consistent.
* Over-triage rate (≈10%) is deliberate: the system prefers false alarms to missed emergencies.
**Next step for a publishable result:** collect clinician-adjudicated cases via `/feedback` and report agreement,
sensitivity for EMERGENCY, and under-triage rate with confidence intervals.


## Ablations (python -m eval.ablation; results in eval/ablation_results.json)
| Configuration | Dev cond / under / over | Holdout cond / under / over |
|---|---|---|
| Full system | 98.8 / 0 / 6 | 100 / 0 / 4 |
| - retrieval prior | 98.8 / 0 / 6 (2.6 q vs 2.0) | 100 / 0 / 3 (3.1 q vs 2.5) |
| - worst-case escalation | 98.8 / 0 / 0 | 100 / 0 / 1 |
| - red-flag layer | 98.8 / 0 / 6 | 100 / 0 / 3 |
| - Bayesian posterior (tree only) | 80.2 / 5 / 4 | 82.5 / 2 / 3 |
| Full + pgvector(hashing) in hybrid | 98.8 / 1 / 7 | 92.5 / 0 / 3 |
| ... without escalation | 98.8 / 1 / 0 | 92.5 / 2 / 1 |

Retrieval: hybrid(overlap+TF-IDF) is best offline; pgvector with the HASHING embedder alone is weak (holdout top-1 67.5%) and
LOWERS fused accuracy (97.5% -> 82.5%). The effect of semantic `nomic-embed-text` embeddings is NOT measured in the build
environment: run `python -m eval.ablation retrieval` with DATABASE_URL set and Ollama running to measure it on your machine.

## Red-flag layer (python -m eval.evaluate_redflags)
30 emergency + 30 ordinary phrases: first version flagged 27/30 (misses: two self-harm phrasings, one newborn sign); fixed -> 30/30
(NOT independent, same phrases exposed the gap); 0/30 false positives on ordinary phrases; 4/4 false positives on deliberate
"hard negatives" that mention an emergency topic without an emergency (known limitation of phrase matching).
