---
tags: [dns, resolution, name, network]
---
# DNS resolution failure

## Symptoms
Errors like "no such host" / "Name or service not known" for service names;
intermittent or total; requests fail before any connection attempt.

## How to confirm
- Log patterns: "lookup <service>.<ns>.svc.cluster.local: no such host".
- The target service EXISTS and its name is spelled correctly.
- A chaos-mesh DNSChaos experiment may be active.

## Likely causes
- Injected DNS fault (experiment).
- CoreDNS overload (cluster-level).
- Typo in a newly configured service address (config regression).

## Remediation
- Remove the DNS chaos experiment if present (report it).
- If a rollout introduced a wrong address env var: `rollout_undo` on that
  service.
- Restarting the failing client does not fix DNS.

## Risks
Low; mostly a report-and-remove case.
