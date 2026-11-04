"""Logs specialist node (wrapper over the shared specialist core)."""

from __future__ import annotations

from agent.nodes import specialist
from agent.state import IncidentState


async def logs_node(state: IncidentState) -> dict:
    return await specialist.run_specialist("logs_agent", state)
