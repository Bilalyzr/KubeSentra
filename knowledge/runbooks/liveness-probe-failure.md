---
tags: [liveness, probe, restarts, config]
---
# Liveness probe failure (killer restart loop)

## Symptoms
Container restarted by the kubelet with reason "Killing" + probe failure
events (NOT OOMKilled); restarts climb while memory looks healthy; brief
outages each restart.

## How to confirm
- Events: "Unhealthy - Liveness probe failed" followed by "Killing".
- `describe_pod`: restarts with last state reason=Error, exit 137 but memory
  well under limit; logs usually healthy up to the kill.

## Likely causes
- Probe timeout too small for peak response latency.
- Probe endpoint genuinely hangs (deadlock) after some uptime.
- Probe port changed by a rollout while the app listens on the old one.

## Remediation
- If caused by a rollout: `rollout_undo`.
- For a hung process (pre-fix relief): `rollout_restart` restores service
  temporarily; the hang needs a code fix.

## Risks
Restarting wipes in-flight work; if the app hangs under load it may hang
again quickly.
