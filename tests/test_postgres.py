"""
Integration tests against a REAL PostgreSQL + pgvector instance.

Skipped unless TEST_DATABASE_URL is set, e.g.
    TEST_DATABASE_URL=postgresql://triage:triage@localhost:5432/triage_test pytest tests/test_postgres.py
(In docker compose:  docker compose run --rm -e TEST_DATABASE_URL=... backend pytest)
"""
import os

import pytest

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="module", autouse=True)
def pg():
    from backend import config, database, store
    from backend.agents import retrieval_agent

    old = config.DATABASE_URL
    config.DATABASE_URL = URL
    with database.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS medical_chunks, conditions, triage_sessions, clinician_feedback, users, audit_log, schema_migrations CASCADE")
    store.init_db()
    retrieval_agent.reset_retriever()
    yield
    config.DATABASE_URL = old
    store._backend = "sqlite"
    retrieval_agent.reset_retriever()


def test_schema_and_extension():
    from backend import database

    with database.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
        assert cur.fetchone()
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_name IN "
                    "('conditions','medical_chunks','triage_sessions','clinician_feedback')")
        assert cur.fetchone()[0] == 4


def test_ingest_is_idempotent_and_complete():
    from backend import database
    from backend.rag.ingest import ingest

    first = ingest("hashing", reset=True, verbose=False)
    assert first["chunks_written"] >= first["conditions"] * 3
    second = ingest("hashing", verbose=False)
    assert second["chunks_written"] == 0 and second["chunks_skipped"] == first["chunks_written"]
    with database.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM conditions")
        assert cur.fetchone()[0] == first["conditions"]
        cur.execute("SELECT count(DISTINCT acuity_label) FROM conditions")
        assert cur.fetchone()[0] == 3


def test_hnsw_index_exists():
    from backend import database

    with database.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname='medical_chunks_embedding_hnsw'")
        assert "hnsw" in cur.fetchone()[0]


def test_pgvector_retriever_finds_correct_conditions():
    from backend.rag.retriever import PgVectorRetriever

    r = PgVectorRetriever()
    assert "hashing" in r.backend_name
    top = r.retrieve("farmer drank pesticide drooling twitching muscles", top_k=3)
    assert any("Pesticide" in m["condition"] for m in top)
    top = r.retrieve("two fang marks snake bite swelling leg", top_k=3)
    assert any("Snakebite" in m["condition"] for m in top)


def test_hybrid_factory_includes_pgvector():
    from backend.rag.retriever import build_retriever

    assert "pgvector" in build_retriever().backend_name


def test_sessions_persist_in_postgres_jsonb_and_feedback():
    from backend import store

    assert store.backend_name() == "postgres"
    pipeline = [{"stage": "final", "result": {"condition": "Malaria", "acuity_label": "URGENT", "confidence": 0.8}}]
    store.save_session("pg-test-1", "yes_no", pipeline)
    got = store.get_session("pg-test-1")
    assert got["condition"] == "Malaria" and got["pipeline"][0]["stage"] == "final"
    assert any(s["id"] == "pg-test-1" for s in store.list_sessions())
    store.add_feedback("pg-test-1", False, "Dengue Fever", "URGENT", "platelets low")
    assert store.feedback_summary()["reviews"] >= 1
    assert store.delete_session("pg-test-1") and store.get_session("pg-test-1") is None


def test_ingest_removes_conditions_deleted_from_kb(tmp_path, monkeypatch):
    from backend import database
    from backend.rag import ingest as ing

    with database.connect() as conn:
        conn.execute("INSERT INTO conditions (id, condition, description, keywords, acuity, acuity_label, content_hash) "
                     "VALUES ('zz','Ghost','x',ARRAY['a'],1,'EMERGENCY','h')")
    ing.ingest("hashing", verbose=False)
    with database.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM conditions WHERE id='zz'")
        assert cur.fetchone()[0] == 0


def test_review_columns_and_migration_exist():
    from backend import database

    with database.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='conditions' "
                    "AND column_name IN ('reviewed_by','reviewed_on','reviewer_comments')")
        assert {r[0] for r in cur.fetchall()} == {"reviewed_by", "reviewed_on", "reviewer_comments"}
        cur.execute("SELECT count(*) FROM conditions WHERE review_status LIKE 'DRAFT%'")
        assert cur.fetchone()[0] >= 150


def test_migrations_recorded_and_repeatable():
    from backend import database

    assert database.migrate() == []          # second run applies nothing
    with database.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        assert [r[0] for r in cur.fetchall()] == ["001_baseline", "002_users_audit", "003_user_history", "004_open_access"]
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_name IN ('users','audit_log')")
        assert cur.fetchone()[0] == 2


def test_users_audit_and_purge_work_on_postgres(tmp_path):
    from backend import security, store

    store.create_user("pg_user", security.hash_password("a-long-test-password"), "user")
    assert store.get_user("pg_user")["role"] == "user" and store.count_users() >= 1
    store.audit("pg_user", "unit_test", "target-1", "detail")
    assert any(e["action"] == "unit_test" for e in store.list_audit(20))
    store.save_session("pg-old", "yes_no", [{"stage": "final", "result": {"condition": "X", "acuity_label": "ROUTINE"}}])
    from backend import database
    with database.connect() as conn:
        conn.execute("UPDATE triage_sessions SET created_at = now() - interval '200 days' WHERE id='pg-old'")
    assert store.purge_older_than(90) >= 1 and store.get_session("pg-old") is None


def test_postgres_backup_and_verify(tmp_path):
    import shutil
    import pytest as _pt

    if not (shutil.which("pg_dump") and shutil.which("pg_restore")):
        _pt.skip("pg_dump/pg_restore not installed")
    from backend import maintenance

    f = maintenance.backup(tmp_path)
    assert f.suffix == ".dump" and maintenance.verify(f)["format"] == "postgres"
