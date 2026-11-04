---
tags: [readiness, probe, notready, config]
---
# Readiness probe failure (pod Running but NotReady)

## Symptoms
Pod phase Running but ready 0/1; `PodNotReady` fires; service endpoints
exclude the pod so traffic 5xx/falls to remaining replicas.

## How to confirm
- Pod shows 0/1 Running; `kube_pod_status_ready{condition="false"} == 1`.
- `describe_pod`: readiness probe failures ("Unhealthy - probe timed out /
  connection refused") for the pod.
- Deployment revision diff shows a probe port/path change.

## Likely causes
- Probe pointed at wrong port or path (bad rollout or copy-paste).
- Application slow to start and the probe timeout/failureThreshold too
  aggressive.
- App listens only after a dependency is ready and never passes the probe.

## Remediation
- Preferred: `rollout_undo` to the revision with the working probe.
- If the app is merely slow and the probe was recently tightened: undo the
  revision (probe tuning then goes through CI).

## Risks
Undo reverts the full template, including intended changes shipped in the
same revision.
