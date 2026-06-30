from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from . import cli_core
from .help_skills import get_skill, help_topic, list_skills
from .official_docs import search_official_docs
from .tcl_assist import build_tcl_command_help, review_tcl, tcl_command_doc_topic
from .tool_catalog import describe_tool, list_tools
from .vivado_locator import check_vivado


def main(argv: Sequence[str] | None = None) -> int:
    argv = _normalize_global_flags(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return 2
    try:
        payload = args.func(args)
        _emit(payload, pretty=bool(args.pretty))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should return structured errors.
        _emit({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, pretty=bool(args.pretty), stream=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vivado-cli",
        description="CLI-first Vivado automation through Tcl and managed GUI sessions.",
    )
    parser.add_argument("--version", action="version", version=f"vivado-cli {__version__}")
    parser.add_argument(
        "--workspace",
        default=os.environ.get("VIVADO_CLI_WORKSPACE") or os.getcwd(),
        help="Directory used for persistent CLI session records and artifacts.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check-installation", help="Find Vivado and return its version.")
    check.add_argument("--vivado-path")
    check.add_argument("--timeout", type=int, default=60)
    check.set_defaults(func=_cmd_check_installation)

    session = sub.add_parser("session", help="Manage persistent Vivado CLI sessions.")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    start = session_sub.add_parser("start", help="Start a persistent Vivado session.")
    start.add_argument("--vivado-path")
    start.add_argument("--no-gui", action="store_true")
    start.add_argument("--profile", choices=["safe", "trusted-local", "unrestricted"], default="trusted-local")
    start.add_argument("--timeout", type=int, default=45)
    start.set_defaults(func=_cmd_session_start)

    adopt = session_sub.add_parser("adopt", help="Adopt an existing file-backed Vivado bridge session.")
    adopt.add_argument("--session-dir", required=True, help="Existing bridge session directory with inbox/running/done.")
    adopt.add_argument("--pid", required=True, type=int, help="Running Vivado process PID that owns the bridge.")
    adopt.add_argument("--session-ref", help="Session ref to register; defaults to the session directory name.")
    adopt.add_argument("--vivado-path", help="Vivado executable path for metadata.")
    adopt.add_argument("--project", help="Current project path for metadata.")
    adopt.add_argument("--no-gui", action="store_true")
    adopt.add_argument("--profile", choices=["safe", "trusted-local", "unrestricted"], default="trusted-local")
    adopt.set_defaults(func=_cmd_session_adopt)

    session_list = session_sub.add_parser("list", help="List known CLI sessions.")
    session_list.set_defaults(func=_cmd_session_list)

    state = session_sub.add_parser("state", help="Show one session state.")
    _add_session_arg(state)
    state.set_defaults(func=_cmd_session_state)

    stop = session_sub.add_parser("stop", help="Stop a persistent Vivado session.")
    _add_session_arg(stop)
    stop.add_argument("--force", action="store_true")
    stop.add_argument("--timeout", type=int, default=20)
    stop.set_defaults(func=_cmd_session_stop)

    open_project = session_sub.add_parser("open-project", help="Open a Vivado .xpr in an existing session.")
    _add_session_arg(open_project)
    open_project.add_argument("project")
    open_project.add_argument("--timeout", type=int, default=120)
    open_project.set_defaults(func=_cmd_open_project)

    run_tcl = session_sub.add_parser("run-tcl", help="Run Tcl text in an existing session.")
    _add_session_arg(run_tcl)
    source = run_tcl.add_mutually_exclusive_group(required=True)
    source.add_argument("--tcl", help="Inline Tcl to execute.")
    source.add_argument("--file", help="Read Tcl text from this file and execute it inline.")
    source.add_argument("--stdin", action="store_true", help="Read Tcl text from stdin.")
    run_tcl.add_argument("--timeout", type=int, default=60)
    run_tcl.add_argument("--expect-destructive", action="store_true")
    run_tcl.set_defaults(func=_cmd_run_tcl)

    source_tcl = session_sub.add_parser("source-tcl", help="Source a Tcl file inside Vivado.")
    _add_session_arg(source_tcl)
    source_tcl.add_argument("script")
    source_tcl.add_argument("tclargs", nargs="*")
    source_tcl.add_argument("--timeout", type=int, default=120)
    source_tcl.add_argument("--expect-destructive", action="store_true")
    source_tcl.set_defaults(func=_cmd_source_tcl)

    tcl = sub.add_parser("tcl", help="Review Tcl and query command help.")
    tcl_sub = tcl.add_subparsers(dest="tcl_command", required=True)
    review = tcl_sub.add_parser("review", help="Review Tcl before execution.")
    review.add_argument("path", nargs="?", help="Read Tcl text from this file, equivalent to --file.")
    review_source = review.add_mutually_exclusive_group(required=False)
    review_source.add_argument("--tcl")
    review_source.add_argument("--file")
    review_source.add_argument("--stdin", action="store_true", help="Read Tcl text from stdin.")
    review.add_argument("--goal")
    review.set_defaults(func=_cmd_tcl_review)

    help_cmd = tcl_sub.add_parser("help", help="Show structured help guidance for a Tcl command.")
    help_cmd.add_argument("vivado_command")
    help_cmd.add_argument("--session")
    help_cmd.add_argument("--timeout", type=int, default=30)
    help_cmd.set_defaults(func=_cmd_tcl_help)

    skills = sub.add_parser("skills", help="Discover packaged Vivado CLI workflow skills.")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills_list = skills_sub.add_parser("list", help="List packaged workflow skills.")
    skills_list.add_argument("--query", help="Filter skills by id, title, or summary.")
    skills_list.set_defaults(func=_cmd_skills_list)

    skills_get = skills_sub.add_parser("get", help="Return one packaged workflow skill document.")
    skills_get.add_argument("skill_id")
    skills_get.set_defaults(func=_cmd_skills_get)

    help_parser = sub.add_parser("help", help="Return structured CLI guidance topics.")
    help_sub = help_parser.add_subparsers(dest="help_command", required=True)
    help_topic_parser = help_sub.add_parser("topic", help="Return structured guidance for a topic.")
    help_topic_parser.add_argument("topic", nargs="?", default="index")
    help_topic_parser.set_defaults(func=_cmd_help_topic)

    tools = sub.add_parser("tools", help="Discover implemented CLI commands for AI callers.")
    tools_sub = tools.add_subparsers(dest="tools_command", required=True)
    tools_list = tools_sub.add_parser("list", help="List implemented CLI commands.")
    tools_list.add_argument("--query", help="Filter tools by command, id, summary, risk, or skill.")
    tools_list.set_defaults(func=_cmd_tools_list)

    tools_describe = tools_sub.add_parser("describe", help="Describe one implemented CLI command.")
    tools_describe.add_argument("name", nargs="+", help="Command words or tool_id, e.g. 'run launch-local'.")
    tools_describe.set_defaults(func=_cmd_tools_describe)

    bd = sub.add_parser("bd", help="Inspect and validate block designs.")
    bd_sub = bd.add_subparsers(dest="bd_command", required=True)
    bd_summary = bd_sub.add_parser("summary", help="Write and parse a BD summary.")
    _add_session_arg(bd_summary)
    bd_summary.add_argument("--design")
    bd_summary.add_argument("--bd-path")
    bd_summary.add_argument("--validate", action="store_true")
    bd_summary.add_argument("--timeout", type=int, default=60)
    bd_summary.set_defaults(func=_cmd_bd_summary)

    bd_validate = bd_sub.add_parser("validate", help="Run validate_bd_design and parse issues.")
    _add_session_arg(bd_validate)
    bd_validate.add_argument("--design")
    bd_validate.add_argument("--bd-path")
    bd_validate.add_argument("--save", action="store_true")
    bd_validate.add_argument("--timeout", type=int, default=120)
    bd_validate.set_defaults(func=_cmd_bd_validate)

    hw = sub.add_parser("hw", help="Inspect and capture live Vivado hardware.")
    hw_sub = hw.add_subparsers(dest="hw_command", required=True)
    hw_list_debug_cores = hw_sub.add_parser("list-debug-cores", help="List hardware ILA/VIO debug cores and probes.")
    _add_session_arg(hw_list_debug_cores)
    hw_list_debug_cores.add_argument("--expect-hardware-access", action="store_true", help="Acknowledge live hw_server/device access.")
    hw_list_debug_cores.add_argument("--timeout", type=int, default=60)
    hw_list_debug_cores.set_defaults(func=_cmd_hw_list_debug_cores)

    hw_vio_read = hw_sub.add_parser("vio-read", help="Read current values from VIO probes without changing outputs.")
    _add_session_arg(hw_vio_read)
    hw_vio_read.add_argument("--vio", required=True, help="hw_vio object name/pattern or implemented CELL_NAME.")
    vio_read_selector = hw_vio_read.add_mutually_exclusive_group(required=True)
    vio_read_selector.add_argument("--probe", dest="probes", action="append", help="VIO probe name or pattern. Repeatable.")
    vio_read_selector.add_argument("--all-probes", action="store_true", help="Read every probe on the selected VIO.")
    hw_vio_read.add_argument("--value-radix", choices=["auto", "hex", "binary", "decimal"], default="auto")
    hw_vio_read.add_argument("--expect-hardware-access", action="store_true", help="Acknowledge live hw_server/device access.")
    hw_vio_read.add_argument("--timeout", type=int, default=60)
    hw_vio_read.set_defaults(func=_cmd_hw_vio_read)

    hw_vio_write = hw_sub.add_parser("vio-write", help="Write VIO output probes after explicit acknowledgement.")
    _add_session_arg(hw_vio_write)
    hw_vio_write.add_argument("--vio", required=True, help="hw_vio object name/pattern or implemented CELL_NAME.")
    hw_vio_write.add_argument("--set", dest="sets", action="append", required=True, help="Probe assignment as probe=value. Repeatable.")
    hw_vio_write.add_argument("--value-radix", choices=["auto", "hex", "binary", "decimal"], default="auto")
    hw_vio_write.add_argument("--expect-hardware-access", action="store_true", help="Acknowledge live hw_server/device access.")
    hw_vio_write.add_argument("--expect-vio-write", action="store_true", help="Acknowledge changing VIO output probes.")
    hw_vio_write.add_argument("--timeout", type=int, default=60)
    hw_vio_write.set_defaults(func=_cmd_hw_vio_write)

    hw_capture_ila = hw_sub.add_parser("capture-ila", help="Capture one hardware ILA and optionally analyze its CSV.")
    _add_session_arg(hw_capture_ila)
    selector = hw_capture_ila.add_mutually_exclusive_group(required=True)
    selector.add_argument("--ila", help="hw_ila object name or pattern, e.g. hw_ila_3; also falls back to CELL_NAME matching.")
    selector.add_argument("--cell-name", help="Implemented debug-core CELL_NAME to select.")
    hw_capture_ila.add_argument("--depth", type=int, default=1024, help="Requested ILA capture depth.")
    hw_capture_ila.add_argument("--label", help="Stable artifact label; defaults to the ILA selector.")
    hw_capture_ila.add_argument(
        "--analysis",
        choices=["none", "digital", "unsigned", "signed", "adc14"],
        default="none",
        help="Optional project-agnostic CSV analysis mode.",
    )
    hw_capture_ila.add_argument("--sample-rate-hz", type=float, help="Sample rate used to convert FFT bins to Hz.")
    hw_capture_ila.add_argument("--signed-width", type=int, help="Signed width for --analysis signed.")
    hw_capture_ila.add_argument("--expect-hardware-access", action="store_true", help="Acknowledge live hw_server/device access.")
    hw_capture_ila.add_argument("--timeout", type=int, default=60)
    hw_capture_ila.set_defaults(func=_cmd_hw_capture_ila)

    hw_spi_read = hw_sub.add_parser("spi-read", help="Read generic SPI-style registers through VIO probes.")
    _add_session_arg(hw_spi_read)
    hw_spi_read.add_argument("--vio", required=True, help="hw_vio object name/pattern or implemented CELL_NAME.")
    hw_spi_read.add_argument("--status-probe", required=True, help="VIO input probe carrying packed read status/data.")
    hw_spi_read.add_argument("--req-probe", required=True, help="VIO output probe used as read request strobe.")
    hw_spi_read.add_argument("--target-probe", required=True, help="VIO output probe carrying the target/device select.")
    hw_spi_read.add_argument("--addr-probe", required=True, help="VIO output probe carrying the register address.")
    hw_spi_read.add_argument("--target", help="Single read target/device select, e.g. 2 or 0x2.")
    hw_spi_read.add_argument("--addr", help="Single read address, e.g. 0x0281.")
    hw_spi_read.add_argument("--reg", action="append", help="Batch read register as target:addr, e.g. 2:0x0281. Repeatable.")
    hw_spi_read.add_argument("--status-radix", choices=["hex", "binary", "decimal", "auto"], default="hex")
    hw_spi_read.add_argument("--data-bits", default="7:0", help="Data bit range inside status, default 7:0.")
    hw_spi_read.add_argument("--addr-bits", default="22:8", help="Echoed address bit range inside status, default 22:8.")
    hw_spi_read.add_argument("--target-bits", default="24:23", help="Echoed target bit range inside status, default 24:23.")
    hw_spi_read.add_argument("--busy-bit", default="25", help="Busy bit index, or 'none'.")
    hw_spi_read.add_argument("--done-bit", default="26", help="Done bit index, or 'none'.")
    hw_spi_read.add_argument("--enable-bit", default="27", help="Enable/valid bit index, or 'none'.")
    hw_spi_read.add_argument("--error-bit", default="28", help="Error bit index, or 'none'.")
    hw_spi_read.add_argument("--poll-count", type=int, default=80, help="Maximum VIO status polls per register.")
    hw_spi_read.add_argument("--poll-interval-ms", type=int, default=25, help="Delay between VIO status polls.")
    hw_spi_read.add_argument("--expect-hardware-access", action="store_true", help="Acknowledge live hw_server/device access.")
    hw_spi_read.add_argument("--timeout", type=int, default=60)
    hw_spi_read.set_defaults(func=_cmd_hw_spi_read)

    project = sub.add_parser("project", help="Inspect Vivado project state.")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_summary = project_sub.add_parser("summary", help="Write and parse a project summary.")
    _add_session_arg(project_summary)
    project_summary.add_argument("--timeout", type=int, default=60)
    project_summary.set_defaults(func=_cmd_project_summary)

    run = sub.add_parser("run", help="Inspect and launch Vivado project runs.")
    run_sub = run.add_subparsers(dest="run_command", required=True)
    run_status = run_sub.add_parser("status", help="Show current run status without launching work.")
    _add_session_arg(run_status)
    run_status.add_argument("--run", dest="run_name", help="Optional run name to filter, e.g. synth_1.")
    run_status.add_argument("--timeout", type=int, default=60)
    run_status.set_defaults(func=_cmd_run_status)

    run_launch = run_sub.add_parser("launch", help="Launch a Vivado run without waiting for completion.")
    _add_session_arg(run_launch)
    run_launch.add_argument("run_name", help="Run name, e.g. synth_1 or impl_1.")
    run_launch.add_argument("--jobs", type=int, help="Number of parallel jobs to pass to launch_runs.")
    run_launch.add_argument("--to-step", help="Optional implementation step for launch_runs -to_step.")
    run_launch.add_argument("--timeout", type=int, default=60)
    run_launch.set_defaults(func=_cmd_run_launch)

    run_launch_local = run_sub.add_parser(
        "launch-local",
        help="Launch Vivado's generated local run script, e.g. runme.bat, without waiting.",
    )
    _add_session_arg(run_launch_local)
    run_launch_local.add_argument("run_name", help="Run name, e.g. synth_1 or impl_1.")
    run_launch_local.add_argument("--jobs", type=int, help="Number of parallel jobs to pass if launch_runs must prepare the script.")
    run_launch_local.add_argument("--to-step", help="Optional implementation step if launch_runs must prepare the script.")
    run_launch_local.add_argument("--timeout", type=int, default=60)
    run_launch_local.set_defaults(func=_cmd_run_launch_local)

    run_logs = run_sub.add_parser("logs", help="Read a run log from the Vivado run directory.")
    _add_session_arg(run_logs)
    run_logs.add_argument("run_name", help="Run name, e.g. synth_1 or impl_1.")
    run_logs.add_argument("--log", dest="log_name", help="Optional log filename in the run directory.")
    run_logs.add_argument("--tail", dest="tail_lines", type=int, default=80, help="Number of trailing lines to return.")
    run_logs.add_argument("--timeout", type=int, default=60)
    run_logs.set_defaults(func=_cmd_run_logs)

    run_diagnose = run_sub.add_parser("diagnose", help="Diagnose one Vivado run and its run directory.")
    _add_session_arg(run_diagnose)
    run_diagnose.add_argument("run_name", help="Run name, e.g. synth_1 or impl_1.")
    run_diagnose.add_argument("--timeout", type=int, default=60)
    run_diagnose.set_defaults(func=_cmd_run_diagnose)

    run_reset = run_sub.add_parser("reset", help="Reset a Vivado run; requires --expect-destructive.")
    _add_session_arg(run_reset)
    run_reset.add_argument("run_name", help="Run name, e.g. synth_1 or impl_1.")
    run_reset.add_argument("--timeout", type=int, default=60)
    run_reset.add_argument("--expect-destructive", action="store_true")
    run_reset.set_defaults(func=_cmd_run_reset)

    report = sub.add_parser("report", help="Generate and parse a Vivado report.")
    _add_session_arg(report)
    report.add_argument("type")
    report.add_argument("--output-name")
    report.add_argument("--timeout", type=int, default=300)
    report.set_defaults(func=_cmd_report)

    return parser


def _add_session_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session", required=True, help="CLI session_ref.")


def _cmd_check_installation(args: argparse.Namespace) -> dict[str, object]:
    installation = check_vivado(args.vivado_path, timeout_seconds=args.timeout)
    return {"ok": True, "vivado_path": str(installation.executable), "version": installation.version}


def _cmd_session_start(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.start_session(
        workspace=args.workspace,
        vivado_path=args.vivado_path,
        open_gui=not args.no_gui,
        capability_profile=args.profile,
        startup_timeout_seconds=args.timeout,
    )


def _cmd_session_adopt(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.adopt_session(
        workspace=args.workspace,
        session_dir=args.session_dir,
        process_pid=args.pid,
        session_ref=args.session_ref,
        vivado_path=args.vivado_path,
        open_gui=not args.no_gui,
        capability_profile=args.profile,
        current_project_path=args.project,
    )


def _cmd_session_list(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.list_sessions(workspace=args.workspace)


def _cmd_session_state(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.session_state(workspace=args.workspace, session_ref=args.session)


def _cmd_session_stop(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.stop_session(
        workspace=args.workspace,
        session_ref=args.session,
        force=args.force,
        timeout_seconds=args.timeout,
    )


def _cmd_open_project(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.open_project(
        workspace=args.workspace,
        session_ref=args.session,
        project_path=args.project,
        timeout_seconds=args.timeout,
    )


def _cmd_run_tcl(args: argparse.Namespace) -> dict[str, object]:
    if args.tcl is not None:
        tcl = args.tcl
    elif args.file is not None:
        tcl = Path(args.file).read_text(encoding="utf-8")
    else:
        tcl = sys.stdin.read()
    return cli_core.run_tcl(
        workspace=args.workspace,
        session_ref=args.session,
        tcl=tcl,
        timeout_seconds=args.timeout,
        expect_destructive=args.expect_destructive,
    )


def _cmd_source_tcl(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.source_tcl(
        workspace=args.workspace,
        session_ref=args.session,
        script_path=args.script,
        tclargs=args.tclargs,
        timeout_seconds=args.timeout,
        expect_destructive=args.expect_destructive,
    )


def _cmd_tcl_review(args: argparse.Namespace) -> dict[str, object]:
    sources = [
        source
        for source in (("tcl", args.tcl), ("file", args.file), ("stdin", args.stdin), ("path", args.path))
        if source[1] is not None and source[1] is not False
    ]
    if len(sources) != 1:
        raise ValueError("Provide exactly one Tcl source: --tcl, --file, --stdin, or PATH.")
    source_kind, source_value = sources[0]
    source: dict[str, object] = {"kind": source_kind}
    if source_kind == "tcl":
        tcl = source_value
    elif source_kind == "stdin":
        tcl = sys.stdin.read()
    else:
        path = Path(source_value).resolve()
        tcl = path.read_text(encoding="utf-8")
        source["path"] = str(path)
    source["line_count"] = len(tcl.splitlines())
    source["sha256"] = hashlib.sha256(tcl.encode("utf-8")).hexdigest()
    result = review_tcl(tcl, intended_goal=args.goal)
    result["source"] = source
    return result


def _cmd_tcl_help(args: argparse.Namespace) -> dict[str, object]:
    official_search = None
    doc_topic = tcl_command_doc_topic(args.vivado_command)
    try:
        official_search = search_official_docs(
            query=args.vivado_command,
            topic=doc_topic,
            timeout_seconds=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - Help should degrade gracefully.
        official_search = {
            "ok": False,
            "query": args.vivado_command,
            "topic": doc_topic,
            "error": str(exc),
            "results": [],
        }
    installed_help = None
    if args.session:
        try:
            installed_help = cli_core.tcl_help(
                workspace=args.workspace,
                session_ref=args.session,
                command=args.vivado_command,
                timeout_seconds=args.timeout,
            )
        except Exception as exc:  # noqa: BLE001 - Help should degrade gracefully.
                installed_help = {"ok": False, "error": str(exc)}
    return build_tcl_command_help(
        command=args.vivado_command,
        official_search=official_search,
        installed_help=installed_help,
        official_doc_topic=doc_topic,
    )


def _cmd_skills_list(args: argparse.Namespace) -> dict[str, object]:
    return {"ok": True, "skills": list_skills(query=args.query)}


def _cmd_skills_get(args: argparse.Namespace) -> dict[str, object]:
    return {"ok": True, "skill": get_skill(args.skill_id)}


def _cmd_help_topic(args: argparse.Namespace) -> dict[str, object]:
    return {"ok": True, "help": help_topic(args.topic)}


def _cmd_tools_list(args: argparse.Namespace) -> dict[str, object]:
    return {"ok": True, "tools": list_tools(query=args.query)}


def _cmd_tools_describe(args: argparse.Namespace) -> dict[str, object]:
    return {"ok": True, "tool": describe_tool(" ".join(args.name))}


def _cmd_bd_summary(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.bd_summary(
        workspace=args.workspace,
        session_ref=args.session,
        design_name=args.design,
        bd_path=args.bd_path,
        validate=args.validate,
        timeout_seconds=args.timeout,
    )


def _cmd_bd_validate(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.bd_validate(
        workspace=args.workspace,
        session_ref=args.session,
        design_name=args.design,
        bd_path=args.bd_path,
        save=args.save,
        timeout_seconds=args.timeout,
    )


def _cmd_hw_list_debug_cores(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.list_debug_cores(
        workspace=args.workspace,
        session_ref=args.session,
        timeout_seconds=args.timeout,
        expect_hardware_access=args.expect_hardware_access,
    )


def _cmd_hw_vio_read(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.vio_read(
        workspace=args.workspace,
        session_ref=args.session,
        vio=args.vio,
        probes=args.probes,
        all_probes=args.all_probes,
        value_radix=args.value_radix,
        timeout_seconds=args.timeout,
        expect_hardware_access=args.expect_hardware_access,
    )


def _cmd_hw_vio_write(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.vio_write(
        workspace=args.workspace,
        session_ref=args.session,
        vio=args.vio,
        writes=_parse_vio_writes(args.sets),
        value_radix=args.value_radix,
        timeout_seconds=args.timeout,
        expect_hardware_access=args.expect_hardware_access,
        expect_vio_write=args.expect_vio_write,
    )


def _cmd_hw_capture_ila(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.capture_ila(
        workspace=args.workspace,
        session_ref=args.session,
        ila=args.ila,
        cell_name=args.cell_name,
        depth=args.depth,
        label=args.label,
        analysis=args.analysis,
        sample_rate_hz=args.sample_rate_hz,
        signed_width=args.signed_width,
        timeout_seconds=args.timeout,
        expect_hardware_access=args.expect_hardware_access,
    )


def _cmd_hw_spi_read(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.spi_read(
        workspace=args.workspace,
        session_ref=args.session,
        vio=args.vio,
        status_probe=args.status_probe,
        req_probe=args.req_probe,
        target_probe=args.target_probe,
        addr_probe=args.addr_probe,
        registers=_parse_spi_registers(args),
        status_layout={
            "data_bits": args.data_bits,
            "addr_bits": args.addr_bits,
            "target_bits": args.target_bits,
            "busy_bit": _parse_optional_bit_arg(args.busy_bit, "busy-bit"),
            "done_bit": _parse_optional_bit_arg(args.done_bit, "done-bit"),
            "enable_bit": _parse_optional_bit_arg(args.enable_bit, "enable-bit"),
            "error_bit": _parse_optional_bit_arg(args.error_bit, "error-bit"),
        },
        status_radix=args.status_radix,
        poll_count=args.poll_count,
        poll_interval_ms=args.poll_interval_ms,
        timeout_seconds=args.timeout,
        expect_hardware_access=args.expect_hardware_access,
    )


def _cmd_project_summary(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.project_summary(
        workspace=args.workspace,
        session_ref=args.session,
        timeout_seconds=args.timeout,
    )


def _cmd_run_status(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.run_status(
        workspace=args.workspace,
        session_ref=args.session,
        run_name=args.run_name,
        timeout_seconds=args.timeout,
    )


def _cmd_run_launch(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.launch_run(
        workspace=args.workspace,
        session_ref=args.session,
        run_name=args.run_name,
        jobs=args.jobs,
        to_step=args.to_step,
        timeout_seconds=args.timeout,
    )


def _cmd_run_launch_local(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.launch_run_local(
        workspace=args.workspace,
        session_ref=args.session,
        run_name=args.run_name,
        jobs=args.jobs,
        to_step=args.to_step,
        timeout_seconds=args.timeout,
    )


def _cmd_run_logs(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.run_logs(
        workspace=args.workspace,
        session_ref=args.session,
        run_name=args.run_name,
        log_name=args.log_name,
        tail_lines=args.tail_lines,
        timeout_seconds=args.timeout,
    )


def _cmd_run_diagnose(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.diagnose_run(
        workspace=args.workspace,
        session_ref=args.session,
        run_name=args.run_name,
        timeout_seconds=args.timeout,
    )


def _cmd_run_reset(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.reset_run(
        workspace=args.workspace,
        session_ref=args.session,
        run_name=args.run_name,
        timeout_seconds=args.timeout,
        expect_destructive=args.expect_destructive,
    )


def _cmd_report(args: argparse.Namespace) -> dict[str, object]:
    return cli_core.report(
        workspace=args.workspace,
        session_ref=args.session,
        report_type=args.type,
        output_name=args.output_name,
        timeout_seconds=args.timeout,
    )


def _emit(payload: Any, *, pretty: bool, stream: Any | None = None) -> None:
    stream = stream or sys.stdout
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=stream)
    else:
        print(cli_core.compact_json(payload), file=stream)


def _normalize_global_flags(argv: Sequence[str]) -> list[str]:
    normalized = list(argv)
    pretty = False
    while "--pretty" in normalized:
        normalized.remove("--pretty")
        pretty = True
    if pretty:
        normalized.insert(0, "--pretty")
    return normalized


def _parse_spi_registers(args: argparse.Namespace) -> list[dict[str, int]]:
    registers: list[dict[str, int]] = []
    for item in args.reg or []:
        normalized = str(item).replace(",", ":")
        parts = normalized.split(":")
        if len(parts) != 2:
            raise ValueError(f"--reg must be target:addr, got {item!r}")
        registers.append({"target": _parse_int_arg(parts[0], "reg target"), "addr": _parse_int_arg(parts[1], "reg addr")})
    if args.target is not None or args.addr is not None:
        if args.target is None or args.addr is None:
            raise ValueError("Provide both --target and --addr for a single SPI read")
        registers.append({"target": _parse_int_arg(args.target, "target"), "addr": _parse_int_arg(args.addr, "addr")})
    if not registers:
        raise ValueError("Provide --target and --addr, or one or more --reg target:addr")
    return registers


def _parse_int_arg(value: str, name: str) -> int:
    try:
        return int(str(value), 0)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer literal, got {value!r}") from exc


def _parse_optional_bit_arg(value: str, name: str) -> int | None:
    text = str(value).strip().lower()
    if text in {"", "none", "off", "disabled"}:
        return None
    bit = _parse_int_arg(text, name)
    if bit < 0:
        return None
    return bit


def _parse_vio_writes(items: list[str]) -> list[dict[str, str]]:
    writes: list[dict[str, str]] = []
    for item in items:
        probe, separator, value = str(item).partition("=")
        if not separator:
            raise ValueError(f"--set must be probe=value, got {item!r}")
        if not probe.strip():
            raise ValueError(f"--set probe must not be empty, got {item!r}")
        if value == "":
            raise ValueError(f"--set value must not be empty, got {item!r}")
        writes.append({"probe": probe.strip(), "value": value.strip()})
    return writes


if __name__ == "__main__":
    raise SystemExit(main())
