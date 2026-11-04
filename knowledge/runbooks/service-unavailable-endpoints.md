---
tags: [service, endpoints, selector, unreachable]
---
# Service has no endpoints (selector mismatch)

## Symptoms
Service ClusterIP resolves but every call gets connection refused; pods are
Running and Ready; endpoints list for the Service is empty.

## How to confirm
- Pods healthy but the Service's Endpoints object lists no addresses.
- Service selector labels do not match the pods' labels.

## Likely causes
- Deployment rollout changed pod labels; Service selector unchanged.
- Service edited to a wrong selector.

## Remediation
- `rollout_undo` restores the previous pod labels so the selector matches
  again.

## Risks
Standard undo caveat on bundled changes.
