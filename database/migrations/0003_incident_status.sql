-- Phase 4: incident workflow status, raw alert labels and error column.
-- status: open -> investigating -> diagnosed | failed | resolved

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open';
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS alert_labels JSONB;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS error TEXT;

CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents (status);
CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint
    ON incidents ((alert_labels->>'fingerprint'));
