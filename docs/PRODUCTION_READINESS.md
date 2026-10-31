# Production readiness - honest status

**Verdict: ready for a supervised pilot at one clinic. NOT ready for unsupervised or public use.**
The engineering is in good shape; the blocking items are clinical and legal, and only people can do them.

## Engineering - done and tested
| Item | Evidence |
|---|---|
| Works offline end to end (Ollama, PostgreSQL + pgvector, or fallbacks) | 162 automated tests (151 offline + 11 PostgreSQL) (incl. real PostgreSQL), real-server run |
| Safety nets: emergency red flags, worst-case urgency, "cannot assess" | tests + evaluation: 0 unsafe under-triage on 240 cases |
| Open access for everyone, free self-registration, **private per-user history**, owner-only access, change password, erase my account | `tests/test_accounts.py` |
| Lockout, rate limiting, security headers, input limits (one kind of user, no staff tier) | `tests/test_hardening.py` |
| Audit log (no patient text), PHI-free logs | tests |
| Production guard (refuses unsafe config / silent DB fallback) | tests + real-process run |
| Versioned database migrations; in-place upgrade of an old database | tests + manual upgrade run |
| Retention purge, "save nothing" option, consent notice | tests |
| Backups with verification and pruning (SQLite and PostgreSQL) | tests incl. real `pg_dump` |
| Open access for everyone: no staff/admin web area; every account sees only its own history; upgrade from v6 turns old staff accounts into ordinary users | `tests/test_accounts.py`, migration `004_open_access` tested on a real PostgreSQL |
| Installable offline web app (manifest, service worker that never caches patient data), mobile viewport | tests |
| Honest AI reporting: result says whether the model or built-in rules wrote it; probabilities never shown as 0%/100%; "unlikely" instead of "ruled out" | tests |
| Release gate in CI | `eval/ci_gate.py` |

## Engineering - written but not yet tested by us
Docker image build, the HTTPS (Caddy) profile, the GitHub Actions workflow, behaviour on the clinic's real hardware and Wi-Fi, load with many simultaneous users, live Ollama model behaviour across many cases.

## Blocking items that need people (not code)
| # | Item | Why it blocks | Who |
|---|---|---|---|
| 1 | **Clinician review of the knowledge base** (159 entries, all DRAFT; 9 source-checked, none clinician-approved) | The advice itself is the main safety risk | Clinician(s) - `docs/CLINICIAN_REVIEW_GUIDE.md` |
| 2 | **Validation on real cases** (sensitivity for emergencies, under-triage rate, with confidence intervals) | Our tests are synthetic and author-written | Clinician + team, via the feedback form |
| 3 | **Regulatory and legal position** (medical-device rules, data-protection law, liability, licence/ownership with the college) | Health-advice software may be regulated | College / legal adviser |
| 4 | **Independent security review** (penetration test) | We have not had one | Security professional |
| 5 | **Usability testing with real users** (ASHA/health workers, low-literacy users, a range of phones) | We have not watched anyone use it | Team + clinic |
| 6 | **Local-language interface and questions** (Telugu/Hindi) with native-speaker and clinician review | English only; Hindi/Telugu word lists are unreviewed | Translators + clinician |
| 7 | **Operating procedures and training** (who backs up, who reviews feedback, what to do after an error) | Tools alone do not make it safe | Clinic lead |
| 8 | **Source-checking the remaining 150 entries** against WHO/ICMR/NHM/NLEM and local guidance | Only 9 checked so far | Team + clinician (`docs/SOURCES.md`) |

## Suggested path
1. Clinician reviews all EMERGENCY entries, then URGENT, then ROUTINE; developers apply requested changes.
2. Supervised pilot with one health worker checking every case; the health worker and the patient record feedback on each result.
3. After a few hundred cases: measure agreement and under-triage, fix what the data shows, re-run `eval.ci_gate`.
4. Only then consider wider use - with the regulatory/legal position settled.

## Go / no-go
* **Pilot go**: EMERGENCY entries reviewed, health workers trained, backup tested, HTTPS set up, consent notice visible.
* **Public no-go** until items 1-6 above are done.
