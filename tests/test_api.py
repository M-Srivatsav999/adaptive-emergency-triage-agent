import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs lifespan -> init_db
        yield c


@pytest.fixture(scope="module")
def H(client):
    """Authorization headers for an ordinary signed-in user (history/feedback belong to the signed-in user)."""
    from backend.users import add_user

    try:
        add_user("tester_user", "a-long-test-password")
    except ValueError:
        pass  # already exists
    token = client.post("/auth/login", json={"username": "tester_user", "password": "a-long-test-password"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _run_dt_session(client, opener, answers=None, max_steps=25, headers=None):
    """Drive /dt/start + /dt/answer. `answers` maps symptom -> bool (default False)."""
    answers = answers or {}
    r = client.post("/dt/start", json={"message": opener}, headers=headers or {}).json()
    steps = 0
    while r["type"] == "question" and steps < max_steps:
        r = client.post(
            "/dt/answer",
            json={
                "session_id": r["session_id"],
                "symptom": r["symptom"],
                "answer": answers.get(r["symptom"], False),
            },
            headers=headers or {},
        ).json()
        steps += 1
    return r


def test_health(client):
    d = client.get("/health").json()
    assert d["status"] == "ok"
    assert d["ollama_connected"] is False
    assert d["conditions_in_knowledge_base"] >= 80
    assert d["database"] in {"sqlite", "postgres"}
    assert "retrieval" in d


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_single_shot_triage_emergency(client):
    r = client.post(
        "/triage",
        json={"symptoms": "Sudden chest pain radiating to my left arm, sweating"},
    ).json()
    assert r["acuity_label"] == "EMERGENCY"
    assert "Heart Attack" in r["condition"]
    assert len(r["reasoning_trace"]) == 4
    assert r["emergency_contacts"] and r["disclaimer"]


def test_decision_tree_flow_reaches_result_and_persists(client, H):
    # A realistic patient confirms the typical conjunctivitis symptoms when asked.
    typical = {"red eye": True, "itchy eyes": True, "watery eyes": True, "eye discharge": True,
               "gritty feeling in eye": True, "swollen eyelids": True}
    r = _run_dt_session(client, "I have a red itchy watery eye with discharge", typical, headers=H)
    assert r["type"] == "result"
    stages = [s["stage"] for s in r["pipeline"]]
    assert stages == ["intake", "retrieval", "triage", "recommendation", "final"]
    final = r["pipeline"][-1]["result"]
    assert final["condition"]
    assert final["acuity_label"] in {"EMERGENCY", "URGENT", "ROUTINE"}

    # Stages must agree: the condition Triage concluded is the one reported downstream.
    retrieval = r["pipeline"][1]["result"]["top_match"]["condition"]
    assert retrieval == final["condition"]

    # Persisted to the audit trail.
    item = client.get(f"/history/{r['session_id']}", headers=H)
    assert item.status_code == 200
    assert item.json()["condition"] == final["condition"]
    listing = client.get("/history", headers=H).json()["sessions"]
    assert any(s["id"] == r["session_id"] for s in listing)


def test_question_count_is_bounded(client):
    r = _run_dt_session(client, "headache and nausea")
    assert r["type"] == "result"


def test_unknown_session_returns_error(client):
    r = client.post(
        "/dt/answer", json={"session_id": "nope", "symptom": "fever", "answer": True}
    ).json()
    assert r["type"] == "error"


def test_history_404_and_delete(client, H):
    assert client.get("/history/does-not-exist", headers=H).status_code == 404
    r = _run_dt_session(client, "twisted my ankle, swelling", headers=H)
    sid = r["session_id"]
    assert client.delete(f"/history/{sid}", headers=H).status_code == 200
    assert client.get(f"/history/{sid}", headers=H).status_code == 404


def test_pdf_report_from_payload_and_history(client, H):
    r = _run_dt_session(client, "runny nose sneezing mild sore throat", headers=H)
    pdf = client.post("/report/pdf", json={"pipeline": r["pipeline"], "patient_name": "Test"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    pdf2 = client.get(f"/history/{r['session_id']}/report.pdf", headers=H)
    assert pdf2.status_code == 200 and pdf2.content.startswith(b"%PDF")


def test_pdf_report_requires_data(client):
    assert client.post("/report/pdf", json={}).status_code == 400


def test_pdf_survives_angle_brackets_in_llm_text(client):
    """Regression: stray '<' in LLM text once crashed reportlab."""
    r = _run_dt_session(client, "red itchy eye")
    for step in r["pipeline"]:
        if step["stage"] == "triage":
            step["result"]["reasoning"] = "BP <90 and HR >120 <b>unclosed & <weird"
    pdf = client.post("/report/pdf", json={"pipeline": r["pipeline"]})
    assert pdf.status_code == 200


def test_ollama_url_env_is_honored():
    from backend import config, llm_client

    assert config.OLLAMA_BASE_URL == "http://127.0.0.1:1"
    assert llm_client.OLLAMA_URL.startswith("http://127.0.0.1:1/")


def test_red_flag_escalates_and_is_reported_immediately(client):
    r = client.post("/dt/start", json={"message": "my father was bitten by a snake and his eyelids are drooping"}).json()
    assert r["red_flags"] and "Seek emergency" in r["urgent_banner"]
    n = 0
    while r["type"] == "question" and n < 25:
        r = client.post("/dt/answer", json={"session_id": r["session_id"], "symptom": r["symptom"], "answer": False}).json()
        n += 1
    final = r["pipeline"][-1]["result"]
    assert final["acuity_label"] == "EMERGENCY"
    assert final["urgent_banner"]


def test_red_flag_in_free_text_triage(client):
    r = client.post("/triage", json={"symptoms": "mild runny nose but my father is unconscious and not responding"}).json()
    assert r["acuity_label"] == "EMERGENCY" and r["red_flags"]


def test_feedback_roundtrip(client, H):
    r = _run_dt_session(client, "twisted my ankle, swelling, can walk", headers=H)
    sid = r["session_id"]
    ok = client.post("/feedback", headers=H, json={"session_id": sid, "correct": False, "corrected_condition": "Suspected Fracture", "notes": "x-ray"})
    assert ok.status_code == 200 and ok.json() == {"ok": True}
    assert client.post("/feedback", headers=H, json={"session_id": "nope", "correct": True}).status_code == 404


def test_pdf_includes_emergency_block(client):
    r = client.post("/dt/start", json={"message": "snake bit my leg"}).json()
    n = 0
    while r["type"] == "question" and n < 25:
        r = client.post("/dt/answer", json={"session_id": r["session_id"], "symptom": r["symptom"], "answer": False}).json()
        n += 1
    pdf = client.post("/report/pdf", json={"pipeline": r["pipeline"]})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
