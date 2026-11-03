-- Core KubeSentra schema (implementation document section 6.3).
-- runbook_chunks / incidents / evidence_raw / audit_log plus retrieval indexes.
-- Idempotent guards are belt-and-braces; the runner applies each file once.

CREATE TABLE IF NOT EXISTS runbook_chunks (
    id           SERIAL PRIMARY KEY,
    runbook      TEXT NOT NULL,
    section      TEXT NOT NULL,
    content      TEXT NOT NULL,
    symptoms     TEXT[],
    embedding    VECTOR(384),
    tsv          TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS idx_runbook_chunks_embedding
    ON runbook_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_runbook_chunks_tsv
    ON runbook_chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS incidents (
    id                  UUID PRIMARY KEY,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    alert_name          TEXT,
    namespace           TEXT,
    service             TEXT,
    symptoms            TEXT,
    root_cause          TEXT,
    root_cause_category TEXT,
    actions             JSONB,
    resolved            BOOLEAN,
    time_to_diagnosis_s INTEGER,
    summary             TEXT,
    embedding           VECTOR(384)
);

CREATE INDEX IF NOT EXISTS idx_incidents_embedding
    ON incidents USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_incidents_service
    ON incidents (namespace, service);
CREATE INDEX IF NOT EXISTS idx_incidents_created_at
    ON incidents (created_at);

CREATE TABLE IF NOT EXISTS evidence_raw (
    id          TEXT,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,
    raw_output  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (incident_id, id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
    actor       TEXT NOT NULL,
    event       TEXT NOT NULL,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_incident
    ON audit_log (incident_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at
    ON audit_log (created_at);
