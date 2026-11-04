---
tags: [pool, connections, timeout, saturation]
---
# Connection pool / thread exhaustion

## Symptoms
Latency spikes with errors like "pool exhausted", "too many open connections"
or requests queuing behind a fixed worker count; CPU/memory normal.

## How to confirm
- Log patterns: pool/connection limit messages on the service.
- Latency rises while resource metrics stay flat.
- Often follows slower downstream responses (pool held longer).

## Likely causes
- Downstream slowdown holding connections; pool too small for concurrency.
- Connection leak in the app.

## Remediation
- Address the downstream slowness first (its runbook).
- `rollout_restart` clears leaked connections temporarily.
- Pool sizing is configuration via CI - report.

## Risks
Restart drops in-flight requests once.
