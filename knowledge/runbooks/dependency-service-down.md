---
tags: [dependency, downstream, unavailable, 5xx]
---
# Dependency service down

## Symptoms
Upstream service returns 5xx/timeouts while itself healthy; errors mention
connection refused/unavailable to a downstream service name; errors appear
on a DIFFERENT service than the broken one.

## How to confirm
- Error patterns in upstream logs: "connection refused", "unavailable",
  "deadline exceeded" naming the downstream.
- Downstream deployment: 0 available replicas or all pods NotReady/CrashLoop.
- `deployment_replicas_available` for the downstream is 0.

## Likely causes
- Downstream scaled to zero or crashed (its own incident).
- Downstream Service selector/endpoints broken after a change.

## Remediation
- Treat the DOWNSTREAM service as the incident: apply its specific runbook
  (crash loop, probe failure, ...).
- If downstream was scaled to 0 by mistake: `scale` it back to 1..5.
- Restarting the upstream never helps a down dependency.

## Risks
Fixing the wrong service wastes the window - always confirm which service is
actually unavailable before acting.
