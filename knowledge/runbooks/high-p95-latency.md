---
tags: [latency, p95, slow, slod]
---
# High p95 latency

## Symptoms
`HighP95Latency` fires; requests succeed but slowly; error rate may stay low.

## How to confirm
- Latency quantiles rising for the service; correlate with CPU throttling
  ratio, memory pressure and downstream latency.
- Locks/GC pauses visible as latency spikes without resource pressure.

## Likely causes
- CPU throttling (most common with tight limits).
- Downstream latency added per call.
- Application-level contention (locks, connection pool exhaustion).

## Remediation
- Throttling: `set_resources` raise CPU limit (policy-bounded).
- Downstream: fix that service.
- App-level contention: needs a code fix - report.

## Risks
Raising limits without confirming throttling just consumes node capacity.
