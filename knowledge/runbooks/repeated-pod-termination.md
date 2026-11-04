---
tags: [podkill, chaos, termination, restarts]
---
# Repeated pod termination (external killer)

## Symptoms
Pods die with last state reason=Killed at regular intervals; NOT OOMKilled,
no probe failures; a chaos-mesh PodChaos schedule exists.

## How to confirm
- `describe_pod`: last state Terminated reason Killed, exit 137, but memory
  far below limit and no liveness events.
- Chaos-mesh PodChaos/Schedule resources in the namespace.
- Restarts happen at a steady cadence (schedule-like).

## Likely causes
- Chaos experiment killing pods on a schedule.
- Human/automation deleting pods (check audit).

## Remediation
- Remove the chaos experiment (report; outside allowlist).
- No allowlisted action stops an external killer; restarting just feeds it.

## Risks
None from reporting; unnecessary restarts increase disruption.
