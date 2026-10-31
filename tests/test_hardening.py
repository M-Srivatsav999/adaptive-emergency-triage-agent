import logging
import time

import pytest
from fastapi.testclient import TestClient

from backend import config, metrics, security, store
from backend.main import _shown, app
from backend.users import add_user


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, user, pw):
    return client.post("/auth/login", json={"username": user, "password": pw})


@pytest.fixture(scope="module", autouse=True)
def accounts(client):
    for name in ("hw_user", "doc_user"):
        try:
            add_user(name, "a-long-test-password")
        except ValueError:
            pass


def _h(client, user):
    tok = _login(client, user, "a-long-test-password").json()["token"]
    return {"Authorization": f"Bearer {tok}"}


# ------------------------------------------------------------------ passwords / tokens
def test_password_hashing_and_policy():
    h = security.hash_password("correct horse battery")
    assert h.startswith("pbkdf2_sha256$") and security.verify_password("correct horse battery", h)
    assert not security.verify_password("wrong", h) and not security.verify_password("x", "garbage")
    assert security.hash_password("same") != security.hash_password("same")        # per-user salt
    assert security.password_problem("short") and security.password_problem("a-very-long-password") is None


def test_token_tamper_and_expiry():
    t = security.make_token("u", "user")
    assert security.verify_token(t) == {"username": "u", "role": "user"}
    body, sig = t.split(".")
    assert security.verify_token(body + "." + sig[:-2] + "AA") is None
    assert security.verify_token(security.make_token("u", "user", ttl=-1)) is None
    assert security.verify_token(security.make_token("u", "admin")) is None        # no such role exists any more
    forged = security.make_token("u", "user").split(".")[0]
    assert security.verify_token(forged + ".bad") is None


# ------------------------------------------------------------------------ login / roles
def test_login_ok_and_bad_credentials(client):
    ok = _login(client, "hw_user", "a-long-test-password")
    assert ok.status_code == 200 and ok.json()["role"] == "user"
    assert _login(client, "hw_user", "wrong-password-x").status_code == 401
    assert _login(client, "nobody", "whatever-password").status_code == 401


def test_history_needs_your_own_login_but_triage_is_open_to_everyone(client):
    assert client.get("/history").status_code == 401
    assert client.post("/feedback", json={"session_id": "x", "correct": True}).status_code == 401
    assert client.post("/triage", json={"symptoms": "runny nose and sneezing"}).status_code == 200
    assert client.post("/dt/start", json={"message": "headache"}).status_code == 200


def test_there_are_no_staff_or_admin_endpoints_and_everyone_is_the_same_kind_of_user(client):
    hw, doc = _h(client, "hw_user"), _h(client, "doc_user")
    assert client.get("/history", headers=hw).status_code == 200
    for path in ("/admin", "/admin/stats", "/admin/audit", "/feedback/summary"):
        assert client.get(path, headers=doc).status_code == 404, path
    assert client.post("/admin/purge", headers=doc).status_code == 404
    assert client.delete("/history/nope", headers=hw).status_code == 404


def test_disabled_user_cannot_login(client):
    add_user("temp_user", "a-long-test-password") if not store.get_user("temp_user") else None
    store.set_user_disabled("temp_user", True)
    assert _login(client, "temp_user", "a-long-test-password").status_code == 401
    store.set_user_disabled("temp_user", False)
    assert _login(client, "temp_user", "a-long-test-password").status_code == 200


