from __future__ import annotations

from pathlib import Path


def quote_tcl(value: str | Path) -> str:
    text = str(value).replace("\\", "/")
    return "{" + text.replace("}", "\\}") + "}"


def tcl_list(values: list[str | Path]) -> str:
    return " ".join(quote_tcl(value) for value in values)


def set_argv_tcl(args: list[str]) -> str:
    return "\n".join(
        [
            f"set ::argv [list {tcl_list(args)}]",
            f"set ::argc {len(args)}",
        ]
    )


def stop_bridge_tcl() -> str:
    return "\n".join(
        [
            "catch { stop_gui }",
            "set ::vivado_mcp_bridge_forever 1",
            'return "stopping"',
        ]
    )


def create_project_tcl(
    *,
    project_name: str,
    project_dir: Path,
    part: str | None,
    board_part: str | None,
    force: bool,
) -> str:
    force_arg = " -force" if force else ""
    lines = [
        f"create_project {quote_tcl(project_name)} {quote_tcl(project_dir)}{force_arg}",
    ]
    if part:
        lines[0] += f" -part {quote_tcl(part)}"
    if board_part:
        lines.append(f"set_property board_part {quote_tcl(board_part)} [current_project]")
    lines.append('return "project_created=[current_project]"')
    return "\n".join(lines)


def open_project_tcl(project_path: Path) -> str:
    return "\n".join(
        [
            f"open_project {quote_tcl(project_path)}",
            'return "project_opened=[current_project]"',
        ]
    )


def add_sources_tcl(
    *,
    sources: list[Path],
    constraints: list[Path],
    top: str | None,
) -> str:
    lines: list[str] = []
    if sources:
        lines.append(f"add_files [list {tcl_list(sources)}]")
    if constraints:
        lines.append(f"add_files -fileset constrs_1 [list {tcl_list(constraints)}]")
    if top:
        lines.append(f"set_property top {quote_tcl(top)} [current_fileset]")
    lines.append('update_compile_order -fileset sources_1')
    lines.append('return "sources_updated"')
    return "\n".join(lines)


def launch_run_tcl(run_name: str, jobs: int | None, to_step: str | None = None) -> str:
    args = [f"launch_runs {quote_tcl(run_name)}"]
    if to_step:
        args.append(f"-to_step {quote_tcl(to_step)}")
    if jobs:
        args.append(f"-jobs {int(jobs)}")
    lines = [
        " ".join(args),
        f"wait_on_run {quote_tcl(run_name)}",
        f"set status [get_property STATUS [get_runs {quote_tcl(run_name)}]]",
        'return "status=$status"',
    ]
    return "\n".join(lines)


def report_tcl(report_type: str, output_path: Path) -> str:
    commands = {
        "timing_summary": "report_timing_summary",
        "timing_paths": "report_timing",
        "utilization": "report_utilization",
        "drc": "report_drc",
        "power": "report_power",
        "clock_interaction": "report_clock_interaction",
        "messages": "report_messages",
    }
    command = commands.get(report_type)
    if command is None:
        allowed = ", ".join(sorted(commands))
        raise ValueError(f"Unsupported report_type {report_type!r}; expected one of {allowed}")
    return "\n".join(
        [
            f"{command} -file {quote_tcl(output_path)} -force",
            f"return \"report={str(output_path).replace('\\', '/')}\"",
        ]
    )


def project_summary_tcl(output_path: Path) -> str:
    out = quote_tcl(output_path)
    out_string = str(output_path).replace("\\", "/")
    return "\n".join(
        [
            f"set mcp_summary_file {out}",
            "set f [open $mcp_summary_file w]",
            "proc mcp_put {f args} { puts $f [join $args \"\\t\"] }",
            "if {[catch {current_project} project] || $project eq \"\"} {",
            "  mcp_put $f has_project 0",
            "  close $f",
            f"  return \"summary={out_string}\"",
            "}",
            "mcp_put $f has_project 1",
            "mcp_put $f current_project $project",
            "foreach {prop key} {FILE_NAME project_file PART part BOARD_PART board_part TOP top} {",
            "  set value \"\"",
            "  catch { set value [get_property $prop [current_project]] }",
            "  if {$value ne \"\"} { mcp_put $f $key $value }",
            "}",
            "foreach file [get_files -quiet] {",
            "  set file_type \"\"",
            "  catch { set file_type [get_property FILE_TYPE $file] }",
            "  mcp_put $f file $file $file_type",
            "}",
            "foreach run [get_runs -quiet] {",
            "  set status \"\"",
            "  set progress \"\"",
            "  catch { set status [get_property STATUS $run] }",
            "  catch { set progress [get_property PROGRESS $run] }",
            "  mcp_put $f run $run $status $progress",
            "}",
            "foreach ip [get_ips -quiet] { mcp_put $f ip $ip }",
            "foreach bd [get_files -quiet -filter {FILE_TYPE == \"Block Designs\"}] { mcp_put $f block_design $bd }",
            "close $f",
            f"return \"summary={out_string}\"",
        ]
    )
