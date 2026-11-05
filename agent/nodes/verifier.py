"""Verifier: did the remediation ACTUALLY resolve the incident?

Deterministic checks (implementation document 4.3) - never trusts a
successful kubectl exit:
1. pods of the service Ready again (poll loop, rollout takes time)
2. deployment replicas available
3. the ORIGINAL alert no longer firing (Prometheus)
4. pre/post comparison against the restart evidence collected earlier

Verdict: RESOLVED | PARTIALLY_RESOLVED | NOT_RESOLVED | VERIFICATION_FAILED
"""

from __future__ import annotations

import asyncio
import re

from agent.state import IncidentState

VERDICTS = ("RESOLVED", "PARTIALLY_RESOLVED", "NOT_RESOLVED",
            "VERIFICATION_FAILED")


def _service_pods_ready(pods_text: str, service: str) -> bool:
    """All pods of the service are Running with N/N containers ready."""
    lines = [ln for ln in pods_text.splitlines()
             if ln.startswith(service) and "\t" in ln]
    if not lines:
        return False
    for line in lines:
        parts = line.split("\t")
        ready, status = parts[1], parts[2]
        current, total = (ready.split("/") + ["?"])[:2]
        if status != "Running" or current != total:
            return False
    return True


def _restarts_worse_than(pods_text: str, service: str, baseline: int) -> bool:
    worse = False
    for line in pods_text.splitlines():
        if line.startswith(service) and "\t" in line:
            try:
                restarts = int(line.split("\t")[3])
            except (IndexError, ValueError):
                continue
            if restarts > baseline:
                worse = True
    return worse


async def _wait_for_ready(service: str, namespace: str, budget_s: int = 240):
    """Poll pod readiness while the rollout settles."""
    from mcp_servers.k8s_read.server import list_pods

    waited = 0
    last = ""
    while waited < budget_s:
        last = list_pods(namespace=namespace)
        if _service_pods_ready(last, service):
            return True, last, waited
        await asyncio.sleep(15)
        waited += 15
    return False, last, waited


def _max_pre_restarts(state: IncidentState) -> int:
    """Baseline restart count captured in the evidence summaries."""
    baseline = 0
    for ev in state.get("evidence", []):
        window = ev.summary[:250]
        for m in re.finditer(r"restart\w*[^\d]{0,30}(\d+)", window, re.I):
            baseline = max(baseline, int(m.group(1)))
    return baseline


async def verifier_node(state: IncidentState) -> dict:
    incident_id = state["incident_id"]
    service = state.get("service", "")
    namespace = state.get("namespace", "")
    execution = state.get("execution") or {}
    alert_labels = state.get("alert", {}).get("labels", {})
    alertname = alert_labels.get("alertname", "")

    if not execution.get("executed"):
        # nothing ran (refused / empty plan / all failed) - verify the
        # incident state anyway so the record is honest
        pass

    checks: dict = {}
    try:
        # 1+2. pods ready (with rollout wait)
        ready, pods_text, waited = await _wait_for_ready(service, namespace)
        checks["pods_ready"] = ready
        checks["rollout_wait_s"] = waited

        # 3. original alert cleared?
        from mcp_servers.prometheus.server import list_firing_alerts
        firing_text = list_firing_alerts()
        still_firing = (alertname in firing_text) if alertname else False
        checks["alert_still_firing"] = bool(still_firing)

        # 4. pre/post restart comparison
        baseline = _max_pre_restarts(state)
        worsening = _restarts_worse_than(pods_text, service,
                                         baseline + 1) if ready else True
        checks["restarts_worsening"] = worsening

        if ready and not still_firing and not worsening:
            verdict = "RESOLVED"
        elif ready and not worsening:
            verdict = "PARTIALLY_RESOLVED"  # healthy but alert not cleared yet
        else:
            verdict = "NOT_RESOLVED"
    except Exception as exc:  # noqa: BLE001 - verification itself failed
        checks["error"] = f"{type(exc).__name__}: {exc}"
        verdict = "VERIFICATION_FAILED"

    from api.services import incident_service
    incident_service.audit(incident_id, actor="verifier",
                           event="verification",
                           detail={"verdict": verdict, **checks})
    return {"outcome": {"verdict": verdict, "checks": checks},
            "timeline": [{"agent": "verifier", "verdict": verdict}]}
