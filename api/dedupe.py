"""Alert deduplication and incident grouping (implementation doc 10.1).

A repeated alert for the same fingerprint (alertname + namespace + derived
service) within the configured window attaches to the existing open incident
instead of creating a duplicate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from psycopg.types.json import Json

from api.schemas.alerts import Alert
from common.config import get_settings
from database.connection import get_pool


def service_from_labels(labels: dict[str, str]) -> str:
    """Derive the affected service from alert labels.

    Preference: the pod name (with ReplicaSet hash suffix stripped), then an
    explicit deployment label, then the service label. The pod wins because
    kube-state-metrics stamps its own `service` label onto every alert it
    emits (e.g. service=monitoring-kube-state-metrics).
    """
    pod = labels.get("pod", "")
    if pod:
        parts = pod.rsplit("-", 2)
        # modern ReplicaSet hashes are 10 chars, legacy pod-template-hash 5
        if len(parts) == 3 and 4 <= len(parts[1]) <= 12:
            return parts[0]
        return pod
    if labels.get("deployment"):
        return labels["deployment"]
    if labels.get("service"):
        return labels["service"]
    return "unknown"


def alert_fingerprint(alert: Alert) -> str:
    labels = alert.labels
    return "|".join([
        labels.get("alertname", "unknown"),
        labels.get("namespace", ""),
        service_from_labels(labels),
    ])


def open_or_attach_incident(alert: Alert) -> tuple[uuid.UUID, bool]:
    """Return (incident_id, is_new). Attaches to a matching open incident
    within the dedupe window, otherwise creates one."""
    fingerprint = alert_fingerprint(alert)
    window = get_settings().dedupe_window_minutes
    labels = alert.labels
    now = datetime.now(timezone.utc).isoformat()

    with get_pool().connection() as conn:
        existing = conn.execute(
            """
            SELECT id FROM incidents
            WHERE alert_labels->>'fingerprint' = %s
              AND status <> 'resolved'
              AND created_at > now() - (%s::int * interval '1 minute')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (fingerprint, window),
        ).fetchone()

        if existing is not None:
            conn.execute(
                """
                UPDATE incidents
                SET alert_labels = jsonb_set(
                        alert_labels, '{occurrences}',
                        to_jsonb(COALESCE((alert_labels->>'occurrences')::int, 1) + 1))
                WHERE id = %s
                """,
                (existing[0],),
            )
            return existing[0], False

        incident_id = uuid.uuid4()
        conn.execute(
            """
            INSERT INTO incidents (id, alert_name, namespace, service, symptoms,
                                   status, alert_labels)
            VALUES (%s, %s, %s, %s, %s, 'open',
                    %s::jsonb)
            """,
            (
                incident_id,
                labels.get("alertname", "unknown"),
                labels.get("namespace", ""),
                service_from_labels(labels),
                alert.annotations.get("summary") or "",
                Json({"fingerprint": fingerprint, "labels": labels,
                      "annotations": alert.annotations,
                      "occurrences": 1, "first_seen": now}),
            ),
        )
        return incident_id, True
