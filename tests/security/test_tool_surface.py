"""SEC-7: the investigation tool surface cannot reach write tools.

- agent/tools.py (loaded by ALL investigation agents) never lists k8s_write
- the write server exposes exactly five allowlisted tools, no shell/exec
- MCP servers loaded per specialist are scoped to their own read-only server
"""

import asyncio
import inspect

import agent.tools
from mcp_servers.k8s_write import server as write_server


def test_investigation_never_loads_the_write_server():
    assert "k8s_write" not in agent.tools.MCP_SERVERS
    assert "k8s_write" not in inspect.getsource(agent.tools)


def test_write_server_exposes_exactly_five_tools():
    async def tools():
        return sorted(t.name for t in await write_server.mcp.list_tools())
    names = asyncio.run(tools())
    assert names == ["delete_pod", "rollout_restart", "rollout_undo",
                     "scale_deployment", "set_resources"]


def test_no_shell_or_exec_tool_anywhere():
    async def tools():
        return [t.name for t in await write_server.mcp.list_tools()]
    names = asyncio.run(tools())
    forbidden = ("shell", "exec", "run_command", "kubectl", "apply", "patch_"
                 "arbitrary")
    for name in names:
        for word in forbidden:
            assert word not in name, name


def test_specialists_only_see_their_own_server():
    from agent.nodes.specialist import SPECIALISTS

    for agent_name, spec in SPECIALISTS.items():
        assert spec["servers"] != ["k8s_write"], agent_name
        assert len(spec["servers"]) == 1, f"{agent_name} scoped to one server"
