# Guide for the reviewing clinician

Thank you for helping. This system gives rural users urgency advice (EMERGENCY / URGENT / ROUTINE) and first-aid style
guidance for **159 conditions**. None of it should be described as clinically approved until a clinician has reviewed
each entry. This sheet records exactly what you review - nothing is marked approved by default.

## What you receive
A spreadsheet (`review_sheet.csv`, opens in Excel or Google Sheets) with one row per condition, **highest risk first**
(emergencies, then urgent, then routine).

| Column | What it contains |
|---|---|
| condition, urgency | the condition and the urgency level the tool assigns |
| typical_symptoms | the symptoms the tool uses to recognise it |
| description, recommendation, caution | what the user is told |
| warning_signs_to_escalate | signs that mean "go to emergency care now" |
| self_care | home measures mentioned |

## What to check, per row
1. **Urgency level** - would you be comfortable with this level for a patient presenting this way in a village with no doctor nearby? When unsure, the safer (more urgent) level is preferred.
2. **Recommendation and caution** - is the advice correct and safe for a layperson? Is anything dangerous, misleading or missing (for example a first-aid step that could cause harm)?
3. **Warning signs** - are the escalation triggers complete?
4. **Typical symptoms** - are they representative? Any common presentation missing?
5. **Local fit** - drugs, programmes and referral advice appropriate for your region (the tool deliberately gives **no drug doses**).
6. **Missing conditions** - note common local conditions that are absent (write them in the comments of any row, or send separately).

## How to record your decision (last four columns)
| Column | Fill in |
|---|---|
| decision | `APPROVED` or `CHANGES_REQUESTED` (leave blank for rows you have not reviewed) |
| reviewer_name | your name (add registration number if you wish) |
| review_date | YYYY-MM-DD (defaults to the import date) |
| comments | **required** if CHANGES_REQUESTED - say exactly what to change |

Return the file to the developers. They run `python -m backend.rag.review import review_sheet.csv`. Your name and date are
then stored with each entry, shown to users on the result screen ("Reviewed and approved by ..."), and logged in
`backend/rag/review_log.jsonl`.

## Important
* You can review a part now and the rest later - only rows with a decision are recorded.
* The import never changes the medical text. If you request changes, a developer edits the entry and it goes back to
  DRAFT for you to approve again. Please do not approve an entry that you would want edited.
* Approval means "I reviewed this entry and consider it reasonable as advice for lay users in a supervised setting". It is
  your professional judgement; please review only what you are comfortable vouching for.
* The tool is an aid for lay users and health workers. It does not replace clinical assessment, and the developers
  will say so wherever it is described.
