from __future__ import annotations

import re
import sys
import time
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if "-mode" in args and "batch" in args:
        print("VIVADO_MCP_VERSION=2023.1")
        return 0

    session_dir = _session_dir(args)
    inbox = session_dir / "inbox"
    running = session_dir / "running"
    done = session_dir / "done"
    inbox.mkdir(parents=True, exist_ok=True)
    running.mkdir(parents=True, exist_ok=True)
    done.mkdir(parents=True, exist_ok=True)
    _write_status(session_dir, "idle", "ready")

    deadline = time.time() + 60
    while time.time() < deadline:
        for command in sorted(inbox.glob("*.tcl")):
            target = running / command.name
            try:
                command.rename(target)
            except PermissionError:
                continue
            _write_status(session_dir, "busy", command.name)
            body = target.read_text(encoding="utf-8", errors="replace")
            result_path = done / f"{target.stem}.result.txt"
            result = _result_for(body)
            result_path.write_text(
                "\n".join(
                    [
                        f"command={target.name}",
                        "started=now",
                        "finished=now",
                        "code=0",
                        f"result={result}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            _write_status(session_dir, "idle", f"completed {command.name}")
            if "vivado_mcp_bridge_forever" in body:
                return 0
        time.sleep(0.05)
    return 2


def _session_dir(args: list[str]) -> Path:
    if "-tclargs" not in args:
        raise SystemExit("missing -tclargs")
    index = args.index("-tclargs") + 1
    return Path(args[index]).resolve()


def _write_status(session_dir: Path, state: str, detail: str) -> None:
    (session_dir / "status.txt").write_text(f"state={state}\ntime=now\ndetail={detail}\n", encoding="utf-8")


def _result_for(body: str) -> str:
    help_match = re.search(r"help \{([^}]+)\}", body)
    if help_match:
        return f"Usage: {help_match.group(1)} fake help"
    if "version -short" in body:
        return "version=2023.1"
    if "create_project" in body:
        return "project_created=fake"
    if "open_project" in body:
        return "project_opened=fake"
    bd_summary_match = re.search(r"set mcp_bd_summary_file \{([^}]+)\}", body)
    if bd_summary_match:
        path = Path(bd_summary_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "has_block_design\t1",
                    "current_bd_design\tdesign_1",
                    "block_design\tC:/fake/design_1.bd",
                    "cell\t/axi_gpio_0\tip\txilinx.com:ip:axi_gpio:2.0",
                    "port\t/gpio_tri_o\tO\tdata\t31\t0",
                    "net\t/net_gpio\t/axi_gpio_0/gpio_io_o,/gpio_tri_o",
                    "validation\t0\t",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"bd_summary={path}"
    if "bd_actions_applied=" in body or "create_bd_cell" in body:
        return "bd_actions_applied=1 current_bd_design=design_1"
    if "bd_validated=" in body or "validate_bd_design" in body:
        return "bd_validated=design_1"
    if "ip_outputs_generated" in body:
        return "ip_outputs_generated"
    if "generate_target" in body:
        return "bd_generated=C:/fake/design_1.bd wrapper=C:/fake/design_1_wrapper.v"
    if "create_bd_design" in body or "open_bd_design" in body:
        return "bd_design=design_1"
    sim_launch_match = re.search(r"set mcp_sim_launch_file \{([^}]+)\}", body)
    if sim_launch_match:
        path = Path(sim_launch_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        log_path = path.parent.parent / "xsim.log"
        log_path.write_text(
            "\n".join(
                [
                    "INFO: [XSIM 43-1] fake simulation started",
                    "WARNING: [VRFC 10-123] timescale missing",
                    "ERROR: [VRFC 10-2063] Module <dut> not found",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        path.write_text(
            "\n".join(
                [
                    "simulation\tsim_1\tbehavioral\t\t0",
                    f"log\txsim.log\t{log_path}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"simulation_launch={path}"
    if "simulation_prepared=" in body or "create_fileset -type {simulation}" in body:
        return "simulation_prepared=sim_1"
    hardware_match = re.search(r"set mcp_hw_file \{([^}]+)\}", body)
    if hardware_match:
        path = Path(hardware_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "server\tlocalhost:3121\tconnected",
                    "target\txilinx_tcf/Digilent/123\topen",
                    "device\txc7a35t_0\txc7a35tcpg236-1\t0123456789abcdef\t1\tReady",
                    "property\txc7a35t_0\tPROGRAM.IS_PROGRAMMED\t1",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"hardware={path}"
    nonproject_read_match = re.search(r"set mcp_nonproject_file \{([^}]+)\}", body)
    if nonproject_read_match:
        path = Path(nonproject_read_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "file\tverilog\tC:/fake/top.v\txil_defaultlib",
                    "file\tsystemverilog\tC:/fake/tb.sv\txil_defaultlib",
                    "constraint\tC:/fake/timing.xdc\tglobal",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"nonproject_sources={path}"
    nonproject_step_match = re.search(r"set mcp_nonproject_step_file \{([^}]+)\}", body)
    if nonproject_step_match:
        path = Path(nonproject_step_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        step_match = re.search(r"mcp_put \$f step \{([^}]+)\}", body)
        step = step_match.group(1) if step_match else "synth_design"
        checkpoint_match = re.search(r"write_checkpoint -force \{([^}]+)\}", body)
        if checkpoint_match:
            checkpoint_path = Path(checkpoint_match.group(1))
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text("FAKE DCP\n", encoding="utf-8")
        for report_path in re.findall(r"-file \{([^}]+\.rpt)\}", body):
            _write_fake_report(Path(report_path), body)
        rows = [
            f"step\t{step}\tok\t",
            "part\txc7a35tcpg236-1",
            "top\ttop",
        ]
        if checkpoint_match:
            rows.append(f"checkpoint\t{step}\t{checkpoint_match.group(1)}")
        for report_path in re.findall(r"-file \{([^}]+\.rpt)\}", body):
            report_type = "utilization" if "util" in report_path else "drc"
            rows.append(f"report\t{report_type}\t{report_path}")
        rows.append("")
        path.write_text("\n".join(rows), encoding="utf-8")
        return f"nonproject_step={path}"
    if "launch_runs" in body:
        return "status=complete"
    summary_match = re.search(r"set mcp_summary_file \{([^}]+)\}", body)
    if summary_match:
        path = Path(summary_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "has_project\t1",
                    "current_project\tfake_project",
                    "project_file\tC:/fake/fake_project.xpr",
                    "part\txc7a35tcpg236-1",
                    "top\ttop",
                    "file\tC:/fake/top.v\tVerilog",
                    "run\tsynth_1\tsynth_design Complete!\t100%",
                    "run\timpl_1\tNot started\t0%",
                    "ip\tfake_ip_0",
                    "block_design\tC:/fake/design_1.bd",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"summary={path}"
    fileset_list_match = re.search(r"set mcp_list_filesets_file \{([^}]+)\}", body)
    if fileset_list_match:
        path = Path(fileset_list_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "has_project\t1",
                    "current_project\tfake_project",
                    "fileset\tsources_1\tSource\t3\t1\t1\t1\ttop\t1",
                    "fileset\tsim_1\tSimulation\t1\t0\t1\t0\ttb_top\t0",
                    "fileset\tconstrs_1\tConstrs\t2\t1\t0\t1\ttop\t1",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"filesets={path}"
    fileset_desc_match = re.search(r"set mcp_desc_file \{([^}]+)\}", body)
    if fileset_desc_match:
        path = Path(fileset_desc_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "fileset\tsources_1",
                    "property\tFILESET_TYPE\tSource",
                    "property\tTOP\ttop",
                    "file\tC:/fake/top.v\tVerilog\txil_defaultlib\t0\t1\t1\t1",
                    "file\tC:/fake/alu.v\tVerilog\txil_defaultlib\t1\t1\t1\t1",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"fileset_desc={path}"
    constr_diag_match = re.search(r"set mcp_diag_file \{([^}]+)\}", body)
    if constr_diag_match:
        path = Path(constr_diag_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "has_project\t1",
                    "current_project\tfake_project",
                    "fileset\tconstrs_1\tConstrs\t1\t1\t0\t1\ttop",
                    "constraint_file\tconstrs_1\t0\tC:/fake/timing.xdc\tXDC",
                    "constraint_file\tconstrs_1\t1\tC:/fake/pinout.xdc\tXDC",
                    "marker\tcreate_clock\t1",
                    "marker\tset_false_path\t0",
                    "marker\tset_input_delay\t1",
                    "marker\tset_output_delay\t1",
                    "marker\tget_ports\t1",
                    "marker\tset_clock_groups\t0",
                    "file_marker\tconstrs_1\tC:/fake/timing.xdc\t1\t0\t0\t0\t0",
                    "file_marker\tconstrs_1\tC:/fake/pinout.xdc\t0\t0\t1\t1\t0",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"constraint_diag={path}"
    ip_catalog_match = re.search(r"set mcp_ip_catalog_file \{([^}]+)\}", body)
    if ip_catalog_match:
        path = Path(ip_catalog_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "catalog_ip\txilinx.com:ip:axi_gpio:2.0\taxi_gpio\tAXI GPIO\t2.0\txilinx.com\tip\t/AXI Peripheral\t1\n",
            encoding="utf-8",
        )
        return f"ip_catalog={path}"
    ip_list_match = re.search(r"set mcp_ip_list_file \{([^}]+)\}", body)
    if ip_list_match:
        path = Path(ip_list_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "has_project\t1",
                    "current_project\tfake_project",
                    "ip\taxi_gpio_0\txilinx.com:ip:axi_gpio:2.0\tC:/fake/axi_gpio_0.xci\t0\t1\t1\tGenerated",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"ips={path}"
    ip_desc_match = re.search(r"set mcp_ip_desc_file \{([^}]+)\}", body)
    if ip_desc_match:
        path = Path(ip_desc_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "ip\taxi_gpio_0\txilinx.com:ip:axi_gpio:2.0\tC:/fake/axi_gpio_0.xci\t0\t1\t1\tGenerated",
                    "property\tCONFIG.C_GPIO_WIDTH\t32",
                    "property\tGENERATE_SYNTH_CHECKPOINT\t1",
                    "target\tall",
                    "target\tsynthesis",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"ip_desc={path}"
    if "create_ip" in body:
        return "ip_created=C:/fake/axi_gpio_0.xci"
    if "upgrade_ip" in body:
        return "ip_upgraded=C:/fake/axi_gpio_0.xci"
    if "fileset_applied" in body or "set_property INCLUDE_DIRS" in body:
        return "fileset_applied"
    if "constraint_set_applied" in body or "current_fileset -constrset" in body or "reorder_files -fileset" in body:
        return "constraint_set_applied"
    create_fileset_match = re.search(r"create_fileset -type \{[^}]+\} \{([^}]+)\}", body)
    if create_fileset_match:
        return f"fileset={create_fileset_match.group(1)}"
    # Order matters: add_files (which also sets top) must be matched before
    # the top-only branch, otherwise add_sources returns "top=...".
    if "add_files" in body:
        return "sources_updated"
    if re.search(r"set_property top \{[^}]+\}", body):
        top_match = re.search(r"set_property top \{([^}]+)\}", body)
        return f"top={top_match.group(1) if top_match else ''}"
    if "set_property -dict" in body and "get_files" in body:
        return "file_properties_set"
    if "remove_files" in body:
        return "files_removed"
    report_match = re.search(r"-file \{([^}]+)\}", body)
    if report_match:
        path = Path(report_match.group(1))
        _write_fake_report(path, body)
        return f"report={path}"
    if "vivado_mcp_bridge_forever" in body:
        return "stopping"
    return "ok"


def _write_fake_report(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if "report_timing_summary" in body:
        text = "FAKE TIMING REPORT\nWNS(ns) -0.125\nTNS(ns) -1.250\nFailing Endpoints: 4\n"
    elif "report_utilization" in body:
        text = "FAKE UTILIZATION REPORT\n| DSPs | 95 | 100 | 95.0 |\n| CLB LUTs | 1,234 | 10,000 | 12.34 |\n"
    elif "report_drc" in body:
        text = "FAKE DRC REPORT\nERROR: [DRC NSTD-1] Unspecified I/O Standard\n"
    elif "report_power" in body:
        text = "FAKE POWER REPORT\nTotal On-Chip Power (W) 7.500\nDynamic (W) 6.000\nDevice Static (W) 1.500\n"
    elif "report_methodology" in body:
        text = "FAKE METHODOLOGY REPORT\nCRITICAL WARNING: [METHODOLOGY TIMING-1] Review clocks\n"
    else:
        text = "FAKE REPORT\nWNS 0.000\n"
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
