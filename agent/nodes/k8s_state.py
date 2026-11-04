"""Kubernetes state specialist node (wrapper over the shared core)."""

from __future__ import annotations

from agent.nodes import specialist
from agent.state import IncidentState


async def k8s_node(state: IncidentState) -> dict:
    return await specialist.run_specialist("k8s_agent", state)
