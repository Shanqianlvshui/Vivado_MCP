from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from . import __version__
from .help_skills import get_skill, help_topic, list_skills, skills_index, suggest_next_steps
from .session import VivadoSessionManager
from .vivado_locator import check_vivado

mcp = FastMCP("vivado-mcp")
manager = VivadoSessionManager(default_workspace=Path(os.environ.get("VIVADO_MCP_WORKSPACE", Path.cwd())).resolve())


@mcp.tool()
def vivado_check_installation(vivado_path: str | None = None) -> dict[str, object]:
    """Find Vivado and return its version."""
    try:
        installation = check_vivado(vivado_path)
        return {
            "ok": True,
            "vivado_path": str(installation.executable),
            "version": installation.version,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


@mcp.tool()
def vivado_start_session(
    vivado_path: str | None = None,
    workspace_dir: str | None = None,
    open_gui: bool = True,
    capability_profile: Literal["safe", "trusted-local", "unrestricted"] = "trusted-local",
    startup_timeout_seconds: int = 45,
    gui_wait_seconds: int = 20,
    activate_gui: bool = False,
) -> dict[str, object]:
    """Start a managed Vivado Tcl session, optionally opening and verifying the GUI."""
    return manager.start_session(
        vivado_path=vivado_path,
        workspace_dir=workspace_dir,
        open_gui=open_gui,
        capability_profile=capability_profile,
        startup_timeout_seconds=startup_timeout_seconds,
        gui_wait_seconds=gui_wait_seconds,
        activate_gui=activate_gui,
    )


@mcp.tool()
def vivado_session_state(session_ref: str) -> dict[str, object]:
    """Return current bridge/process state for a managed Vivado session."""
    return manager.session_state(session_ref)


@mcp.tool()
def vivado_list_sessions() -> dict[str, object]:
    """List active managed Vivado sessions."""
    return manager.list_sessions()


@mcp.tool()
def vivado_stop_session(session_ref: str, force: bool = False, timeout_seconds: int = 20) -> dict[str, object]:
    """Stop a managed Vivado session."""
    return manager.stop_session(session_ref, force=force, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_focus_gui(session_ref: str, timeout_seconds: int = 10) -> dict[str, object]:
    """Bring the managed Vivado GUI window to the foreground when it can be found."""
    return manager.focus_gui(session_ref, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_run_tcl(
    session_ref: str,
    tcl: str,
    timeout_seconds: int = 60,
    expect_destructive: bool = False,
) -> dict[str, object]:
    """Run raw Tcl in a managed session. Requires trusted-local or unrestricted profile."""
    return manager.run_tcl(
        session_ref=session_ref,
        tcl=tcl,
        timeout_seconds=timeout_seconds,
        expect_destructive=expect_destructive,
    )


@mcp.tool()
def vivado_source_tcl(
    session_ref: str,
    script_path: str,
    tclargs: list[str] | None = None,
    timeout_seconds: int = 120,
    expect_destructive: bool = False,
) -> dict[str, object]:
    """Source a Tcl file in a managed session. Requires trusted-local or unrestricted profile."""
    return manager.source_tcl(
        session_ref=session_ref,
        script_path=script_path,
        tclargs=tclargs,
        timeout_seconds=timeout_seconds,
        expect_destructive=expect_destructive,
    )


@mcp.tool()
def vivado_create_project(
    session_ref: str,
    project_name: str,
    project_dir: str,
    part: str | None = None,
    board_part: str | None = None,
    force: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Create a Vivado Project Mode project in the managed session."""
    return manager.create_project(
        session_ref=session_ref,
        project_name=project_name,
        project_dir=project_dir,
        part=part,
        board_part=board_part,
        force=force,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_open_project(
    session_ref: str,
    project_path: str,
    timeout_seconds: int = 120,
    gui_wait_seconds: int = 20,
    focus_gui: bool = False,
) -> dict[str, object]:
    """Open an existing Vivado project in the managed session and refresh GUI visibility state."""
    return manager.open_project(
        session_ref=session_ref,
        project_path=project_path,
        timeout_seconds=timeout_seconds,
        gui_wait_seconds=gui_wait_seconds,
        focus_gui=focus_gui,
    )


@mcp.tool()
def vivado_add_sources(
    session_ref: str,
    sources: list[str] | None = None,
    constraints: list[str] | None = None,
    top: str | None = None,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Add RTL/source and constraint files to the current Vivado project."""
    return manager.add_sources(
        session_ref=session_ref,
        sources=sources,
        constraints=constraints,
        top=top,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_run_synthesis(
    session_ref: str,
    run_name: str = "synth_1",
    jobs: int | None = None,
    timeout_seconds: int = 3600,
) -> dict[str, object]:
    """Launch and wait for a Vivado synthesis run."""
    return manager.launch_run(session_ref=session_ref, run_name=run_name, jobs=jobs, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_run_implementation(
    session_ref: str,
    run_name: str = "impl_1",
    jobs: int | None = None,
    timeout_seconds: int = 7200,
) -> dict[str, object]:
    """Launch and wait for a Vivado implementation run."""
    return manager.launch_run(session_ref=session_ref, run_name=run_name, jobs=jobs, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_generate_bitstream(
    session_ref: str,
    run_name: str = "impl_1",
    jobs: int | None = None,
    timeout_seconds: int = 7200,
) -> dict[str, object]:
    """Run implementation through write_bitstream."""
    return manager.launch_run(
        session_ref=session_ref,
        run_name=run_name,
        jobs=jobs,
        to_step="write_bitstream",
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_report(
    session_ref: str,
    report_type: Literal["timing_summary", "timing_paths", "utilization", "drc", "power", "clock_interaction", "messages"],
    output_name: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, object]:
    """Generate a Vivado report in the managed session."""
    return manager.report(
        session_ref=session_ref,
        report_type=report_type,
        output_name=output_name,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_project_summary(session_ref: str, timeout_seconds: int = 60) -> dict[str, object]:
    """Return structured information about the current Vivado project, files, runs, IP, and block designs."""
    return manager.project_summary(session_ref=session_ref, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_list_artifacts(session_ref: str) -> dict[str, object]:
    """List files produced in a managed session directory."""
    return manager.list_artifacts(session_ref)


@mcp.tool()
def vivado_read_artifact(session_ref: str, artifact_id: str, max_chars: int = 20000) -> dict[str, object]:
    """Read a text artifact from a managed session."""
    return manager.read_artifact(session_ref, artifact_id, max_chars=max_chars)


@mcp.tool()
def vivado_help(topic: str | None = None) -> dict[str, object]:
    """Return concise help for a Vivado MCP topic."""
    return help_topic(topic)


@mcp.tool()
def vivado_list_skills(query: str | None = None) -> dict[str, object]:
    """List built-in Vivado MCP skills."""
    return {"skills": list_skills(query)}


@mcp.tool()
def vivado_get_skill(skill_id: str) -> dict[str, str]:
    """Return one built-in Vivado MCP skill document."""
    return get_skill(skill_id)


@mcp.tool()
def vivado_suggest_next_steps(
    goal: str | None = None,
    last_error: str | None = None,
    session_ref: str | None = None,
    project_ref: str | None = None,
) -> dict[str, object]:
    """Suggest next MCP operations from current context."""
    return suggest_next_steps(
        goal=goal,
        last_error=last_error,
        has_session=session_ref is not None,
        has_project=project_ref is not None,
    )


@mcp.resource("vivado://help/index", mime_type="text/markdown")
def help_index() -> str:
    """Vivado MCP help index."""
    help_result = help_topic("index")
    tools = "\n".join(f"- `{tool}`" for tool in help_result["recommended_tools"])
    resources = "\n".join(f"- `{uri}`" for uri in help_result["related_resources"])
    return (
        "# Vivado MCP Help\n\n"
        f"{help_result['summary']}\n\n"
        "## Recommended Tools\n\n"
        f"{tools}\n\n"
        "## Related Resources\n\n"
        f"{resources}\n"
    )


@mcp.resource("vivado://skills/index", mime_type="text/markdown")
def resource_skills_index() -> str:
    """Built-in Vivado MCP skills index."""
    return skills_index()


@mcp.resource("vivado://skills/{skill_id}", mime_type="text/markdown")
def resource_skill(skill_id: str) -> str:
    """Built-in Vivado MCP skill document."""
    return get_skill(skill_id)["body"]


@mcp.resource("vivado://sessions/{session_ref}/artifacts/{artifact_id}", mime_type="text/plain")
def resource_artifact(session_ref: str, artifact_id: str) -> str:
    """Read a Vivado MCP session artifact."""
    return str(manager.read_artifact(session_ref, artifact_id)["text"])


@mcp.resource("vivado://server/info", mime_type="application/json")
def server_info() -> dict[str, object]:
    """Vivado MCP server metadata."""
    return {
        "name": "vivado-mcp",
        "version": __version__,
        "default_workspace": str(manager.default_workspace),
        "allowed_roots": [str(root) for root in manager.path_policy.roots],
    }


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
