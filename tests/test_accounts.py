"""Open access: anyone can use the tool; anyone can create a free account; every account has a PRIVATE history."""
import pytest
from fastapi.testclient import TestClient

from backend import config, security, store
from backend.main import app
from backend.users import add_user


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register(client, name, pw="my-secret-pass"):
    r = client.post("/auth/register", json={"username": name, "password": pw})
    return r


def _hdr(client, name, pw="my-secret-pass"):
    return {"Authorization": "Bearer " + client.post("/auth/login", json={"username": name, "password": pw}).json()["token"]}


def _run(client, text, headers=None, answers=None):
    """Complete a yes/no triage session (optionally while signed in) and return the final response."""
    answers = answers or {}
    r = client.post("/dt/start", json={"message": text}, headers=headers or {}).json()
    n = 0
    while r["type"] == "question" and n < 25:
        r = client.post("/dt/answer", json={"session_id": r["session_id"], "symptom": r["symptom"],
                                            "answer": answers.get(r["symptom"], False)}, headers=headers or {}).json()
        n += 1
    return r


# ---------------------------------------------------------------------------- open access
def test_everyone_can_use_the_tool_without_any_account(client):
    assert client.post("/triage", json={"symptoms": "runny nose and sneezing for two days"}).status_code == 200
    assert client.post("/dt/start", json={"message": "headache"}).status_code == 200
    assert client.post("/chat/message", json={"message": "fever and cough for 3 days"}).status_code == 200
    assert client.post("/report/pdf", json={"pipeline": [{"stage": "final", "result": {"condition": "X", "acuity_label": "ROUTINE"}}]}).status_code == 200


# ---------------------------------------------------------------------------- registration
def test_anyone_can_register_and_is_a_plain_user(client):
    r = _register(client, "lakshmi_k")
    assert r.status_code == 201 and r.json()["role"] == "user" and r.json()["token"]
    me = client.get("/auth/me", headers={"Authorization": "Bearer " + r.json()["token"]}).json()
    assert me == {"username": "lakshmi_k", "role": "user"}
    assert client.post("/auth/login", json={"username": "lakshmi_k", "password": "my-secret-pass"}).status_code == 200


@pytest.mark.parametrize("name,pw,code", [
    ("lakshmi_k", "another-pass-1", 409),      # taken
    ("ab", "my-secret-pass", 422),             # too short
    ("bad name!", "my-secret-pass", 422),      # invalid characters
    ("admin", "my-secret-pass", 422),          # reserved
    ("system", "my-secret-pass", 422),         # reserved (used as an audit actor)
    ("newuser1", "short", 422),                # password too short
    ("samepass1", "samepass1", 422),           # password equals username
])
def test_registration_validation(client, name, pw, code):
    assert _register(client, name, pw).status_code == code


def test_registration_can_be_closed_and_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(config, "REGISTRATION_OPEN", False)
    assert _register(client, "closed_user1").status_code == 403
    monkeypatch.setattr(config, "REGISTRATION_OPEN", True)
    security.limiter.reset()
    monkeypatch.setattr(config, "REGISTER_LIMIT_PER_HOUR", 2)
    codes = [_register(client, f"spam_user{i}").status_code for i in range(4)]
    assert codes[:2] == [201, 201] and 429 in codes[2:]
    security.limiter.reset()


# ---------------------------------------------------------------------------- private history
def test_each_user_has_their_own_private_history(client):
    _register(client, "ravi_p"); _register(client, "sita_m")
    a, b = _hdr(client, "ravi_p"), _hdr(client, "sita_m")
    ra = _run(client, "I have a red itchy watery eye with discharge", a)["session_id"]
    rb = _run(client, "runny nose sneezing mild sore throat", b)["session_id"]
    anon = _run(client, "twisted my ankle swelling can walk")["session_id"]

    mine_a = {s["id"] for s in client.get("/history", headers=a).json()["sessions"]}
    mine_b = {s["id"] for s in client.get("/history", headers=b).json()["sessions"]}
    assert ra in mine_a and rb not in mine_a and anon not in mine_a
    assert rb in mine_b and ra not in mine_b and anon not in mine_b


def test_users_cannot_open_download_feedback_or_delete_other_peoples_records(client):
    a, b = _hdr(client, "ravi_p"), _hdr(client, "sita_m")
    ra = next(s["id"] for s in client.get("/history", headers=a).json()["sessions"])
    assert client.get(f"/history/{ra}", headers=a).status_code == 200
    assert client.get(f"/history/{ra}", headers=b).status_code == 404                 # not revealed to others
    assert client.get(f"/history/{ra}/report.pdf", headers=b).status_code == 404
    assert client.post("/feedback", headers=b, json={"session_id": ra, "correct": True}).status_code == 404
    assert client.delete(f"/history/{ra}", headers=b).status_code == 404
    assert client.get(f"/history/{ra}", headers=a).status_code == 200                 # still there


