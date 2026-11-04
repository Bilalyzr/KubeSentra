---
tags: [network, partition, unreachable, chaos]
---
# Network partition

## Symptoms
One service suddenly cannot reach another at all (connection refused/timeout
on every call); both sides healthy in isolation; errors are sharply
binary - all-or-nothing per peer.

## How to confirm
- Upstream logs: 100% failure calling one specific downstream name.
- Downstream itself responds to its own probes and serves other callers.
- A chaos-mesh NetworkChaos partition experiment exists in the namespace.

## Likely causes
- Chaos experiment partitioning the two services.
- NetworkPolicy change denying the flow (config incident).

## Remediation
- Remove the chaos experiment (outside the allowlist; report it).
- For a NetworkPolicy regression: `rollout_undo` on the service whose policy
  template changed, if policies ship in its manifests.

## Risks
Minimal - this is a diagnose-and-report case; wrong restarts just add noise.
