---
tags: [network, latency, slow, timeout]
---
# Network latency between services

## Symptoms
p95/p99 latency up across calls that cross one hop; timeouts and retry
storms; CPU/memory normal everywhere; `HighP95Latency` fires.

## How to confirm
- `p95_latency` rising for the affected job; error log patterns show
  "deadline exceeded"/timeout on calls to a specific peer.
- No pod restarts, no CPU throttling, no memory pressure.

## Likely causes
- Injected/real network delay on the path (e.g. chaos experiment).
- Downstream saturation appearing as queueing delay.
- DNS slowness amplifying every call.

## Remediation
- If a chaos experiment is active (check chaos-mesh resources), remove the
  experiment - no allowlisted action fixes synthetic delay.
- If downstream saturation: address that service's resource runbook.
- `rollout_restart` of the caller does NOT help; avoid it.

## Risks
None from waiting; acting on the wrong service adds churn to a healthy tier.
