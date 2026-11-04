"""MCP tool loading for agents (langchain-mcp-adapters, stdio transport).

Investigation agents only ever receive the four READ-ONLY servers. The
write server (Phase 7) is deliberately not listed here and is loaded only
inside the executor after human approval.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from langchain_core.tools import BaseTool

ROOT = Path(__file__).resolve().parents[1]

MCP_SERVERS: dict[str, str] = {
    "k8s_read": "mcp_servers.k8s_read.server",
    "prometheus": "mcp_servers.prometheus.server",
    "loki": "mcp_servers.loki.server",
    "knowledge": "mcp_servers.knowledge.server",
}


async def get_tools(servers: list[str] | None = None) -> list[BaseTool]:
    """Start the requested MCP servers and return their tools as LangChain tools."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    selected = servers or list(MCP_SERVERS)
    unknown = set(selected) - set(MCP_SERVERS)
    if unknown:
        raise ValueError(f"unknown MCP servers: {sorted(unknown)}")

    env = dict(os.environ)
    env["K8S_READER_KUBECONFIG"] = str(ROOT / ".secrets/k8s-read.kubeconfig")

    config = {
        name: {
            "command": sys.executable,
            "args": ["-m", MCP_SERVERS[name]],
            "transport": "stdio",
            "env": env,
        }
        for name in selected
    }
    client = MultiServerMCPClient(config)
    return await client.get_tools()
