from __future__ import annotations

import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.anyio
async def test_mcp_server_lists_core_tools() -> None:
    server = StdioServerParameters(command=sys.executable, args=["-m", "vivado_mcp.server"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert {
                "vivado_check_installation",
                "vivado_start_session",
                "vivado_run_tcl",
                "vivado_project_summary",
                "vivado_list_sessions",
                "vivado_read_artifact",
                "vivado_help",
            }.issubset(tool_names)


@pytest.mark.anyio
async def test_mcp_server_reads_skill_resource() -> None:
    server = StdioServerParameters(command=sys.executable, args=["-m", "vivado_mcp.server"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            resources = await session.list_resources()
            resource_uris = {str(resource.uri) for resource in resources.resources}
            assert "vivado://skills/index" in resource_uris
            result = await session.read_resource("vivado://skills/index")
            assert "raw-tcl-expert" in result.contents[0].text
