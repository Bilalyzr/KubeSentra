---
tags: [memory, leak, growth, oomkilled]
---
# Memory leak (steady growth to OOM)

## Symptoms
Memory working set climbs linearly over hours/days until OOMKilled; after
restart the climb repeats; limit was fine for months.

## How to confirm
- `memory_usage` / `memory_vs_limit` trend rising monotonically, not
  correlated with traffic.
- Repeated OOMKilled exits at increasing intervals since last restart.

## Likely causes
- Unbounded cache/slice growth, leaked goroutines/threads, retained
  references (code defect).

## Remediation
- `rollout_restart` as scheduled relief (buys one memory-life per restart).
- `set_resources` to raise the limit buys time (policy-bounded, max 2x).
- Real fix is a code change - report with the growth evidence.

## Risks
Restarts drop in-flight work; raising limits only delays the OOM.