def test_account_lockout_after_repeated_failures(client, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES", 3)
    security.clear_lockouts()
    for _ in range(3):
        assert _login(client, "hw_user", "wrong-password-x").status_code == 401
    assert _login(client, "hw_user", "a-long-test-password").status_code == 429   # locked even with the right password
    security.clear_lockouts()
    assert _login(client, "hw_user", "a-long-test-password").status_code == 200


def test_auth_mode_off_removes_login_requirement(client, monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "off")
    assert client.get("/history").status_code == 200


# ------------------------------------------------------------------- rate limit / limits
def test_rate_limiter_blocks_bursts_then_recovers(client, monkeypatch):
    security.limiter.reset()
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 5)
    codes = [client.post("/triage", json={"symptoms": "runny nose"}).status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and 429 in codes[5:]
    security.limiter.reset()
    assert client.post("/triage", json={"symptoms": "runny nose"}).status_code == 200


def test_login_rate_limit(client, monkeypatch):
    security.limiter.reset()
    monkeypatch.setattr(config, "LOGIN_RATE_LIMIT_PER_MINUTE", 3)
    codes = [_login(client, "hw_user", "wrong-password-x").status_code for _ in range(5)]
    assert 429 in codes
    security.limiter.reset()
    security.clear_lockouts()


def test_input_length_and_body_size_limits(client):
    assert client.post("/triage", json={"symptoms": "x" * (config.MAX_INPUT_CHARS + 1)}).status_code == 422
    assert client.post("/dt/start", json={"message": "y" * (config.MAX_INPUT_CHARS + 1)}).status_code == 422
    big = client.post("/report/pdf", content=b"{" + b" " * 1_100_000 + b"}", headers={"content-type": "application/json"})
    assert big.status_code == 413


def test_security_headers_present(client):
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer" and h["x-request-id"]
    assert "no-store" in client.get("/history").headers["cache-control"]


def test_csp_and_hsts_in_production_mode(client, monkeypatch):
    monkeypatch.setattr(config, "ENV", "production")
    r = client.get("/health", headers={"x-forwarded-proto": "https"})
    assert "default-src 'self'" in r.headers["content-security-policy"] and "max-age" in r.headers["strict-transport-security"]


# ------------------------------------------------------------------- privacy / retention
def test_retention_purge_removes_only_old_sessions(client):
    import json

    old_id, new_id = "old-session-test", "new-session-test"
    pipeline = [{"stage": "final", "result": {"condition": "X", "acuity_label": "ROUTINE", "confidence": 0.5}}]
    store.save_session(new_id, "yes_no", pipeline)
    with store._sqlite() as c:
        c.execute("INSERT OR REPLACE INTO triage_sessions (id, created_at, mode, condition, acuity, confidence, pipeline_json, owner) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (old_id, time.time() - 200 * 86400, "yes_no", "X", "ROUTINE", 0.5, json.dumps(pipeline), None))
    assert store.purge_older_than(0) == 0                                  # 0 = keep forever
    assert store.purge_older_than(90) >= 1
    assert store.get_session(old_id) is None and store.get_session(new_id) is not None


def test_store_sessions_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(config, "STORE_SESSIONS", False)
    store.save_session("should-not-exist", "yes_no", [{"stage": "final", "result": {"condition": "X"}}])
    assert store.get_session("should-not-exist") is None


def test_audit_log_records_actions_without_patient_text(client):
    secret = "zzqq-very-private-symptom-text"
    client.post("/triage", json={"symptoms": f"{secret} headache"})
    me = _h(client, "hw_user")
    client.get("/history", headers=me)
    entries = store.list_audit(200)
    actions = {e["action"] for e in entries}
    assert {"login_ok", "history_listed"} <= actions
    assert secret not in str(entries)


def test_access_logs_never_contain_patient_text(client, caplog):
    secret = "qqzz-secret-complaint-words"
    with caplog.at_level(logging.INFO, logger="triage"):
        client.post("/dt/start", json={"message": f"{secret} chest pain"})
    assert "http" in caplog.text and secret not in caplog.text


# ------------------------------------------------------------- production safety checks
def test_production_config_validation(monkeypatch):
    monkeypatch.setattr(config, "ENV", "production")
    monkeypatch.setattr(config, "SECRET_KEY", "")
    monkeypatch.setattr(config, "CORS_ORIGINS", ["*"])
    monkeypatch.setattr(config, "AUTH_MODE", "off")
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://triage:triage@db:5432/triage")
    problems = " | ".join(config.production_problems())
    for needle in ("SECRET_KEY", "CORS_ORIGINS", "AUTH_MODE", "database password"):
        assert needle in problems
    monkeypatch.setattr(config, "SECRET_KEY", "x" * 40)
    monkeypatch.setattr(config, "CORS_ORIGINS", ["https://clinic.local"])
    monkeypatch.setattr(config, "AUTH_MODE", "open")
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://triage:S0me-Strong-pw@db:5432/triage")
    assert config.production_problems() == []


def test_app_refuses_to_start_with_unsafe_production_settings(monkeypatch):
    monkeypatch.setattr(config, "ENV", "production")
    monkeypatch.setattr(config, "SECRET_KEY", "")
    with pytest.raises(RuntimeError, match="unsafe settings"):
        with TestClient(app):
            pass


# ------------------------------------------------------------------- monitoring / honesty
def test_metrics_endpoint_counts_outcomes(client):
    metrics.reset()
    client.post("/triage", json={"symptoms": "snake bit my leg"})
    client.post("/triage", json={"symptoms": "runny nose and sneezing for two days"})
    text = client.get("/metrics").text
    assert "triage_results_total" in text and 'acuity="EMERGENCY"' in text and "triage_red_flag_total" in text


def test_ready_probe(client):
    assert client.get("/ready").json()["ready"] is True


def test_result_reports_which_engine_wrote_it_and_never_blames_ollama_wrongly(client):
    r = client.post("/triage", json={"symptoms": "runny nose and sneezing for two days"}).json()
    assert r["ai_mode"] == "built_in_rules" and "AI model" in r["ai_note"]
    from backend.agents import triage_agent
    assert "Ollama not running" not in open(triage_agent.__file__, encoding="utf-8").read()


def test_displayed_probabilities_are_never_0_or_100_percent():
    assert _shown(1.0) == "98%" and _shown(0.0) == "2%" and _shown(0.5) == "50%"


def test_pdf_wording_does_not_claim_certain_exclusion():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "backend" / "report.py").read_text(encoding="utf-8")
    assert "ruled out during questioning" not in src and "not excluded with certainty" in src


# ------------------------------------------------------------------ installable app
def test_pwa_assets_are_served(client):
    for path, mime in (("/manifest.webmanifest", "manifest"), ("/sw.js", "javascript"),
                       ("/icon-192.png", "image/png"), ("/icon-512.png", "image/png")):
        r = client.get(path)
        assert r.status_code == 200 and mime in r.headers["content-type"], path


def test_page_is_mobile_ready_and_has_consent_notice(client):
    html = client.get("/").text
    assert 'name="viewport"' in html and 'rel="manifest"' in html and "consent_v1" in html


def test_service_worker_never_caches_api_or_patient_data():
    from pathlib import Path
    sw = (Path(__file__).resolve().parent.parent / "frontend" / "sw.js").read_text(encoding="utf-8")
    assert 'e.request.method !== "GET"' in sw and "SHELL.includes(url.pathname)" in sw
    for forbidden in ("/history", "/triage", "/dt/", "/admin", "/feedback"):
        assert f'"{forbidden}' not in sw.split("const SHELL")[1].split("];")[0]


def test_health_reports_privacy_posture(client):
    d = client.get("/health").json()
    assert d["auth_mode"] in {"off", "open"} and "retention_days" in d and "store_sessions" in d


# ------------------------------------------------------------------------ operations
def test_sqlite_backup_verify_and_prune(tmp_path, monkeypatch):
    from backend import maintenance
    store.save_session("backup-test-1", "yes_no", [{"stage": "final", "result": {"condition": "X", "acuity_label": "ROUTINE"}}])
    f1 = maintenance.backup(tmp_path)
    assert f1.exists() and maintenance.verify(f1)["integrity"] == "ok"
    time.sleep(1.1)
    f2 = maintenance.backup(tmp_path)
    assert maintenance.prune(1, tmp_path) == 1 and f2.exists() and not f1.exists()


def test_corrupt_backup_is_rejected(tmp_path):
    from backend import maintenance
    bad = tmp_path / "triage-bad.db"
    bad.write_bytes(b"this is not a database")
    with pytest.raises(Exception):
        maintenance.verify(bad)
    with pytest.raises(RuntimeError):
        maintenance.verify(tmp_path / "missing.db")


def test_client_key_uses_forwarded_address_only_when_proxy_trusted(monkeypatch):
    class Req:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.2"}
        client = type("C", (), {"host": "172.18.0.5"})()
    assert security.client_key(Req()) == "172.18.0.5"           # not trusted: ignore spoofable header
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    assert security.client_key(Req()) == "203.0.113.7"


def test_user_creation_validation():
    with pytest.raises(ValueError):
        add_user("bad name!", "a-long-test-password")
    with pytest.raises(ValueError):
        add_user("okname", "short")


def test_production_refuses_to_fall_back_to_sqlite_when_postgres_is_unreachable(monkeypatch):
    monkeypatch.setattr(config, "ENV", "production")
    monkeypatch.setattr(config, "SECRET_KEY", "k" * 40)
    monkeypatch.setattr(config, "CORS_ORIGINS", ["https://clinic.local"])
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://triage:Another-Strong-pw@127.0.0.1:1/nope")  # nothing listens on port 1
    with pytest.raises(RuntimeError, match="not reachable"):
        with TestClient(app):
            pass
    store._backend = "sqlite"
