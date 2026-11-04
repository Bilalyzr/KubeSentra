---
tags: [configmap, missing, config, volume]
---
# Missing ConfigMap / mount failure

## Symptoms
Pod fails with CreateContainerConfigError or mount errors; events mention a
ConfigMap that does not exist.

## How to confirm
- Pod status CreateContainerConfigError; events name the missing ConfigMap.
- `get_configmap` for the expected name: not found.

## Likely causes
- ConfigMap removed/renamed while the deployment still references it.
- Deployment rollout references a key that was never created.

## Remediation
- `rollout_undo` to a revision that did not require the missing ConfigMap.
- Creating the ConfigMap is a CI/config change (report; outside allowlist).

## Risks
Undo may not help if the ConfigMap was deleted out-of-band while the old
revision also referenced it - then only re-creating it fixes startup.
