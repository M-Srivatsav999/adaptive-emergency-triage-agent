-- PostgreSQL + pgvector schema for the AI-Driven Clinical Triage System.
-- Idempotent: safe to run on every start.

CREATE EXTENSION IF NOT EXISTS vector;

-- Knowledge base (seeded from backend/rag/knowledge_base.json)
CREATE TABLE IF NOT EXISTS conditions (
    id              TEXT PRIMARY KEY,
    condition       TEXT NOT NULL,
    description     TEXT NOT NULL,
    keywords        TEXT[] NOT NULL,
    acuity          SMALLINT NOT NULL CHECK (acuity BETWEEN 1 AND 5),
    acuity_label    TEXT NOT NULL CHECK (acuity_label IN ('EMERGENCY','URGENT','ROUTINE')),
    source          TEXT,
    recommendation  TEXT,
    caution         TEXT,
    red_flags       TEXT[] NOT NULL DEFAULT '{}',
    self_care       TEXT,
    review_status   TEXT,
    reviewed_by     TEXT,
    reviewed_on     DATE,
    reviewer_comments TEXT,
    content_hash    TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migration for databases created before clinician-review tracking existed
ALTER TABLE conditions ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
ALTER TABLE conditions ADD COLUMN IF NOT EXISTS reviewed_on DATE;
ALTER TABLE conditions ADD COLUMN IF NOT EXISTS reviewer_comments TEXT;

-- RAG chunks: several retrievable facts per condition, one row per embedder.
-- Dimension 768 = nomic-embed-text; the offline hashing embedder also emits 768.
CREATE TABLE IF NOT EXISTS medical_chunks (
    id            BIGSERIAL PRIMARY KEY,
    condition_id  TEXT NOT NULL REFERENCES conditions(id) ON DELETE CASCADE,
    chunk_type    TEXT NOT NULL,
    content       TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    embedder      TEXT NOT NULL,
    embedding     vector(768) NOT NULL,
    UNIQUE (condition_id, chunk_type, embedder)
);
CREATE INDEX IF NOT EXISTS medical_chunks_embedder_idx ON medical_chunks (embedder);
CREATE INDEX IF NOT EXISTS medical_chunks_embedding_hnsw
    ON medical_chunks USING hnsw (embedding vector_cosine_ops);

-- Audit trail of completed triage sessions (full explainable pipeline as JSONB)
CREATE TABLE IF NOT EXISTS triage_sessions (
    id          TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode        TEXT NOT NULL,
    condition   TEXT,
    acuity      TEXT,
    confidence  REAL,
    pipeline    JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS triage_sessions_created_idx ON triage_sessions (created_at DESC);

-- Clinician feedback: ground truth for continuous evaluation / future retraining
CREATE TABLE IF NOT EXISTS clinician_feedback (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          TEXT NOT NULL,
    correct             BOOLEAN NOT NULL,
    corrected_condition TEXT,
    corrected_acuity    TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
