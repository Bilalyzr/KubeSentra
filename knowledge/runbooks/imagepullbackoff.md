---
tags: [imagepullbackoff, image, registry, scheduling]
---
# ImagePullBackOff / ErrImagePull

## Symptoms
New pod stuck in `ImagePullBackOff`; never becomes ready; deployment
unavailable replicas > 0; pod events show registry errors.

## How to confirm
- Pod status ImagePullBackOff; `container_waiting_reason` shows
  ImagePullBackOff.
- Events: "Failed to pull image ... not found" / "unauthorized" / "back-off
  pulling image".

## Likely causes
- Image tag typo or tag that does not exist in the registry.
- Registry rate limit or authentication missing (imagePullSecrets).
- Deleted image / wrong registry path in a new rollout.

## Remediation
- If the bad image came from a rollout: `rollout_undo` to the revision with
  the working image.
- Correcting the image itself is done by the deployment pipeline (outside the
  agent allowlist); after fixing, `rollout_restart` is unnecessary - the
  ReplicaSet controller retries pulls automatically.

## Risks
Undo loses other template changes in the same revision. No cluster-side
action can make a nonexistent image pullable.
