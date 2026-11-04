"""Optional Langfuse tracing (implementation document section 12).

Tracing is enabled only when LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are
configured in the environment; without keys every decorator is a no-op, so
the system runs fully offline.
"""

from __future__ import annotations

import os


def _enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY")
                and os.environ.get("LANGFUSE_SECRET_KEY"))


def traced(name: str):
    """Decorator: langfuse.observe when configured, identity otherwise."""
    def decorator(fn):
        if _enabled():
            try:
                from langfuse import observe
                return observe(name=name)(fn)
            except Exception:  # noqa: BLE001 - tracing must never break runs
                return fn
        return fn
    return decorator
