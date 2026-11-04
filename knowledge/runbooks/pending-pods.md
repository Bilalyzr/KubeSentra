---
tags: [pending, scheduling, insufficient, resources]
---
# Pods stuck Pending (unschedulable)

## Symptoms
Pod stays Pending; deployment unavailable; events show scheduling failures.

## How to confirm
- Pod phase Pending, no container status.
- Events: "Insufficient cpu"/"Insufficient memory"/"Insufficient nodes" from
  default-scheduler.
- Node resource metrics show nearly no allocatable headroom.

## Likely causes
- Requests (cpu/memory) exceed what any node can allocate.
- Cluster capacity exhausted by other workloads.
- Taints/affinity rules exclude all nodes (less common).

## Remediation
- If a rollout raised requests too far: `rollout_undo`.
- Else `set_resources` to lower requests back to the working set (within
  policy bounds).
- `scale` another deployment down 1 replica to free capacity is allowed but
  reduces its availability - only with human approval.

## Risks
Lowering requests below real usage risks throttling/OOM later; scaling down
any service reduces its fault tolerance.
