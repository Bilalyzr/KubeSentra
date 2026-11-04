---
tags: [rollout, change, revision, config]
---
# Bad rollout (regression shipped in a new revision)

## Symptoms
Errors/latency/restarts begin immediately after a deployment change;
`HighErrorRate`, `PodRestarting` or `PodNotReady` cluster around the rollout
time; previous revision was healthy.

## How to confirm
- `get_rollout_history`: a new revision exists.
- `diff_rollout_revisions` (latest vs previous): image, command, env var
  names, limits or probe changes.
- Metrics/logs degrade exactly from the rollout timestamp.

## Likely causes
- Bad image build, wrong env wiring, bad config flag or probe change shipped
  together.

## Remediation
- Preferred: `rollout_undo` to the previous revision (fastest safe recovery).
- For wide breakage plus a stuck template: `rollout_restart` after undo if
  pods need recycling.

## Risks
Undo also reverts intended changes in that revision; the fixed forward roll
must be re-shipped via CI afterwards.
