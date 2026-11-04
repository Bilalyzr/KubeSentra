---
tags: [env, config, configmap, regression]
---
# Incorrect environment variables / config

## Symptoms
Service starts but misbehaves deterministically: calls the wrong address,
feature flags inverted, empty configuration errors; began with a rollout.

## How to confirm
- `diff_rollout_revisions`: env var NAME set changed between revisions
  (values are redacted - names changing is the signal).
- Logs show the bad value or its downstream effect (refused connections to a
  wrong host, "missing required config").
- `get_configmap` shows keys present/absent (values redacted).

## Likely causes
- Env var renamed/removed/wired to the wrong key in a new revision.
- ConfigMap key renamed without updating the deployment.

## Remediation
- Preferred: `rollout_undo` to the last known-good revision.
- After the correct config lands via CI, no restart is needed - the rollout
  itself replaces pods.

## Risks
Standard undo caveat: reverts all template changes in that revision.
