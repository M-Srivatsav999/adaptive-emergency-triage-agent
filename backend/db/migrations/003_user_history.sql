-- Per-user history: every stored session can belong to the registered user who ran it.
-- NULL owner = an anonymous session (visible to staff only, subject to retention).
ALTER TABLE triage_sessions ADD COLUMN IF NOT EXISTS owner TEXT;
CREATE INDEX IF NOT EXISTS triage_sessions_owner_idx ON triage_sessions (owner, created_at DESC);
-- Ordinary self-registered accounts have the role 'user'.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('user','health_worker','clinician','admin'));
