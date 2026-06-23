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
                "vivado_focus_gui",
                "vivado_run_tcl",
                "vivado_review_tcl",
                "vivado_tcl_command_help",
                "vivado_project_summary",
                "vivado_capture_state",
                "vivado_state_diff",
                "vivado_analyze_reports",
                "vivado_hw_discover",
                "vivado_nonproject_read_sources",
                "vivado_nonproject_synth_design",
                "vivado_nonproject_opt_design",
                "vivado_nonproject_place_design",
                "vivado_nonproject_route_design",
                "vivado_simulation_audit",
                "vivado_prepare_simulation",
                "vivado_launch_simulation",
                "vivado_analyze_xsim_logs",
                "vivado_ip_catalog_search",
                "vivado_create_ip",
                "vivado_list_ips",
                "vivado_describe_ip",
                "vivado_ip_upgrade_check",
                "vivado_upgrade_ip",
                "vivado_generate_ip_outputs",
                "vivado_add_sources",
                "vivado_remove_sources",
                "vivado_set_file_properties",
                "vivado_set_top",
                "vivado_list_filesets",
                "vivado_create_fileset",
                "vivado_describe_fileset",
                "vivado_constraint_diagnostics",
                "vivado_source_audit",
                "vivado_xdc_order_check",
                "vivado_fileset_apply",
                "vivado_constraint_set_apply",
                "vivado_bd_open_or_create",
                "vivado_bd_summary",
                "vivado_bd_apply",
                "vivado_list_sessions",
                "vivado_read_artifact",
                "vivado_help",
                "vivado_list_official_references",
                "vivado_get_official_reference",
                "vivado_official_reference_guide",
                "vivado_search_official_docs",
                "vivado_search_xilinx_docs",
                "vivado_download_xilinx_pdf",
                "vivado_sync_official_docs",
                "vivado_clean_bad_pdfs",
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
            assert "vivado://official-docs/index" in resource_uris
            result = await session.read_resource("vivado://skills/index")
            assert "raw-tcl-expert" in result.contents[0].text

            docs_result = await session.read_resource("vivado://official-docs/index")
            assert "UG835" in docs_result.contents[0].text
