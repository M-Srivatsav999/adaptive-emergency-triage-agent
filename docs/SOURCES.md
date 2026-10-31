# Data sources: what we use, how, and what is still to do

## Principle
We use authoritative sources to **check** and **cite** our advice, and write the advice **in our own words**.
We do not paste in third-party text. That keeps the knowledge base free to share (MIT / CC BY 4.0) and avoids
licence conflicts - for example WHO documents are usually CC BY-NC-SA 3.0 IGO, whose share-alike and non-commercial
terms would not match our licences if text were copied.

Every entry has `review_status` (clinician review) and, where we have checked it, `source_check` + `references`:

| Field | Meaning |
|---|---|
| `source_check` | **SOURCE-CHECKED (by the development team, not a clinician)** - we compared specific points with the cited sources. This is *not* clinical review. |
| `references` | Titles and links of the sources checked (shown on the result screen and in the PDF) |
| `review_status` | DRAFT / APPROVED / CHANGES_REQUESTED - only a named clinician can set APPROVED |

## Source-checked so far (checked on 2026-10-15)
| Entry | Sources | Points confirmed | Change made |
|---|---|---|---|
| Snakebite | WHO snakebite pages | immobilise limb; no tight tourniquet; avoid traditional remedies; remove rings; antivenom | none needed |
| Animal bite (rabies risk) | WHO 2018 rabies recommendations; India NRCP wound guidance | wash ~15 min with soap and water; antiseptic; vaccine promptly; do not suture tightly early | added "do not stitch tightly before rabies treatment" |
| Dengue | WHO Western Pacific dengue page; CDC dengue sheet | paracetamol; avoid aspirin/NSAIDs; warning signs days 3-7 | added "rapid breathing", "restlessness" to warning signs |
| Gastroenteritis, severe dehydration, dysentery | WHO/UNICEF joint statement on acute diarrhoea | ORS + zinc 10-14 days (children); keep feeding; no anti-diarrhoeal drugs | added the zinc line (no dose) |
| Heart attack | St John Ambulance (clinically reviewed first-aid advice) | call emergency first; one aspirin chewed slowly if not allergic; not for under-16s | rewrote aspirin wording with exclusions |
| Severe burn, minor burn | NHS burns and scalds | cool running water 20 min; no ice/creams/butter; cover loosely; who needs medical care | broadened the "get medical care" criteria |

## Still to check (not yet source-checked - treat as DRAFT)
All other entries (150 of 159), with priority on: malaria, eclampsia/pre-eclampsia, postpartum haemorrhage, newborn danger
signs, child pneumonia/IMCI danger signs, stroke, seizure and febrile seizure, heat stroke, pesticide/organophosphate,
choking, scorpion sting, tetanus, TB, kala-azar, leprosy, hypoglycaemia. Method: pick the entry, read the cited guidance,
list the points confirmed or corrected in `source_check`, add `references`, add a test in `tests/test_sources.py`.

## Licence handling for the sources you listed
| Source | How to use it | Do not |
|---|---|---|
| MedlinePlus (NLM) | Reference and cross-check; mostly US-government public domain, but some pages contain third-party content - check each | Bulk-copy pages without checking each page's notice |
| openFDA / DailyMed | Reference for drug warnings only if drug content is ever added | Add doses (we deliberately give none) |
| WHO IRIS, ETAT, IMCI/IMAI, mhGAP | Reference and cite; model our own documented rules on the *principles* (danger signs, triage categories) | Copy text or tables (CC BY-NC-SA 3.0 IGO conflicts with our licences) |
| India: NHM/MoHFW, ASHA modules, ICMR Standard Treatment Workflows, NLEM, IDSP, data.gov.in (GODL-India) | **Highest priority.** Align advice with what ASHA workers and PHCs actually do and stock; use NLEM to keep any medicine mention to listed drugs; use IDSP to prioritise regional diseases | Rely on scanned PDFs without careful OCR and a human check |
| Where There Is No Doctor (Hesperian) | Reference only; licence differs by title/edition | Copy text before checking the exact licence |
| MedQuAD (NIH) | Possible extra evaluation questions (check licence) | Treat as ground truth |
| Kaggle disease-symptom sets | Baseline only, and say in the paper that they are partly synthetic | Train or tune the shipped system on them |
| DDInter (CC BY-NC-SA), DrugBank (academic licence) | Research reading only | Redistribute or embed |
| Manchester Triage, ESI | Cited as background only; we do not copy their rules | Copy their algorithms or tables |
| SNOMED CT, ICD-11 | Not used | Embed codes in what we ship |

## What we create ourselves (ours to license)
* **Red-flag emergency set**: 24 rule groups (158+ phrases) incl. Hindi/Telugu emergency phrases - needs clinician and native-speaker review.
* **Colloquial map**: ~2,500 everyday phrasings (e.g. "body heat", "loose motions") plus common Hindi and Telugu symptom words
  in Roman and native script for ~40 symptoms. **Needs native-speaker review.** Known limitation: negation in Hindi/Telugu
  ("bukhar nahi hai") is not parsed, so such a sentence can be read as the symptom being present (the cautious direction).
  Questions and results are still shown in English.
* **Translations** of the interface and questions are not done; they need native speakers and a clinician.

## Next steps that need a human with internet access to those sites
1. Download the relevant ICMR Standard Treatment Workflows and NHM/ASHA modules; check licences; OCR if scanned.
2. Work through the "still to check" list above with the clinician, citing the exact guidance used.
3. Compare our medicine mentions against the current NLEM.
