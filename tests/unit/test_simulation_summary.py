from __future__ import annotations

from pathlib import Path

from vivado_mcp.simulation_summary import analyze_simulation_audit, analyze_xsim_logs, parse_simulation_launch


def test_parse_simulation_launch_returns_logs_and_mode(tmp_path: Path) -> None:
    tsv = tmp_path / "simulation.tsv"
    tsv.write_text(
        "\n".join(
            [
                "simulation\tsim_1\tbehavioral\t\t0",
                "log\txsim.log\tC:/fake/xsim.log",
                "warning\tmissing_xvhdl_log",
                "",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_simulation_launch(tsv)

    assert parsed["simset"] == "sim_1"
    assert parsed["mode"] == "behavioral"
    assert parsed["type"] == ""
    assert parsed["scripts_only"] is False
    assert parsed["log_paths"] == [{"kind": "xsim.log", "path": "C:/fake/xsim.log"}]
    assert parsed["warnings"] == ["missing_xvhdl_log"]


def test_parse_simulation_launch_supports_type_column(tmp_path: Path) -> None:
    tsv = tmp_path / "simulation.tsv"
    tsv.write_text("simulation\tsim_1\tpost-synthesis\tfunctional\t1\n", encoding="utf-8")

    parsed = parse_simulation_launch(tsv)

    assert parsed["mode"] == "post-synthesis"
    assert parsed["type"] == "functional"
    assert parsed["scripts_only"] is True


def test_parse_simulation_launch_accepts_legacy_scripts_only_column(tmp_path: Path) -> None:
    tsv = tmp_path / "simulation.tsv"
    tsv.write_text("simulation\tsim_1\tbehavioral\t1\n", encoding="utf-8")

    parsed = parse_simulation_launch(tsv)

    assert parsed["type"] == ""
    assert parsed["scripts_only"] is True


def test_analyze_xsim_logs_classifies_errors(tmp_path: Path) -> None:
    log = tmp_path / "xsim.log"
    log.write_text(
        "\n".join(
            [
                "INFO: [XSIM 43-1] started",
                "WARNING: [VRFC 10-123] timescale missing",
                "ERROR: [VRFC 10-2063] Module <dut> not found",
                "FATAL: [XSIM 43-99] simulation aborted",
                "INFO: Simulation finished with 1 errors and 1 warnings",
            ]
        ),
        encoding="utf-8",
    )

    analysis = analyze_xsim_logs([log])

    assert analysis["ok"] is False
    assert analysis["worst_severity"] == "fatal"
    assert analysis["counts"]["error"] == 1
    categories = {issue["category"] for issue in analysis["issues"]}
    assert {"timescale", "unresolved_design_unit"}.issubset(categories)
    issue_ids = {issue["issue_id"] for issue in analysis["issues"]}
    assert {"sim.timescale_missing", "sim.module_not_found", "sim.runtime_failed"}.issubset(issue_ids)


def test_analyze_xsim_logs_ignores_summary_mentions(tmp_path: Path) -> None:
    log = tmp_path / "xsim.log"
    log.write_text("Simulation finished with 0 errors and 0 warnings\n", encoding="utf-8")

    analysis = analyze_xsim_logs([log])

    assert analysis["ok"] is True
    assert analysis["counts"]["error"] == 0
    assert analysis["counts"]["warning"] == 0


def test_analyze_xsim_logs_detects_ip_model_and_include_issues(tmp_path: Path) -> None:
    log = tmp_path / "xelab.log"
    log.write_text(
        "\n".join(
            [
                "ERROR: [VRFC 10-3195] cannot open include file defs.svh",
                "ERROR: [XSIM 43-3322] Static elaboration of top level Verilog design unit(s) in library work failed.",
                "ERROR: [XSIM 43-3431] Failed to link the design because IP simulation model is missing.",
            ]
        ),
        encoding="utf-8",
    )

    analysis = analyze_xsim_logs([log])

    issue_ids = {issue["issue_id"] for issue in analysis["issues"]}
    assert {"sim.include_file_missing", "sim.elaboration_failed", "sim.ip_model_missing"}.issubset(issue_ids)
    assert "vivado_simulation_audit" in analysis["suggested_next_tools"]


def test_analyze_simulation_audit_flags_fileset_and_ip_state() -> None:
    filesets = {
        "filesets": [
            {
                "name": "sim_1",
                "type": "Simulation",
                "top": "",
                "files": [
                    {
                        "path": "C:/demo/tb_top.sv",
                        "file_type": "SystemVerilog",
                        "is_enabled_simulation": True,
                    }
                ],
            }
        ]
    }
    ip = {
        "ips": [
            {
                "name": "axi_gpio_0",
                "generated": False,
                "upgrade_available": True,
            }
        ]
    }

    audit = analyze_simulation_audit(filesets=filesets, ip=ip, fileset="sim_1", top="tb_top")

    assert audit["ok"] is False
    issue_ids = {issue["issue_id"] for issue in audit["issues"]}
    assert {"sim.top_not_set", "sim.ip_outputs_not_generated", "sim.ip_upgrade_available"}.issubset(issue_ids)
    assert audit["recommendations"][0]["tool"] == "vivado_prepare_simulation"
