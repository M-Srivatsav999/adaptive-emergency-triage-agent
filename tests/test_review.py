import csv
import json

from backend.rag import review


def _kb(tmp_path):
    kb = [
        {"id": "a1", "condition": "Cond A", "acuity_label": "URGENT", "keywords": ["x", "y", "z"], "description": "d",
         "recommendation": "r", "caution": "c", "red_flags": ["rf"], "self_care": "", "review_status": review.DRAFT},
        {"id": "a2", "condition": "Cond B", "acuity_label": "ROUTINE", "keywords": ["p", "q", "r"], "description": "d2",
         "recommendation": "r2", "caution": "c2", "red_flags": ["rf2"], "self_care": "", "review_status": review.DRAFT},
    ]
    path = tmp_path / "kb.json"
    path.write_text(json.dumps(kb), encoding="utf-8")
    return str(path)


def test_export_has_one_row_per_condition_and_blank_decisions(tmp_path):
    kb = _kb(tmp_path)
    out = tmp_path / "sheet.csv"
    assert review.export_sheet(str(out), kb_path=kb) == 2
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    assert [r["id"] for r in rows] == ["a1", "a2"] and all(r["decision"] == "" for r in rows)
    assert rows[0]["typical_symptoms"] == "x; y; z"


def test_import_records_decision_name_date_and_audit_log(tmp_path):
    kb = _kb(tmp_path); out = tmp_path / "s.csv"; log = tmp_path / "log.jsonl"
    review.export_sheet(str(out), kb_path=kb)
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    rows[0].update(decision="approved", reviewer_name="Dr. Test", review_date="2026-10-20")
    rows[1].update(decision="CHANGES_REQUESTED", reviewer_name="Dr. Test", comments="caution too weak")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=review.COLUMNS); w.writeheader(); w.writerows(rows)
    applied, errors = review.import_sheet(str(out), kb_path=kb, log_path=str(log), today="2026-10-21")
    assert errors == [] and applied == {"APPROVED": 1, "CHANGES_REQUESTED": 1}
    data = {e["id"]: e for e in json.loads(open(kb, encoding="utf-8").read())}
    assert data["a1"]["review_status"] == "APPROVED" and data["a1"]["reviewed_by"] == "Dr. Test" and data["a1"]["reviewed_on"] == "2026-10-20"
    assert data["a2"]["review_status"] == "CHANGES_REQUESTED" and data["a2"]["reviewed_on"] == "2026-10-21"
    assert len(open(log, encoding="utf-8").read().strip().splitlines()) == 2
    assert review.status(kb) == {"total": 2, "approved": 1, "changes_requested": 1, "draft": 0}


def test_import_never_edits_clinical_text(tmp_path):
    kb = _kb(tmp_path); before = json.loads(open(kb, encoding="utf-8").read())
    out = tmp_path / "s.csv"; review.export_sheet(str(out), kb_path=kb)
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    rows[0].update(decision="APPROVED", reviewer_name="Dr. X", recommendation="TAMPERED TEXT")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=review.COLUMNS); w.writeheader(); w.writerows(rows)
    review.import_sheet(str(out), kb_path=kb, log_path=str(tmp_path / "l.jsonl"))
    after = json.loads(open(kb, encoding="utf-8").read())
    assert after[0]["recommendation"] == before[0]["recommendation"]


def test_import_rejects_incomplete_or_invalid_rows(tmp_path):
    kb = _kb(tmp_path); out = tmp_path / "s.csv"; review.export_sheet(str(out), kb_path=kb)
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    rows[0].update(decision="APPROVED", reviewer_name="")                       # no reviewer name
    rows[1].update(decision="CHANGES_REQUESTED", reviewer_name="Dr. Y", comments="")  # no comments
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=review.COLUMNS); w.writeheader(); w.writerows(rows)
    applied, errors = review.import_sheet(str(out), kb_path=kb, log_path=str(tmp_path / "l.jsonl"))
    assert applied == {"APPROVED": 0, "CHANGES_REQUESTED": 0} and len(errors) == 2
    assert review.status(kb)["draft"] == 2   # nothing was recorded


def test_status_label_wording():
    assert "not yet been reviewed" in review.status_label({"review_status": review.DRAFT})
    approved = review.status_label({"review_status": "APPROVED", "reviewed_by": "Dr. Z", "reviewed_on": "2026-10-20"})
    assert "Dr. Z" in approved and "2026-10-20" in approved
    assert "changes" in review.status_label({"review_status": "CHANGES_REQUESTED"}).lower()


def test_reset_to_draft_after_edit(tmp_path):
    kb = _kb(tmp_path); out = tmp_path / "s.csv"; review.export_sheet(str(out), kb_path=kb)
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig"))); rows[0].update(decision="APPROVED", reviewer_name="Dr. Q")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=review.COLUMNS); w.writeheader(); w.writerows(rows)
    review.import_sheet(str(out), kb_path=kb, log_path=str(tmp_path / "l.jsonl"))
    review.reset_to_draft({"a1"}, kb_path=kb)
    assert review.status(kb)["approved"] == 0
