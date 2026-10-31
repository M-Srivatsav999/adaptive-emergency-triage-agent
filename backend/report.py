"""
report.py — Owner: Sai (Evaluation & Documentation)

Generates a formal, clinician-readable PDF report summarizing the full
triage process: reported symptoms, the differential diagnosis process
(which conditions were considered and why each was ruled in/out), the
final assessment, and the recommendation — formatted so a doctor could
review it as a structured pre-visit summary, not just a casual app output.
"""

import io
import html
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

INK = colors.HexColor("#0B2E33")
TEAL = colors.HexColor("#028090")
GRAY = colors.HexColor("#4B6367")
LIGHTBG = colors.HexColor("#F1F5F4")
ACUITY_COLORS = {
    "EMERGENCY": colors.HexColor("#B3261E"),
    "URGENT": colors.HexColor("#B7791F"),
    "ROUTINE": colors.HexColor("#1E7A5F"),
}


def _esc(text) -> str:
    """
    Escapes dynamic text before it goes into a reportlab Paragraph.
    Paragraph uses a small XML-like markup language internally (for our
    own <b>, <i>, &bull; tags etc.), so any *unescaped* raw text — which
    includes genuinely LLM-generated content once Ollama is connected —
    can contain a stray "<" that reportlab's parser misreads as the start
    of a tag, crashing PDF generation with a "parse ended with unclosed
    tags" error. This never showed up in fallback mode because that text
    was fixed and predictable; live LLM output is not. Every piece of
    dynamic/generated text in this file must be passed through this
    function before being inserted into an f-string handed to Paragraph().
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("ReportTitle", parent=ss["Title"], fontSize=18, textColor=INK, spaceAfter=2))
    ss.add(ParagraphStyle("ReportSub", parent=ss["Normal"], fontSize=10, textColor=GRAY, spaceAfter=14))
    ss.add(ParagraphStyle("Section", parent=ss["Heading2"], fontSize=13, textColor=TEAL, spaceBefore=16, spaceAfter=6))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], fontSize=10.3, textColor=INK, leading=15))
    ss.add(ParagraphStyle("Small", parent=ss["Normal"], fontSize=9, textColor=GRAY, leading=13))
    ss.add(ParagraphStyle("QALine", parent=ss["Normal"], fontSize=9.5, textColor=INK, leading=14, leftIndent=10))
    return ss


def build_report_pdf(pipeline_steps: list, patient_name: str = "") -> bytes:
    """
    pipeline_steps: the same list of {"stage": ..., "result": ...} dicts
    returned by /dt/answer's final "result" response (or /triage/stream).
    Returns raw PDF bytes.
    """
    stages = {s["stage"]: s["result"] for s in pipeline_steps}
    intake = stages.get("intake", {})
    retrieval = stages.get("retrieval", {})
    triage = stages.get("triage", {})
    recommendation = stages.get("recommendation", {})
    final = stages.get("final", {})

    acuity = final.get("acuity_label") or triage.get("acuity_label") or "UNKNOWN"
    condition = final.get("condition") or triage.get("matched_condition") or "Undetermined"
    confidence = final.get("confidence") or triage.get("confidence") or 0
    recommendation_text = final.get("recommendation") or recommendation.get("final_recommendation", "")
    caution = final.get("caution") or recommendation.get("caution")
    differential_note = final.get("differential_note") or recommendation.get("differential_note")
    qa_log = triage.get("qa_log") or intake.get("qa_log") or []
    candidates = intake.get("candidates_considered") or retrieval.get("matches", [])
    ruled_out = intake.get("ruled_out_candidates", [])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    ss = _styles()
    story = []

    # ---- Header ----
    story.append(Paragraph("AI-Driven Clinical Triage — Pre-Visit Summary", ss["ReportTitle"]))
    story.append(Paragraph(
        f"Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}"
        + (f" &middot; Patient: {_esc(patient_name)}" if patient_name else ""),
        ss["ReportSub"]
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DCE6E4")))
    story.append(Spacer(1, 10))

    # ---- Acuity banner ----
    acuity_color = ACUITY_COLORS.get(acuity, GRAY)
    banner_data = [[
        Paragraph(f"<b><font color='white' size=13>{_esc(acuity)}</font></b>", ss["Body"]),
        Paragraph(f"<font color='white'>{_esc(condition)}</font>", ss["Body"]),
        Paragraph(f"<font color='white'>Confidence: {confidence:.0%}</font>" if isinstance(confidence, float) else
                   f"<font color='white'>Confidence: {_esc(confidence)}</font>", ss["Body"]),
    ]]
    banner = Table(banner_data, colWidths=[1.6 * inch, 3.5 * inch, 1.4 * inch])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), acuity_color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(banner)
    story.append(Spacer(1, 8))

    urgent = final.get("urgent_banner") or final.get("safety_override")
    if urgent:
        story.append(Paragraph(f"<b><font color='#B42318'>EMERGENCY SIGNS:</font></b> {_esc(urgent)}", ss["Body"]))
        story.append(Spacer(1, 6))
    if final.get("emergency_contacts"):
        story.append(Paragraph(f"<b>Emergency contacts:</b> {_esc(final['emergency_contacts'])}", ss["Small"]))
    refs = final.get("references") or []
    if refs:
        story.append(Paragraph("<b>Advice checked against:</b> " + "; ".join(_esc(x.get("title") or "") + " (" + _esc(x.get("url") or "") + ")" for x in refs), ss["Small"]))

    story.append(Spacer(1, 10))

    # ---- Reported symptoms ----
    story.append(Paragraph("Patient-Reported Symptoms", ss["Section"]))
    yes_symptoms = intake.get("extracted_symptoms", [])
    no_symptoms = intake.get("ruled_out_symptoms", [])
    story.append(Paragraph(
        f"<b>Confirmed present:</b> {_esc(', '.join(yes_symptoms)) if yes_symptoms else 'none recorded'}",
        ss["Body"]
    ))
    story.append(Paragraph(
        f"<b>Reported absent by the patient:</b> "
        f"{_esc(', '.join(no_symptoms)) if no_symptoms else 'none recorded'}",
        ss["Body"]
    ))
    duration = intake.get("duration")
    if duration and duration != "not applicable (yes/no intake mode)":
        story.append(Paragraph(f"<b>Duration:</b> {_esc(duration)}", ss["Body"]))

    # ---- Differential diagnosis process ----
    story.append(Paragraph("Differential Diagnosis Process", ss["Section"]))
    cand_names = candidates if isinstance(candidates, list) and candidates and isinstance(candidates[0], str) else \
        [c.get("condition", "") for c in candidates] if candidates else []
    if cand_names:
        story.append(Paragraph(
            f"Based on the initial description, the following candidate conditions were "
            f"retrieved from the knowledge base for consideration: <b>{_esc(', '.join(cand_names))}</b>.",
            ss["Body"]
        ))
    if qa_log:
        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>Question-and-answer log:</b>", ss["Body"]))
        for turn in qa_log:
            if turn.get("is_opener"):
                story.append(Paragraph(f"&bull; {_esc(turn['question'])}", ss["QALine"]))
                continue
            ans_text = "Yes" if turn.get("answer") else "No"
            line = f"&bull; <b>Q:</b> {_esc(turn.get('question', ''))} &nbsp; <b>A:</b> {ans_text}"
            story.append(Paragraph(line, ss["QALine"]))
            note = turn.get("elimination_note")
            if note and "No major shift" not in note:
                story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;<i>-&gt; {_esc(note)}</i>", ss["Small"]))
    if ruled_out:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"<b>Candidates that became unlikely given the answers (not excluded with certainty):</b> {_esc(', '.join(ruled_out))}",
            ss["Body"]
        ))

    # ---- Clinical reasoning ----
    story.append(Paragraph("Clinical Reasoning", ss["Section"]))
    triage_reasoning = triage.get("reasoning", "")
    if triage_reasoning:
        story.append(Paragraph(_esc(triage_reasoning), ss["Body"]))

    # ---- Recommendation ----
    story.append(Paragraph("Recommendation", ss["Section"]))
    story.append(Paragraph(_esc(recommendation_text), ss["Body"]))
    if caution:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>[!] Caution:</b> {_esc(caution)}", ss["Body"]))
    if differential_note:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Differential note:</b> {_esc(differential_note)}", ss["Body"]))

    # ---- Footer / disclaimer ----
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DCE6E4")))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "This report was generated by an AI-assisted triage prototype for informational and "
        "pre-visit summary purposes only. It is not a diagnosis and does not replace evaluation "
        "by a licensed healthcare professional. Please bring this summary to your consultation. "
        "Knowledge status for this result: " + _esc(final.get("knowledge_status") or "Draft - not yet reviewed by a clinician") + ". The knowledge base as a whole has not been clinically validated.",
        ss["Small"]
    ))

    doc.build(story)
    return buf.getvalue()
