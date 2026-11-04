---
tags: [replicas, availability, single, scale]
---
# Single replica availability risk

## Symptoms
Any pod failure of a service with replicas=1 causes full outage of that
service; recovery requires pod reschedule.

## How to confirm
- `deployment_replicas_available` shows desired=1.
- Incident history shows the same service failing repeatedly alone.

## Likely causes
- Deployment specced with one replica (cost-cutting or default).

## Remediation
- `scale` to 2..3 replicas within policy for rolling resilience.
- Fixing the underlying pod failure still applies (see its runbook).

## Risks
More replicas consume node capacity; check headroom first.
