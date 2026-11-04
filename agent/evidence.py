"""Evidence recording: summaries enter LLM context, raw output goes to the
`evidence_raw` table (implementation document 4.1 / 6.3)."""

from __future__ import annotations

import json

from agent.state import Evidence, EvidenceSource
from common.safety import cap, redact
from database.connection import get_pool

# raw payloads are capped before storage too - they are for audit, not replay
RAW_CAP = 200_000


def record_evidence(incident_id: str, source: EvidenceSource, summary: str,
                    raw_output: str = "", existing_count: int = 0) -> Evidence:
    """Create the next evidence item (E{n}) and persist its raw output.

    `existing_count` must be the number of evidence items already in the
    incident state so IDs stay unique and monotonic.
    """
    evidence_id = f"E{existing_count + 1}"
    raw = cap(redact(raw_output or summary), RAW_CAP)
    try:
        with get_pool().connection() as conn:
            conn.execute(
                "INSERT INTO evidence_raw (id, incident_id, source, raw_output) "
                "VALUES (%s, %s::uuid, %s, %s) "
                "ON CONFLICT (incident_id, id) DO NOTHING",
                (evidence_id, incident_id, source, raw),
            )
    except Exception:  # noqa: BLE001 - raw persistence must not kill an
        # investigation; the summary is still recorded in state
        raw = raw  # keep going - audit gap beats lost investigation
    return Evidence(
        id=evidence_id, source=source, summary=summary,
        raw_ref=f"evidence_raw:{incident_id}:{evidence_id}",
        incident_id=incident_id,
    )


def store_step_audit(incident_id: str, step: dict) -> None:
    """Persist a timeline step to the audit log."""
    try:
        with get_pool().connection() as conn:
            conn.execute(
                "INSERT INTO audit_log (incident_id, actor, event, detail) "
                "VALUES (%s::uuid, %s, %s, %s::jsonb)",
                (incident_id, step.get("agent", "system"),
                 "step:" + step.get("agent", "unknown"),
                 json.dumps(step, default=str)),
            )
    except Exception:  # noqa: BLE001 - audit must never break the graph
        pass
