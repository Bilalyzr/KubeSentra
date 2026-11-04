---
tags: [unavailable, replicas, deployment]
---
# Deployment replicas unavailable

## Symptoms
`DeploymentReplicasUnavailable`: available < desired; traffic degraded or
dropped for that service.

## How to confirm
- `deployment_replicas_available` vs desired.
- Pod statuses under the deployment: CrashLoop, Pending, ImagePull or NotReady
  tell the real story - follow THAT runbook.
- Rollout stuck mid-progress (maxSurge/maxUnavailable math).

## Likely causes
Any pod-level failure: crash loop, image pull, probe failure, unschedulable.

## Remediation
Address the underlying pod state (see the matching runbook). Generic options:
- `rollout_undo` if a revision introduced it.
- `scale` up within policy only if pods are healthy but too few.

## Risks
Scaling up unhealthy pods multiplies the problem; confirm pod health first.