def test_owner_can_download_feedback_and_delete_their_own(client):
    _register(client, "own_user1")
    h = _hdr(client, "own_user1")
    sid = _run(client, "red itchy eye with discharge", h)["session_id"]
    pdf = client.get(f"/history/{sid}/report.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.post("/feedback", headers=h, json={"session_id": sid, "correct": True, "notes": "helpful"}).status_code == 200
    assert client.delete(f"/history/{sid}", headers=h).status_code == 200
    assert client.get(f"/history/{sid}", headers=h).status_code == 404


def test_anonymous_sessions_are_not_visible_to_any_user(client):
    sid = _run(client, "twisted my ankle, swelling, can walk")["session_id"]       # anonymous
    user = _hdr(client, "ravi_p")
    assert not any(s["id"] == sid for s in client.get("/history", headers=user).json()["sessions"])
    assert client.get(f"/history/{sid}", headers=user).status_code == 404


def test_nobody_can_list_other_peoples_records_and_there_are_no_admin_pages(client):
    user = _hdr(client, "ravi_p")
    owners = {s["owner"] for s in client.get("/history", headers=user).json()["sessions"]}
    assert owners <= {"ravi_p"}                                  # never anyone else's
    assert client.get("/admin/stats", headers=user).status_code == 404
    assert client.get("/admin/audit", headers=user).status_code == 404
    assert client.post("/admin/purge", headers=user).status_code == 404
    assert client.get("/admin").status_code == 404


def test_history_needs_login_even_though_triage_does_not(client):
    assert client.get("/history").status_code == 401
    assert client.get("/auth/me").status_code == 401


# ---------------------------------------------------------------------------- account controls
def test_change_password(client):
    _register(client, "pw_user1")
    h = _hdr(client, "pw_user1")
    assert client.post("/auth/password", headers=h, json={"old_password": "wrong-old-pass", "new_password": "brand-new-pass"}).status_code == 401
    assert client.post("/auth/password", headers=h, json={"old_password": "my-secret-pass", "new_password": "short"}).status_code == 422
    assert client.post("/auth/password", headers=h, json={"old_password": "my-secret-pass", "new_password": "brand-new-pass"}).status_code == 200
    assert client.post("/auth/login", json={"username": "pw_user1", "password": "my-secret-pass"}).status_code == 401
    assert client.post("/auth/login", json={"username": "pw_user1", "password": "brand-new-pass"}).status_code == 200


def test_user_can_erase_account_and_all_their_data(client):
    _register(client, "erase_me1")
    h = _hdr(client, "erase_me1")
    sid = _run(client, "red itchy eye with discharge", h)["session_id"]
    assert store.get_session(sid)["owner"] == "erase_me1"
    r = client.delete("/auth/me", headers=h)
    assert r.status_code == 200 and r.json()["sessions_erased"] >= 1
    assert store.get_session(sid) is None and store.get_user("erase_me1") is None
    assert client.post("/auth/login", json={"username": "erase_me1", "password": "my-secret-pass"}).status_code == 401


def test_owner_is_stored_only_when_signed_in(client):
    _register(client, "owner_chk1")
    h = _hdr(client, "owner_chk1")
    signed = _run(client, "red itchy eye with discharge", h)["session_id"]
    anon = _run(client, "red itchy eye with discharge")["session_id"]
    assert store.get_session(signed)["owner"] == "owner_chk1" and store.get_session(anon)["owner"] is None


def test_frontend_has_account_features_and_still_works_without_login(client):
    html = client.get("/").text
    for needle in ("acctBar", "authModal", "histModal", "/auth/register", "without an account", "private history"):
        assert needle in html
    assert 'apiFetch("/dt/start"' in html          # token is attached when present, optional when absent


def test_accounts_made_by_older_versions_with_staff_roles_become_ordinary_users(client):
    """Upgrading from v6: a leftover 'clinician' row must not keep any extra power."""
    import time as _t
    with store._sqlite() as c:
        c.execute("INSERT OR REPLACE INTO users (username, password_hash, role, disabled, created_at) VALUES (?,?,?,0,?)",
                  ("old_doc", security.hash_password("a-long-test-password"), "clinician", _t.time()))
    store.init_db()
    assert store.get_user("old_doc")["role"] == "user"
    r = client.post("/auth/login", json={"username": "old_doc", "password": "a-long-test-password"})
    assert r.status_code == 200 and r.json()["role"] == "user"
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.get("/admin/stats", headers=h).status_code == 404
    assert all(s["owner"] == "old_doc" for s in client.get("/history", headers=h).json()["sessions"])
