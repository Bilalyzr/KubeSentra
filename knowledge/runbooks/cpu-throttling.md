---
tags: [cpu, throttling, resource, latency]
---
# CPU throttling / CPU limit too low

## Symptoms
High p95 latency with low average CPU usage; `CPUThrottlingHigh`;
`HighP95Latency` may fire; app "slow but alive".

## How to confirm
- `cpu_throttling_ratio` template: throttled-periods ratio high (> 0.2 is
  bad).
- `cpu_usage` near `cpu_limit` for the pod.
- `describe_pod`: CPU limit far below the service's normal burst.

## Likely causes
- CPU limit set below the service's burst need.
- New revision added CPU-heavy work (serialization, crypto) under the same
  limit.
- Noisy neighbour concentrating load.

## Remediation
- Preferred: `set_resources` to raise the CPU limit (within policy bounds).
- If a rollout caused it: `rollout_undo`.

## Risks
Higher CPU limits can saturate the node at peak; check node headroom
(`node_load1`, available memory) before raising.
