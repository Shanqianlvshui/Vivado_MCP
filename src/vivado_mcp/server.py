from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from . import __version__
from .help_skills import get_skill, help_topic, list_skills, skills_index, suggest_next_steps
from .official_docs import (
    get_official_reference,
    list_official_references,
    local_docs_root,
    official_doc_resource,
    official_docs_index,
    official_reference_guide,
    search_official_docs,
)
from .session import VivadoSessionManager
from .tcl_assist import build_tcl_command_help, review_tcl, tcl_command_doc_topic
from .vivado_locator import check_vivado
from .xilinx_docs import clean_bad_pdfs, download_xilinx_pdf, search_xilinx_docs, sync_official_docs

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
    capture_diff: bool = False,
) -> dict[str, object]:
    """Run raw Tcl in a managed session. Requires trusted-local or unrestricted profile."""
    return manager.run_tcl(
        session_ref=session_ref,
        tcl=tcl,
        timeout_seconds=timeout_seconds,
        expect_destructive=expect_destructive,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_source_tcl(
    session_ref: str,
    script_path: str,
    tclargs: list[str] | None = None,
    timeout_seconds: int = 120,
    expect_destructive: bool = False,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Source a Tcl file in a managed session. Requires trusted-local or unrestricted profile."""
    return manager.source_tcl(
        session_ref=session_ref,
        script_path=script_path,
        tclargs=tclargs,
        timeout_seconds=timeout_seconds,
        expect_destructive=expect_destructive,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_review_tcl(tcl: str, intended_goal: str | None = None) -> dict[str, object]:
    """Review Tcl for destructive, hardware-affecting, or high-risk commands before expert execution."""
    return review_tcl(tcl, intended_goal=intended_goal)


@mcp.tool()
def vivado_tcl_command_help(
    command: str,
    session_ref: str | None = None,
    topic: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, object]:
    """Combine official-doc search, MCP coverage guidance, and optional installed Vivado help for one Tcl command."""
    if not command.strip():
        return build_tcl_command_help(command=command)
    doc_topic = topic or tcl_command_doc_topic(command)
    official_search = search_official_docs(
        query=command,
        topic=doc_topic,
        max_results=3,
        context_chars=260,
        timeout_seconds=max(timeout_seconds, 30),
    )
    installed_help: dict[str, object] | None = None
    if session_ref:
        try:
            installed_help = manager.tcl_command_help(
                session_ref=session_ref,
                command=command,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            installed_help = {"ok": False, "error": str(exc)}
    return build_tcl_command_help(
        command=command,
        official_search=official_search,
        installed_help=installed_help,
        official_doc_topic=doc_topic,
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
    sources_fileset: str | None = None,
    include_dirs: list[str] | None = None,
    defines: list[str] | None = None,
    library: str | None = None,
    file_type: str | None = None,
    used_in: list[Literal["synthesis", "simulation", "implementation"]] | None = None,
    processing_order: int | None = None,
    timeout_seconds: int = 120,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Add RTL/source/constraint files to the current Vivado project.

    ``sources_fileset`` lets the caller pick a non-default fileset (e.g.
    ``sources_2`` or a custom RTL fileset). ``include_dirs`` and ``defines``
    are applied at the fileset level so Verilog ``\\`include`` and VHDL
    search paths resolve without listing each directory as a tracked file.
    """
    return manager.add_sources(
        session_ref=session_ref,
        sources=sources,
        constraints=constraints,
        top=top,
        sources_fileset=sources_fileset,
        include_dirs=include_dirs,
        defines=defines,
        library=library,
        file_type=file_type,
        used_in=used_in,
        processing_order=processing_order,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_remove_sources(
    session_ref: str,
    paths: list[str],
    fileset: str | None = None,
    force: bool = False,
    timeout_seconds: int = 120,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Remove files from a Vivado project fileset. Destructive — reviewed upstream."""
    return manager.remove_sources(
        session_ref=session_ref,
        paths=paths,
        fileset=fileset,
        force=force,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_set_file_properties(
    session_ref: str,
    paths: list[str],
    properties: dict[str, object],
    fileset: str | None = None,
    timeout_seconds: int = 60,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Set or update Vivado file properties (FILE_TYPE, LIBRARY, PROCESSING_ORDER, USED_IN_*)."""
    return manager.set_file_properties(
        session_ref=session_ref,
        paths=paths,
        properties=properties,
        fileset=fileset,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_set_top(
    session_ref: str,
    top: str | None = None,
    fileset: str | None = None,
    timeout_seconds: int = 60,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Set or query the Vivado top module for the given fileset.

    Omit ``top`` to read the current value (read-only).
    """
    return manager.set_top(
        session_ref=session_ref,
        top=top,
        fileset=fileset,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_list_filesets(session_ref: str, timeout_seconds: int = 60) -> dict[str, object]:
    """List every fileset in the current Vivado project with type, file count, and top."""
    return manager.list_filesets(session_ref=session_ref, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_create_fileset(
    session_ref: str,
    name: str,
    kind: Literal["constrs", "simulation", "Source", "BlockSrcs"] = "constrs",
    timeout_seconds: int = 120,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Create a new Vivado fileset of the given type (constrs/simulation/Source/BlockSrcs)."""
    return manager.create_fileset(
        session_ref=session_ref,
        name=name,
        kind=kind,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_describe_fileset(session_ref: str, name: str, timeout_seconds: int = 60) -> dict[str, object]:
    """Describe one Vivado fileset in detail: file list, library, processing order, USED_IN scopes."""
    return manager.describe_fileset(session_ref=session_ref, name=name, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_constraint_diagnostics(session_ref: str, timeout_seconds: int = 120) -> dict[str, object]:
    """Audit XDC constraint filesets: loading order, USED_IN scopes, methodology markers, and warnings."""
    return manager.constraint_diagnostics(session_ref=session_ref, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_source_audit(
    session_ref: str,
    filesets: list[str] | None = None,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Audit project sources, filesets, top, duplicate files, and constraint placement."""
    return manager.source_audit(session_ref=session_ref, filesets=filesets, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_xdc_order_check(session_ref: str, timeout_seconds: int = 120) -> dict[str, object]:
    """Check XDC load order and flag exceptions or I/O delays that appear before clocks."""
    return manager.xdc_order_check(session_ref=session_ref, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_fileset_apply(
    session_ref: str,
    fileset: str,
    include_dirs: list[str] | None = None,
    defines: list[str] | None = None,
    top: str | None = None,
    properties: dict[str, object] | None = None,
    update_compile_order: bool = True,
    timeout_seconds: int = 120,
    capture_diff: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    """Apply common fileset-level source settings: include dirs, defines, top, and properties."""
    return manager.fileset_apply(
        session_ref=session_ref,
        fileset=fileset,
        include_dirs=include_dirs,
        defines=defines,
        top=top,
        properties=properties,
        update_compile_order=update_compile_order,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
        dry_run=dry_run,
    )


@mcp.tool()
def vivado_constraint_set_apply(
    session_ref: str,
    fileset: str,
    create_if_missing: bool = False,
    add: list[str] | None = None,
    remove: list[str] | None = None,
    used_in: list[Literal["synthesis", "simulation", "implementation"]] | None = None,
    reorder: list[str] | None = None,
    active: bool | None = None,
    timeout_seconds: int = 120,
    capture_diff: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    """Create/update a constraint fileset: add/remove XDC, set USED_IN scopes, reorder, or activate."""
    return manager.constraint_set_apply(
        session_ref=session_ref,
        fileset=fileset,
        create_if_missing=create_if_missing,
        add=add,
        remove=remove,
        used_in=used_in,
        reorder=reorder,
        active=active,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
        dry_run=dry_run,
    )


@mcp.tool()
def vivado_bd_open_or_create(
    session_ref: str,
    design_name: str | None = None,
    bd_path: str | None = None,
    create_if_missing: bool = True,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Open an existing block design by name/path, or create a generic IP Integrator design."""
    return manager.bd_open_or_create(
        session_ref=session_ref,
        design_name=design_name,
        bd_path=bd_path,
        create_if_missing=create_if_missing,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_bd_summary(
    session_ref: str,
    design_name: str | None = None,
    bd_path: str | None = None,
    validate: bool = False,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    """Return generic structured information about a block design's cells, ports, nets, and validation state."""
    return manager.bd_summary(
        session_ref=session_ref,
        design_name=design_name,
        bd_path=bd_path,
        validate=validate,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_bd_apply(
    session_ref: str,
    actions: list[dict[str, object]],
    design_name: str | None = None,
    bd_path: str | None = None,
    validate: bool = True,
    save: bool = True,
    timeout_seconds: int = 300,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Apply generic IP Integrator actions such as creating cells/ports, setting properties, and connecting nets."""
    return manager.bd_apply(
        session_ref=session_ref,
        actions=actions,
        design_name=design_name,
        bd_path=bd_path,
        validate=validate,
        save=save,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_bd_validate(
    session_ref: str,
    design_name: str | None = None,
    bd_path: str | None = None,
    save: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Run Vivado block design validation for the current or selected design."""
    return manager.bd_validate(
        session_ref=session_ref,
        design_name=design_name,
        bd_path=bd_path,
        save=save,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_bd_generate(
    session_ref: str,
    design_name: str | None = None,
    bd_path: str | None = None,
    target: str = "all",
    make_wrapper: bool = True,
    wrapper_top: bool = True,
    timeout_seconds: int = 600,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Generate block design output products and optionally add a generic HDL wrapper."""
    return manager.bd_generate(
        session_ref=session_ref,
        design_name=design_name,
        bd_path=bd_path,
        target=target,
        make_wrapper=make_wrapper,
        wrapper_top=wrapper_top,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_run_synthesis(
    session_ref: str,
    run_name: str = "synth_1",
    jobs: int | None = None,
    timeout_seconds: int = 3600,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Launch and wait for a Vivado synthesis run."""
    return manager.launch_run(
        session_ref=session_ref,
        run_name=run_name,
        jobs=jobs,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_run_implementation(
    session_ref: str,
    run_name: str = "impl_1",
    jobs: int | None = None,
    timeout_seconds: int = 7200,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Launch and wait for a Vivado implementation run."""
    return manager.launch_run(
        session_ref=session_ref,
        run_name=run_name,
        jobs=jobs,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_generate_bitstream(
    session_ref: str,
    run_name: str = "impl_1",
    jobs: int | None = None,
    timeout_seconds: int = 7200,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Run implementation through write_bitstream."""
    return manager.launch_run(
        session_ref=session_ref,
        run_name=run_name,
        jobs=jobs,
        to_step="write_bitstream",
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_report(
    session_ref: str,
    report_type: Literal["timing_summary", "timing_paths", "utilization", "drc", "power", "methodology", "clock_interaction", "messages"],
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
def vivado_analyze_reports(
    session_ref: str,
    report_types: list[Literal["timing_summary", "timing_paths", "utilization", "drc", "power", "methodology", "messages"]] | None = None,
    timeout_seconds: int = 300,
) -> dict[str, object]:
    """Generate common reports and return structured diagnostics with next-step guidance."""
    return manager.analyze_reports(session_ref=session_ref, report_types=report_types, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_hw_discover(
    session_ref: str,
    expect_hardware_access: bool = False,
    hw_server_url: str | None = None,
    target: str | None = None,
    open_target: bool = True,
    refresh: bool = False,
    timeout_seconds: int = 120,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Read-only hardware discovery. Opens/connects Hardware Manager and lists targets/devices; does not program devices."""
    return manager.hardware_discover(
        session_ref=session_ref,
        expect_hardware_access=expect_hardware_access,
        hw_server_url=hw_server_url,
        target=target,
        open_target=open_target,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_nonproject_read_sources(
    session_ref: str,
    verilog: list[str] | None = None,
    systemverilog: list[str] | None = None,
    vhdl: list[str] | None = None,
    xdc: list[str] | None = None,
    include_dirs: list[str] | None = None,
    defines: list[str] | None = None,
    library: str | None = None,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Read RTL and XDC files into a managed Non-project Mode design."""
    return manager.nonproject_read_sources(
        session_ref=session_ref,
        verilog=verilog,
        systemverilog=systemverilog,
        vhdl=vhdl,
        xdc=xdc,
        include_dirs=include_dirs,
        defines=defines,
        library=library,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_nonproject_synth_design(
    session_ref: str,
    part: str,
    top: str,
    checkpoint_name: str | None = "synth_design.dcp",
    report_types: list[Literal["timing_summary", "utilization", "drc", "methodology", "messages"]] | None = None,
    extra_args: dict[str, object] | None = None,
    timeout_seconds: int = 3600,
) -> dict[str, object]:
    """Run synth_design in Non-project Mode and optionally write checkpoint/reports."""
    return manager.nonproject_run_step(
        session_ref=session_ref,
        step="synth_design",
        part=part,
        top=top,
        checkpoint_name=checkpoint_name,
        report_types=report_types if report_types is not None else ["utilization", "drc"],
        extra_args=extra_args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_nonproject_opt_design(
    session_ref: str,
    checkpoint_name: str | None = "opt_design.dcp",
    report_types: list[Literal["timing_summary", "utilization", "drc", "methodology", "messages"]] | None = None,
    extra_args: dict[str, object] | None = None,
    timeout_seconds: int = 3600,
) -> dict[str, object]:
    """Run opt_design in Non-project Mode and optionally write checkpoint/reports."""
    return manager.nonproject_run_step(
        session_ref=session_ref,
        step="opt_design",
        checkpoint_name=checkpoint_name,
        report_types=report_types if report_types is not None else ["drc"],
        extra_args=extra_args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_nonproject_place_design(
    session_ref: str,
    checkpoint_name: str | None = "place_design.dcp",
    report_types: list[Literal["timing_summary", "utilization", "drc", "methodology", "messages"]] | None = None,
    extra_args: dict[str, object] | None = None,
    timeout_seconds: int = 7200,
) -> dict[str, object]:
    """Run place_design in Non-project Mode and optionally write checkpoint/reports."""
    return manager.nonproject_run_step(
        session_ref=session_ref,
        step="place_design",
        checkpoint_name=checkpoint_name,
        report_types=report_types if report_types is not None else ["timing_summary", "utilization", "drc"],
        extra_args=extra_args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_nonproject_route_design(
    session_ref: str,
    checkpoint_name: str | None = "route_design.dcp",
    report_types: list[Literal["timing_summary", "timing_paths", "utilization", "drc", "power", "methodology", "messages"]] | None = None,
    extra_args: dict[str, object] | None = None,
    timeout_seconds: int = 7200,
) -> dict[str, object]:
    """Run route_design in Non-project Mode and optionally write checkpoint/reports."""
    return manager.nonproject_run_step(
        session_ref=session_ref,
        step="route_design",
        checkpoint_name=checkpoint_name,
        report_types=report_types if report_types is not None else ["timing_summary", "utilization", "drc", "power", "methodology"],
        extra_args=extra_args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_prepare_simulation(
    session_ref: str,
    fileset: str = "sim_1",
    testbench_files: list[str] | None = None,
    top: str | None = None,
    include_dirs: list[str] | None = None,
    defines: list[str] | None = None,
    library: str | None = None,
    create_if_missing: bool = True,
    timeout_seconds: int = 120,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Create/update a simulation fileset with testbench files, top, includes, defines, and library."""
    return manager.prepare_simulation(
        session_ref=session_ref,
        fileset=fileset,
        testbench_files=testbench_files,
        top=top,
        include_dirs=include_dirs,
        defines=defines,
        library=library,
        create_if_missing=create_if_missing,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_launch_simulation(
    session_ref: str,
    fileset: str = "sim_1",
    mode: Literal["behavioral", "post-synthesis", "post-implementation"] = "behavioral",
    sim_type: Literal["functional", "timing"] | None = None,
    run_all: bool = True,
    scripts_only: bool = False,
    timeout_seconds: int = 1200,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Launch Vivado simulation and return structured launch/log information.

    Use mode="behavioral" without sim_type, or mode="post-synthesis"/"post-implementation"
    with sim_type="functional" or "timing".
    """
    return manager.launch_simulation(
        session_ref=session_ref,
        fileset=fileset,
        mode=mode,
        sim_type=sim_type,
        run_all=run_all,
        scripts_only=scripts_only,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_analyze_xsim_logs(
    session_ref: str,
    log_paths: list[str] | None = None,
    launch_summary_artifact: str | None = None,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Parse xsim/xelab/xvlog/xvhdl logs and return severity/category diagnostics."""
    return manager.analyze_xsim_logs(
        session_ref=session_ref,
        log_paths=log_paths,
        launch_summary_artifact=launch_summary_artifact,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_ip_catalog_search(
    session_ref: str,
    query: str | None = None,
    vendor: str | None = None,
    library: str | None = None,
    name: str | None = None,
    taxonomy: str | None = None,
    limit: int = 25,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Search the Vivado IP catalog and return matching IP definitions."""
    return manager.ip_catalog_search(
        session_ref=session_ref,
        query=query,
        vendor=vendor,
        library=library,
        name=name,
        taxonomy=taxonomy,
        limit=limit,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_create_ip(
    session_ref: str,
    module_name: str,
    output_dir: str,
    vlnv: str | None = None,
    vendor: str | None = None,
    library: str | None = None,
    ip_name: str | None = None,
    version: str | None = None,
    properties: dict[str, object] | None = None,
    timeout_seconds: int = 300,
    capture_diff: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    """Create a project IP instance from a VLNV or vendor/library/ip_name/version fields, or return a dry-run plan."""
    return manager.ip_create(
        session_ref=session_ref,
        module_name=module_name,
        output_dir=output_dir,
        vlnv=vlnv,
        vendor=vendor,
        library=library,
        ip_name=ip_name,
        version=version,
        properties=properties,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
        dry_run=dry_run,
    )


@mcp.tool()
def vivado_list_ips(session_ref: str, timeout_seconds: int = 120) -> dict[str, object]:
    """List project IP instances with VLNV, .xci path, lock, upgrade, and generation state."""
    return manager.ip_list(session_ref=session_ref, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_describe_ip(session_ref: str, name: str, timeout_seconds: int = 120) -> dict[str, object]:
    """Describe one project IP instance, including common properties and generated targets."""
    return manager.ip_describe(session_ref=session_ref, name=name, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_ip_upgrade_check(session_ref: str, timeout_seconds: int = 120) -> dict[str, object]:
    """Check project IP lock, upgrade, and generated-output state without modifying .xci files."""
    return manager.ip_upgrade_check(session_ref=session_ref, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_upgrade_ip(
    session_ref: str,
    name: str,
    expect_upgrade: bool = False,
    timeout_seconds: int = 300,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Upgrade one IP instance. Requires expect_upgrade=true because this modifies .xci state."""
    return manager.ip_upgrade(
        session_ref=session_ref,
        name=name,
        expect_upgrade=expect_upgrade,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_generate_ip_outputs(
    session_ref: str,
    name: str,
    targets: list[str] | None = None,
    timeout_seconds: int = 600,
    capture_diff: bool = False,
) -> dict[str, object]:
    """Generate IP output products for one IP instance."""
    return manager.ip_generate_outputs(
        session_ref=session_ref,
        name=name,
        targets=targets,
        timeout_seconds=timeout_seconds,
        capture_diff=capture_diff,
    )


@mcp.tool()
def vivado_project_summary(session_ref: str, timeout_seconds: int = 60) -> dict[str, object]:
    """Return structured information about the current Vivado project, files, runs, IP, and block designs."""
    return manager.project_summary(session_ref=session_ref, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_capture_state(
    session_ref: str,
    label: str | None = None,
    include_bd: bool = True,
    validate_bd: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Capture a JSON snapshot of project, fileset, constraint, and optional BD state."""
    return manager.capture_state(
        session_ref=session_ref,
        label=label,
        include_bd=include_bd,
        validate_bd=validate_bd,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_state_diff(
    session_ref: str,
    before_artifact_id: str,
    after_artifact_id: str,
) -> dict[str, object]:
    """Diff two JSON state snapshots produced by vivado_capture_state."""
    return manager.state_diff(
        session_ref=session_ref,
        before_artifact_id=before_artifact_id,
        after_artifact_id=after_artifact_id,
    )


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


@mcp.tool()
def vivado_list_official_references(query: str | None = None, topic: str | None = None) -> dict[str, object]:
    """List packaged AMD official Vivado documentation references by keyword or topic."""
    return {"references": list_official_references(query=query, topic=topic)}


@mcp.tool()
def vivado_get_official_reference(doc_id: str) -> dict[str, object]:
    """Return one packaged AMD official Vivado documentation reference."""
    return get_official_reference(doc_id)


@mcp.tool()
def vivado_official_reference_guide(topic: str | None = None) -> dict[str, object]:
    """Return AI guidance for which AMD official Vivado references apply to a topic."""
    return official_reference_guide(topic)


@mcp.tool()
def vivado_search_official_docs(
    query: str,
    doc_id: str | None = None,
    topic: str | None = None,
    max_results: int = 8,
    context_chars: int = 260,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Search local AMD official Vivado PDFs and return short supporting snippets."""
    return search_official_docs(
        query=query,
        doc_id=doc_id,
        topic=topic,
        max_results=max_results,
        context_chars=context_chars,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_search_xilinx_docs(query: str, limit: int = 10, timeout_seconds: int = 30) -> dict[str, object]:
    """Search AMD KHub for Xilinx/AMD PDFs and documentation entries."""
    return search_xilinx_docs(query=query, limit=limit, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_download_xilinx_pdf(
    source: str,
    output_name: str | None = None,
    overwrite: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Download one AMD/Xilinx PDF into the configured local docs root and verify the PDF signature."""
    return download_xilinx_pdf(
        source=source,
        output_name=output_name,
        out_dir=local_docs_root(),
        overwrite=overwrite,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def vivado_sync_official_docs(
    doc_ids: list[str] | None = None,
    overwrite: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Download packaged Vivado official references into the configured local docs root."""
    return sync_official_docs(doc_ids=doc_ids, overwrite=overwrite, timeout_seconds=timeout_seconds)


@mcp.tool()
def vivado_clean_bad_pdfs(delete_bad: bool = False) -> dict[str, object]:
    """Find local docs-root PDFs that fail the %PDF signature check, optionally deleting them."""
    return clean_bad_pdfs(root=local_docs_root(), delete_bad=delete_bad)


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


@mcp.resource("vivado://official-docs/index", mime_type="text/markdown")
def resource_official_docs_index() -> str:
    """AMD official Vivado documentation reference index."""
    return official_docs_index()


@mcp.resource("vivado://official-docs/{doc_id}", mime_type="text/markdown")
def resource_official_doc(doc_id: str) -> str:
    """One AMD official Vivado documentation reference."""
    return official_doc_resource(doc_id)


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
        "official_docs_root": local_docs_root(),
    }


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
