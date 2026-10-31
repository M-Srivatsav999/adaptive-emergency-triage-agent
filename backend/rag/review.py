"""
review.py - Clinician review workflow for the knowledge base.

WHY: nothing in this system may be called 'clinician-approved' unless a named
clinician has actually reviewed that specific entry. This tool makes that easy and auditable.

    python -m backend.rag.review export                    # -> review_sheet.csv (open in Excel/Sheets)
    python -m backend.rag.review export --only-unreviewed
    python -m backend.rag.review import review_sheet.csv   # records decisions with name + date
    python -m backend.rag.review status                    # how many entries are approved / pending

The clinician fills the last columns of each row he has reviewed:
    decision        APPROVED  or  CHANGES_REQUESTED
    reviewer_name   e.g. Dr. A. Kumar (+ registration number if you wish)
    review_date     YYYY-MM-DD (defaults to today)
    comments        required when CHANGES_REQUESTED (what is wrong / what to change)

Import NEVER edits clinical text. It only records the decision. Requested changes are made by a
developer, after which the entry returns to DRAFT and must be reviewed again.
Every decision is appended to backend/rag/review_log.jsonl (audit trail).
"""
import argparse
import csv
import datetime
import json
import os
import sys

HERE = os.path.dirname(__file__)
KB_PATH = os.path.join(HERE, "knowledge_base.json")
LOG_PATH = os.path.join(HERE, "review_log.jsonl")

DRAFT = "DRAFT - requires licensed clinician review before any real-world use"
APPROVED = "APPROVED"
CHANGES = "CHANGES_REQUESTED"
VALID_STATUSES = {APPROVED, CHANGES}

COLUMNS = ["id", "condition", "urgency", "typical_symptoms", "description", "recommendation", "caution",
           "warning_signs_to_escalate", "self_care", "current_status",
           "decision", "reviewer_name", "review_date", "comments"]


def _load(path=KB_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(kb, path=KB_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)


def is_draft(status: str) -> bool:
    return not status or status.upper().startswith("DRAFT")


def status_label(entry: dict) -> str:
    """Human-readable review status shown in results and reports."""
    st = entry.get("review_status", "")
    if st == APPROVED:
        who = entry.get("reviewed_by") or "a clinician"
        when = entry.get("reviewed_on")
        return f"Reviewed and approved by {who}" + (f" on {when}" if when else "")
    if st == CHANGES:
        return "A clinician requested changes to this entry - content under revision"
    return "Draft - this entry has not yet been reviewed by a clinician"


def export_sheet(out="review_sheet.csv", only_unreviewed=False, kb_path=KB_PATH):
    kb = sorted(_load(kb_path), key=lambda e: (e.get("acuity", 9), e["id"]))  # EMERGENCY first
    rows = 0
    with open(out, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel shows symbols correctly
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for e in kb:
            if only_unreviewed and not is_draft(e.get("review_status", "")):
                continue
            w.writerow({
                "id": e["id"], "condition": e["condition"], "urgency": e["acuity_label"],
                "typical_symptoms": "; ".join(e.get("keywords", [])),
                "description": e.get("description", ""), "recommendation": e.get("recommendation", ""),
                "caution": e.get("caution", ""), "warning_signs_to_escalate": "; ".join(e.get("red_flags", [])),
                "self_care": e.get("self_care", ""),
                "current_status": "DRAFT" if is_draft(e.get("review_status", "")) else e.get("review_status"),
                "decision": "", "reviewer_name": "", "review_date": "", "comments": "",
            })
            rows += 1
    return rows


def import_sheet(path, kb_path=KB_PATH, log_path=LOG_PATH, today=None):
    today = today or datetime.date.today().isoformat()
    kb = _load(kb_path)
    by_id = {e["id"]: e for e in kb}
    applied = {"APPROVED": 0, "CHANGES_REQUESTED": 0}
    errors = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            decision = (row.get("decision") or "").strip().upper().replace(" ", "_")
            if not decision:
                continue  # not reviewed yet
            cid = (row.get("id") or "").strip()
            if cid not in by_id:
                errors.append(f"row {n}: unknown id '{cid}'"); continue
            if decision not in VALID_STATUSES:
                errors.append(f"row {n} ({cid}): decision must be APPROVED or CHANGES_REQUESTED, got '{decision}'"); continue
            name = (row.get("reviewer_name") or "").strip()
            if not name:
                errors.append(f"row {n} ({cid}): reviewer_name is required"); continue
            comments = (row.get("comments") or "").strip()
            if decision == CHANGES and not comments:
                errors.append(f"row {n} ({cid}): comments are required when requesting changes"); continue
            date = (row.get("review_date") or "").strip() or today
            try:
                datetime.date.fromisoformat(date)
            except ValueError:
                errors.append(f"row {n} ({cid}): review_date must be YYYY-MM-DD, got '{date}'"); continue
            e = by_id[cid]
            old = e.get("review_status", "")
            e["review_status"] = decision
            e["reviewed_by"] = name
            e["reviewed_on"] = date
            e["reviewer_comments"] = comments
            applied[decision] += 1
            with open(log_path, "a", encoding="utf-8") as lg:
                lg.write(json.dumps({"at": datetime.datetime.now().isoformat(timespec="seconds"), "id": cid,
                                     "condition": e["condition"], "from": old, "to": decision,
                                     "reviewer": name, "review_date": date, "comments": comments},
                                    ensure_ascii=False) + "\n")
    if applied["APPROVED"] or applied["CHANGES_REQUESTED"]:
        _save(kb, kb_path)
    return applied, errors


def status(kb_path=KB_PATH):
    kb = _load(kb_path)
    n = len(kb)
    appr = sum(1 for e in kb if e.get("review_status") == APPROVED)
    chg = sum(1 for e in kb if e.get("review_status") == CHANGES)
    draft = n - appr - chg
    return {"total": n, "approved": appr, "changes_requested": chg, "draft": draft}


def reset_to_draft(entry_ids, kb_path=KB_PATH):
    """After a developer edits an entry, it must be reviewed again."""
    kb = _load(kb_path)
    for e in kb:
        if e["id"] in entry_ids:
            e["review_status"] = DRAFT
            for k in ("reviewed_by", "reviewed_on", "reviewer_comments"):
                e.pop(k, None)
    _save(kb, kb_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export"); e.add_argument("--out", default="review_sheet.csv"); e.add_argument("--only-unreviewed", action="store_true")
    i = sub.add_parser("import"); i.add_argument("file")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        print(f"Wrote {export_sheet(a.out, a.only_unreviewed)} rows to {a.out}")
    elif a.cmd == "import":
        applied, errors = import_sheet(a.file)
        print(f"Recorded: {applied['APPROVED']} approved, {applied['CHANGES_REQUESTED']} changes requested.")
        for err in errors:
            print("  PROBLEM:", err)
        print("Status:", status())
        if errors:
            sys.exit(1)
    else:
        print(status())


if __name__ == "__main__":
    main()
