---
tags: [node, capacity, memory, eviction]
---
# Insufficient node resources / memory pressure

## Symptoms
Multiple pods across services show scheduling/eviction pressure; node memory
available low; possibly node `MemoryPressure` condition.

## How to confirm
- `node_memory_available_ratio` low (< 0.1 critical).
- Events: evictions, scheduling denials across namespaces of the app.
- Several services' usage grew simultaneously (e.g. after traffic spike).

## Likely causes
- Cumulative over-requesting across services (requests far above usage).
- Traffic growth without capacity additions.
- A memory leak somewhere inflating steady-state usage.

## Remediation
- `scale` a non-critical service down within policy (short-term headroom).
- `set_resources` to right-size an over-requested service.
- Adding nodes is outside the allowlist - report for human action.

## Risks
Every scale-down trades availability for capacity; prefer right-sizing first.
