# Knowledge base: contents, governance, and how to extend

## Status: DRAFT unless a named clinician has approved the entry
Every entry carries `"review_status": "DRAFT - requires licensed clinician review before any real-world use"`.
Content was authored to be conservative and to follow widely taught public-health first-aid and referral principles
(e.g. ORS for diarrhoea, avoiding NSAIDs in suspected dengue, no tourniquets/cutting for snakebite, wash animal-bite
wounds for 15 minutes and seek rabies prophylaxis). It was **not** copied from, nor verified against, a specific
guideline document in this build — a clinician must check each entry against current national guidelines
(e.g. NVBDCP/NTEP/IMNCI/MoHFW in India, WHO elsewhere) before real-world use.

**Deliberate safety choices:** no drug dosages anywhere (enforced by a test); medicines are mentioned only generically;
every entry lists `red_flags` that mean "escalate now".

## Coverage (159 conditions: 51 EMERGENCY, 56 URGENT, 52 ROUTINE)
* **Allergy and immunology**: food allergy reaction, medicine (drug) allergy with rash, severe drug reaction with skin blistering,
  insect sting reaction, allergic contact dermatitis, eczema, allergic conjunctivitis, angioedema, allergic rhinitis, hives,
  anaphylaxis.
* **Child health**: severe pneumonia, bronchiolitis, croup, whooping cough, diphtheria, mumps, hand-foot-and-mouth disease, measles,
  chickenpox, febrile seizure, newborn danger signs, newborn jaundice, severe malnutrition, nappy rash, oral thrush, dehydration,
  foreign object in nose/ear, swallowed foreign object.
* **Infectious and tropical**: malaria, dengue, chikungunya, typhoid, tuberculosis, leptospirosis, scrub typhus, kala-azar,
  filariasis, leprosy, dysentery, hepatitis, shingles, brain infection (encephalitis), tetanus, suspected rabies, animal bites,
  COVID-like illness.
* **Pregnancy and women's health**: eclampsia, pregnancy bleeding, reduced baby movement, premature labour, postpartum bleeding and
  infection, mastitis, severe vomiting in pregnancy, vaginal infections, pelvic infection, painful or heavy periods.
* **Poisoning, injury and environment**: snakebite, scorpion sting, pesticide, kerosene, carbon monoxide, illicit liquor, plant and
  mushroom poisoning, unknown poison or overdose, burns, heat illness, near-drowning, electric shock, spinal injury, fractures,
  dislocation, chest injury, bleeding, head injury, minor wounds, sunburn.
* **Heart, lungs, abdomen, kidney**: heart attack, angina, palpitations, heart failure, stroke, pulmonary embolism, pneumothorax,
  asthma, COPD, pneumonia, appendicitis, obstruction, pancreatitis, GI bleeding, hernia, gallstones, kidney stones and infection,
  urinary retention, testicular torsion and inflammation.
* **Chronic, mental health, eye, ear, mouth, skin**: diabetes and its emergencies, hypertension, thyroid, anaemia, arthritis, gout,
  septic arthritis, back pain, sciatica, vertigo, facial palsy, depression, anxiety, alcohol withdrawal, self-harm crisis, glaucoma,
  eye infection and injury, stye, ear infection, dental abscess, mouth ulcers, gum disease, scabies, ringworm, impetigo, head lice,
  abscess, heat rash and more.

This is a broad list of **common** conditions, not "all diseases". Anything outside it should produce the "cannot assess" outcome.

## Clinical review status
Every entry starts as `DRAFT`. A clinician reviews entries with `python -m backend.rag.review export/import`
(see `docs/CLINICIAN_REVIEW_GUIDE.md`); an approval stores `reviewed_by`, `reviewed_on` and comments, appears on every result,
and is logged in `backend/rag/review_log.jsonl`. After any edit to an entry's clinical text, reset it to draft with
`review.reset_to_draft([...ids])` so it is reviewed again.

## Files
* `backend/rag/knowledge_base.json` — conditions (`id, condition, description, keywords, acuity(1/3/5), acuity_label,
  source, recommendation, caution, red_flags, self_care, review_status`)
* `backend/rag/symptom_lexicon.json` — `questions` (natural yes/no wording) and `synonyms` (everyday/rural phrasings)
* `backend/db/migrations/` — Postgres tables; `python -m backend.rag.ingest` loads/updates them (idempotent)

## Adding or editing a condition (no code changes)
1. Add an entry to `knowledge_base.json` (3+ keywords; reuse existing keyword strings where the symptom is the same).
2. For any *new* keyword, add a question to `symptom_lexicon.json` → `questions` and phrasings to `synonyms`.
3. `python -m pytest -q` (the tests enforce schema, acuity scale, no dosages, lexicon coverage).
4. `python -m backend.rag.ingest` (or restart the server — it auto-ingests) to refresh pgvector embeddings.
5. Add a case to `eval/cases.json`, re-run `python -m eval.evaluate_full`; check under-triage stays 0.

## Clinician review checklist (per entry)
Acuity correct? · Red flags complete? · Recommendation safe and locally appropriate? · Caution complete? · Symptoms typical?
· Any dangerous omission? Record reviewer and date, then change `review_status`.

## Source checking (separate from clinical review)
See `docs/SOURCES.md`. 9 entries have been compared with WHO / CDC / NHS-type sources and carry `references`; the rest are still to do.
Source-checked is not clinician-reviewed: only `review_status: APPROVED` with a named reviewer means a clinician reviewed the entry.
