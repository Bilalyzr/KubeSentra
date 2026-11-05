"""Thin API client for the dashboard. Every control goes through the REAL
backend - the dashboard never reads the database directly and never
simulates a response.
"""

from __future__ import annotations

import os

import httpx

DEFAULT_BASE = os.environ.get("DASHBOARD_API_URL",
                              "http://127.0.0.1:8547")


def _base() -> str:
    return os.environ.get("DASHBOARD_API_URL", DEFAULT_BASE)


def _token() -> str:
    from common.config import get_settings

    return get_settings().approval_token


def get_json(path: str, params: dict | None = None, timeout: float = 15.0):
    with httpx.Client(base_url=_base(), timeout=timeout) as client:
        resp = client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


def post_decision(incident_id: str, status: str, plan: list | None,
                  approver: str) -> tuple[int, dict]:
    """Submit an approval decision. Returns (http_status, body) - errors are
    surfaced to the UI verbatim, never swallowed or faked."""
    body = {"status": status, "approver": approver}
    if plan is not None:
        body["plan"] = plan
    with httpx.Client(base_url=_base(), timeout=600.0) as client:
        resp = client.post(f"/incidents/{incident_id}/decision",
                           json=body,
                           headers={"X-Approval-Token": _token()})
        try:
            parsed = resp.json()
        except ValueError:
            parsed = {"detail": resp.text}
        return resp.status_code, parsed


# --- typed helpers used by pages -----------------------------------------------


def incidents(status: str | None = None, limit: int = 100) -> list[dict]:
    return get_json("/incidents",
                    {"status": status, "limit": limit} if status
                    else {"limit": limit}).get("incidents", [])


def incident(incident_id: str) -> dict:
    return get_json(f"/incidents/{incident_id}")


def timeline(incident_id: str) -> list[dict]:
    return get_json(f"/incidents/{incident_id}/timeline").get("events", [])


def evidence(incident_id: str) -> list[dict]:
    return get_json(f"/incidents/{incident_id}/evidence").get("evidence", [])


def postmortem(incident_id: str) -> dict:
    return get_json(f"/incidents/{incident_id}/postmortem")


def stats() -> dict:
    return get_json("/stats")


def runbooks() -> list[dict]:
    return get_json("/runbooks").get("runbooks", [])


def runbook_search(query: str) -> list[dict]:
    # generous timeout: first search may pay the embedding model cold-load
    return get_json("/runbooks/search", {"q": query},
                    timeout=180.0).get("results", [])


def approval_payload(incident_row: dict) -> dict:
    """Extract {plan, dry_run, hypotheses, timeline} from the incident row."""
    actions = incident_row.get("actions") or {}
    if isinstance(actions, dict):
        return actions.get("approval_payload", {}) or {}
    return {}
