---
tags: [5xx, errors, http, latency]
---
# High HTTP 5xx error rate

## Symptoms
`HighErrorRate` fires for a service; clients receive 5xx; error rate above
the alert threshold (e.g. > 5%).

## How to confirm
- Error-rate metrics/counts by status class for the service.
- Error log patterns: which downstream or code path is failing.
- Correlate with restarts, rollouts or dependency incidents at the same time.

## Likely causes
- A dependency being down/unstable (see dependency runbook).
- Bad rollout shipping a bug (see bad-rollout runbook).
- Overload: throttling or saturation (see cpu-throttling / resources).

## Remediation
Treat the PRIMARY cause, not the symptom:
- Dependency down -> fix that service.
- Bad rollout -> `rollout_undo`.
- Overload -> `set_resources` / `scale` within policy.

## Risks
Acting on the reporting service when the cause is downstream wastes the
recovery window and adds churn.
