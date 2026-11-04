---
tags: [crashloopbackoff, crash, restarts, application]
---
# CrashLoopBackOff

## Symptoms
Container exits non-zero repeatedly; pod stuck cycling
Running -> CrashLoopBackOff; `PodRestarting` / `DeploymentReplicasUnavailable`
alerts fire; endpoint flaps in and out of readiness.

## How to confirm
- Pod status shows CrashLoopBackOff; restart count climbing.
- `get_pod_logs` with `previous=true` for the crashing instance.
- `describe_pod`: last state reason=Error with a specific exit code.

## Likely causes
- Application bug or panic at startup (bad code path, nil dereference).
- Misconfigured command/entrypoint (binary missing -> "exec format error").
- Missing ConfigMap/Secret or invalid env var causing fatal startup error.
- Dependency unavailable at boot and no retry (app exits instead).

## Remediation
- If a recent rollout introduced it: `rollout_undo` to the previous revision.
- If config-driven and the config was fixed out-of-band: `rollout_restart`
  to recycle pods onto the fixed config.
- `delete_pod` only to force one fast retry after fixing the cause.

## Risks
Undo reverts all changes in that revision, wanted or not. Deleting a pod
without fixing the cause just produces another crash cycle.
