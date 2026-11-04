---
tags: [oomkilled, memory, restarts, resource]
---
# OOMKilled / memory limit too low

## Symptoms
Pod restarts repeatedly with short uptimes; container last state shows
`OOMKilled` with exit code 137; alert `PodRestarting` fires; service may drop
requests during each restart.

## How to confirm
- `describe_pod`: Last State Terminated reason=OOMKilled, exit code 137.
- Metrics: memory working set at or near the container limit
  (`memory_vs_limit` template close to or above 1.0).
- Events: Killing (OOMKilled) messages for the pod.

## Likely causes
- Memory limit set below the service's real working set (bad resource spec).
- A new revision raised memory usage (more cache, bigger payloads) without
  raising the limit.
- Memory leak slowly exceeding the limit.

## Remediation
- Preferred: `set_resources` to raise the memory limit to a healthy multiple
  of the observed working set (never more than 2x the current limit per
  policy).
- If a recent rollout caused it: `rollout_undo` to the previous revision.
- Temporary relief: `rollout_restart` (only helps if usage was transient).

## Risks
Raising limits consumes node memory - check node headroom first. Rolling back
also reverts any good changes in the same revision. Restarts cause brief
connection drops.
