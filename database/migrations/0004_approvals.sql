-- Phase 6: durable approval decisions (every write action needs one).

CREATE TABLE IF NOT EXISTS approvals (
    id          UUID PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    approver    TEXT NOT NULL,
    decision    TEXT NOT NULL CHECK (decision IN ('approved', 'edited', 'rejected')),
    plan        JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_approvals_incident ON approvals (incident_id);
