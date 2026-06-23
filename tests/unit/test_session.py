from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vivado_mcp.session import VivadoSessionManager


def test_session_raw_tcl_lifecycle(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    result = manager.run_tcl(session_ref=session_ref, tcl='return "version=[version -short]"', timeout_seconds=5)
    assert result["ok"] is True
    assert result["result"] == "version=2023.1"
    assert result["command_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")
    assert result["result_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")

    sessions = manager.list_sessions()
    assert [session["session_ref"] for session in sessions["sessions"]] == [session_ref]

    artifacts = manager.list_artifacts(session_ref)
    command_artifact = next(item for item in artifacts["artifacts"] if item["relative_path"].startswith("running/"))
    artifact_id = command_artifact["artifact_uri"].rsplit("/", 1)[-1]
    read = manager.read_artifact(session_ref, artifact_id)
    assert "version -short" in read["text"]

    stopped = manager.stop_session(session_ref, timeout_seconds=5)
    assert stopped["process_exit_code"] == 0


def test_safe_profile_blocks_raw_tcl_but_allows_workflow_tcl(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False, capability_profile="safe")
    session_ref = str(started["session_ref"])

    with pytest.raises(PermissionError):
        manager.run_tcl(session_ref=session_ref, tcl='return "no"', timeout_seconds=5)
    with pytest.raises(PermissionError):
        manager.source_tcl(session_ref=session_ref, script_path=str(tmp_path / "probe.tcl"), timeout_seconds=5)

    help_result = manager.tcl_command_help(session_ref=session_ref, command="create_project", timeout_seconds=5)
    assert help_result["ok"] is True
    assert help_result["result"] == "Usage: create_project fake help"

    created = manager.create_project(
        session_ref=session_ref,
        project_name="demo",
        project_dir=str(tmp_path / "demo"),
        part="xc7a35tcpg236-1",
        timeout_seconds=5,
    )
    assert created["ok"] is True
    assert created["result"] == "project_created=fake"
    manager.stop_session(session_ref, timeout_seconds=5)


def test_workflow_paths_must_stay_under_workspace(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    manager = VivadoSessionManager(default_workspace=workspace)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    with pytest.raises(PermissionError):
        manager.create_project(
            session_ref=session_ref,
            project_name="bad",
            project_dir=str(outside / "bad"),
            part="xc7a35tcpg236-1",
            timeout_seconds=5,
        )

    manager.stop_session(session_ref, timeout_seconds=5)


def test_report_writes_artifact(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    report = manager.report(session_ref=session_ref, report_type="timing_summary", timeout_seconds=5)
    assert report["ok"] is True
    assert "FAKE TIMING REPORT" in report["report_text"]
    assert report["report_summary"]["parsed"] is True
    assert report["report_summary"]["status"] == "fail"
    manager.stop_session(session_ref, timeout_seconds=5)


def test_analyze_reports_generates_diagnostics(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    result = manager.analyze_reports(
        session_ref=session_ref,
        report_types=["timing_summary", "utilization", "drc", "power", "methodology"],
        timeout_seconds=5,
    )

    issue_ids = [issue["issue_id"] for issue in result["analysis"]["issues"]]
    assert result["ok"] is True
    assert result["analysis"]["ok"] is False
    assert issue_ids[:3] == ["drc.io_standard_missing", "timing.unconstrained_paths", "timing.setup_failed"]
    assert "timing.hold_failed" in issue_ids
    assert "timing.clock_interaction_issue" in issue_ids
    assert "utilization.resource_pressure" in issue_ids
    assert "power.high_total" in issue_ids
    assert "power.thermal_risk" in issue_ids
    assert "methodology.clocking_issue" in issue_ids
    assert result["analysis_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")
    assert result["reports"]["timing_summary"]["report_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")
    manager.stop_session(session_ref, timeout_seconds=5)


def test_nonproject_workflow_reads_sources_and_runs_steps(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    top_v = tmp_path / "top.v"
    tb_sv = tmp_path / "tb.sv"
    xdc = tmp_path / "timing.xdc"
    top_v.write_text("module top; endmodule\n", encoding="utf-8")
    tb_sv.write_text("module tb; endmodule\n", encoding="utf-8")
    xdc.write_text("create_clock -period 10 [get_ports clk]\n", encoding="utf-8")
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    read = manager.nonproject_read_sources(
        session_ref=session_ref,
        verilog=[str(top_v)],
        systemverilog=[str(tb_sv)],
        xdc=[str(xdc)],
        library="xil_defaultlib",
        timeout_seconds=5,
    )
    assert read["ok"] is True
    assert read["nonproject"]["file_count"] == 2
    assert read["nonproject"]["constraint_count"] == 1

    synth = manager.nonproject_run_step(
        session_ref=session_ref,
        step="synth_design",
        part="xc7a35tcpg236-1",
        top="top",
        checkpoint_name="synth.dcp",
        report_types=["utilization", "drc"],
        timeout_seconds=5,
    )
    assert synth["ok"] is True
    assert synth["nonproject"]["steps"][0]["name"] == "synth_design"
    assert synth["checkpoint_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")
    assert synth["report_summaries"]["utilization"]["parsed"] is True
    assert synth["report_summaries"]["drc"]["parsed"] is True

    for step in ("opt_design", "place_design", "route_design"):
        result = manager.nonproject_run_step(
            session_ref=session_ref,
            step=step,
            checkpoint_name=f"{step}.dcp",
            report_types=["drc"],
            timeout_seconds=5,
        )
        assert result["ok"] is True
        assert result["nonproject"]["steps"][0]["name"] == step

    manager.stop_session(session_ref, timeout_seconds=5)


def test_hardware_discovery_requires_confirmation_and_returns_devices(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    with pytest.raises(PermissionError):
        manager.hardware_discover(session_ref=session_ref, timeout_seconds=5)

    discovered = manager.hardware_discover(
        session_ref=session_ref,
        expect_hardware_access=True,
        hw_server_url="localhost:3121",
        target="*Digilent*",
        refresh=True,
        timeout_seconds=5,
        capture_diff=True,
    )

    assert discovered["ok"] is True
    assert discovered["expect_hardware_access"] is True
    assert discovered["hardware"]["server_count"] == 1
    assert discovered["hardware"]["devices"][0]["part"] == "xc7a35tcpg236-1"
    assert discovered["hardware"]["devices"][0]["programmed"] is True
    assert discovered["state_diff"]["ok"] is True

    manager.stop_session(session_ref, timeout_seconds=5)


def test_project_summary_returns_structured_state(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    result = manager.project_summary(session_ref=session_ref, timeout_seconds=5)
    assert result["ok"] is True
    assert result["summary_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")
    summary = result["project_summary"]
    assert summary["current_project"] == "fake_project"
    assert summary["files"][0]["file_type"] == "Verilog"
    assert summary["runs"][0]["name"] == "synth_1"
    assert summary["ips"] == ["fake_ip_0"]

    manager.stop_session(session_ref, timeout_seconds=5)


def test_ip_workflow_returns_structured_state(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    catalog = manager.ip_catalog_search(session_ref=session_ref, query="axi_gpio", timeout_seconds=5)
    assert catalog["ok"] is True
    assert catalog["catalog"]["ips"][0]["vlnv"] == "xilinx.com:ip:axi_gpio:2.0"

    with pytest.raises(ValueError):
        manager.ip_create(
            session_ref=session_ref,
            module_name="bad_ip",
            output_dir=str(tmp_path / "ip"),
            vendor="xilinx.com",
            library="ip",
            ip_name="axi_gpio",
            timeout_seconds=5,
        )

    created = manager.ip_create(
        session_ref=session_ref,
        vlnv="xilinx.com:ip:axi_gpio:2.0",
        module_name="axi_gpio_0",
        output_dir=str(tmp_path / "ip"),
        properties={"CONFIG.C_GPIO_WIDTH": 32},
        timeout_seconds=5,
        capture_diff=True,
    )
    assert created["ok"] is True
    assert created["result"] == "ip_created=C:/fake/axi_gpio_0.xci"
    assert created["state_diff"]["ok"] is True

    dry_created = manager.ip_create(
        session_ref=session_ref,
        vlnv="xilinx.com:ip:axi_gpio:2.0",
        module_name="axi_gpio_0",
        output_dir=str(tmp_path / "ip"),
        properties={"CONFIG.C_GPIO_WIDTH": 32},
        timeout_seconds=5,
        dry_run=True,
    )
    assert dry_created["ok"] is True
    assert dry_created["dry_run"] is True
    assert dry_created["plan"]["actions"][0]["action"] == "create_ip"
    assert "create_ip -vlnv" in dry_created["plan"]["tcl_preview"]
    assert dry_created["plan"]["recommended_docs"][0]["doc_id"] == "UG896"

    created_from_parts = manager.ip_create(
        session_ref=session_ref,
        module_name="axi_gpio_1",
        output_dir=str(tmp_path / "ip"),
        vendor="xilinx.com",
        library="ip",
        ip_name="axi_gpio",
        version="2.0",
        timeout_seconds=5,
    )
    assert created_from_parts["ok"] is True

    listed = manager.ip_list(session_ref=session_ref, timeout_seconds=5)
    assert listed["ips"]["ips"][0]["name"] == "axi_gpio_0"
    assert listed["ips"]["ips"][0]["upgrade_available"] is True
    assert listed["ips"]["upgrade_check"]["upgrade_needed_count"] == 1

    described = manager.ip_describe(session_ref=session_ref, name="axi_gpio_0", timeout_seconds=5)
    assert described["ip"]["properties"]["CONFIG.C_GPIO_WIDTH"] == "32"
    assert "synthesis" in described["ip"]["targets"]

    upgrade_check = manager.ip_upgrade_check(session_ref=session_ref, timeout_seconds=5)
    assert upgrade_check["ok"] is False
    assert upgrade_check["upgrade_needed_count"] == 1
    assert upgrade_check["recommendations"][0]["tool"] == "vivado_describe_ip"

    with pytest.raises(PermissionError):
        manager.ip_upgrade(session_ref=session_ref, name="axi_gpio_0", timeout_seconds=5)

    upgraded = manager.ip_upgrade(
        session_ref=session_ref,
        name="axi_gpio_0",
        expect_upgrade=True,
        timeout_seconds=5,
        capture_diff=True,
    )
    assert upgraded["ok"] is True
    assert upgraded["result"] == "ip_upgraded=C:/fake/axi_gpio_0.xci"
    assert upgraded["state_diff"]["ok"] is True

    generated = manager.ip_generate_outputs(
        session_ref=session_ref,
        name="axi_gpio_0",
        targets=["all"],
        timeout_seconds=5,
        capture_diff=True,
    )
    assert generated["ok"] is True
    assert generated["result"] == "ip_outputs_generated"
    assert generated["state_diff"]["ok"] is True

    manager.stop_session(session_ref, timeout_seconds=5)


def test_simulation_workflow_prepares_launches_and_analyzes_logs(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    tb = tmp_path / "tb_top.sv"
    tb.write_text("module tb_top; endmodule\n", encoding="utf-8")
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    prepared = manager.prepare_simulation(
        session_ref=session_ref,
        fileset="sim_1",
        testbench_files=[str(tb)],
        top="tb_top",
        defines=["SIM=1"],
        timeout_seconds=5,
        capture_diff=True,
    )
    assert prepared["ok"] is True
    assert prepared["result"] == "simulation_prepared=sim_1"
    assert prepared["state_diff"]["ok"] is True

    launched = manager.launch_simulation(session_ref=session_ref, fileset="sim_1", timeout_seconds=5, capture_diff=True)
    assert launched["ok"] is True
    assert launched["simulation"]["simset"] == "sim_1"
    assert launched["log_analysis"]["ok"] is False
    assert launched["log_analysis"]["counts"]["error"] == 1
    assert launched["state_diff"]["ok"] is True
    assert "reports" in launched["state_diff"]["diff"]["summary"]["changed_domains"]

    analyzed = manager.analyze_xsim_logs(
        session_ref=session_ref,
        launch_summary_artifact=str(launched["summary_artifact_uri"]),
        timeout_seconds=5,
    )
    assert analyzed["analysis"]["worst_severity"] == "error"
    assert analyzed["analysis"]["issues"][0]["path"].endswith("xsim.log")

    manager.stop_session(session_ref, timeout_seconds=5)


def test_state_capture_and_diff_writes_artifacts(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    before = manager.capture_state(session_ref=session_ref, label="before", timeout_seconds=5)
    after = manager.capture_state(session_ref=session_ref, label="after", timeout_seconds=5)

    assert before["ok"] is True
    assert before["snapshot_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")
    assert before["state"]["project"]["current_project"] == "fake_project"
    assert before["state"]["ip"]["ips"][0]["name"] == "axi_gpio_0"
    assert before["state"]["reports"]["count"] == 0
    assert after["digest"] == before["digest"]

    before_artifact = before["snapshot_artifact_uri"].rsplit("/", 1)[-1]
    after_artifact = after["snapshot_artifact_uri"].rsplit("/", 1)[-1]
    diff = manager.state_diff(
        session_ref=session_ref,
        before_artifact_id=before["snapshot_artifact_uri"],
        after_artifact_id=after_artifact,
    )

    assert diff["ok"] is True
    assert diff["changed"] is False
    assert diff["diff"]["version"] == 2
    assert diff["diff"]["summary"]["change_count"] == 0
    assert diff["diff_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")

    manager.stop_session(session_ref, timeout_seconds=5)


def test_capture_diff_wraps_raw_tcl_and_structured_tools(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    raw = manager.run_tcl(
        session_ref=session_ref,
        tcl='return "version=[version -short]"',
        timeout_seconds=5,
        capture_diff=True,
    )

    assert raw["ok"] is True
    assert raw["state_before"]["snapshot_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")
    assert raw["state_after"]["snapshot_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")
    assert raw["state_diff"]["ok"] is True
    assert raw["state_diff"]["diff"]["summary"]["changed_domains"] == []
    assert raw["state_diff"]["diff_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")

    top_v = tmp_path / "top.v"
    top_v.write_text("// top\n", encoding="utf-8")
    added = manager.add_sources(
        session_ref=session_ref,
        sources=[str(top_v)],
        timeout_seconds=5,
        capture_diff=True,
    )

    assert added["ok"] is True
    assert added["result"] == "sources_updated"
    assert added["state_diff"]["ok"] is True
    assert "summary" in added["state_diff"]["diff"]

    manager.stop_session(session_ref, timeout_seconds=5)


def test_block_design_workflow_uses_generic_tools(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    opened = manager.bd_open_or_create(session_ref=session_ref, design_name="design_1", timeout_seconds=5)
    assert opened["ok"] is True
    assert opened["result"] == "bd_design=design_1"

    applied = manager.bd_apply(
        session_ref=session_ref,
        design_name="design_1",
        actions=[
            {"action": "create_cell", "name": "axi_gpio_0", "vlnv": "xilinx.com:ip:axi_gpio:*"},
            {"action": "create_port", "name": "gpio_tri_o", "direction": "O", "from": 31, "to": 0},
        ],
        timeout_seconds=5,
    )
    assert applied["ok"] is True
    assert "bd_actions_applied" in applied["result"]

    summary = manager.bd_summary(session_ref=session_ref, design_name="design_1", validate=True, timeout_seconds=5)
    assert summary["ok"] is True
    assert summary["summary_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")
    assert summary["bd_summary"]["current_bd_design"] == "design_1"
    assert summary["bd_summary"]["cells"][0]["vlnv"] == "xilinx.com:ip:axi_gpio:2.0"

    generated = manager.bd_generate(session_ref=session_ref, design_name="design_1", timeout_seconds=5)
    assert generated["ok"] is True
    assert "bd_generated" in generated["result"]

    manager.stop_session(session_ref, timeout_seconds=5)


def test_open_gui_session_reports_visible_window_without_activating_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)

    def fake_wait_for_gui(**kwargs):
        assert kwargs["timeout_seconds"] == 3
        assert kwargs["activate"] is False
        return {
            "requested": True,
            "platform": "win32",
            "platform_supported": True,
            "visible": True,
            "activated": True,
            "windows": [{"handle": 123, "pid": kwargs["root_pid"], "title": "Vivado 2023.1"}],
            "detail": "Matched 1 Vivado GUI window.",
        }

    def fake_probe_gui(**kwargs):
        return {
            "requested": True,
            "platform": "win32",
            "platform_supported": True,
            "visible": True,
            "activated": False,
            "windows": [{"handle": 123, "pid": kwargs["root_pid"], "title": "Vivado 2023.1"}],
            "detail": "Matched 1 Vivado GUI window.",
        }

    monkeypatch.setattr("vivado_mcp.session.wait_for_vivado_gui", fake_wait_for_gui)
    monkeypatch.setattr("vivado_mcp.session.probe_vivado_gui", fake_probe_gui)

    started = manager.start_session(
        vivado_path=str(wrapper),
        open_gui=True,
        gui_wait_seconds=3,
    )
    session_ref = str(started["session_ref"])

    assert started["gui"]["visible"] is True
    assert started["state"]["gui"]["visible"] is True

    state = manager.session_state(session_ref)
    assert state["gui"]["windows"][0]["title"] == "Vivado 2023.1"

    manager.stop_session(session_ref, timeout_seconds=5)


def test_open_project_in_gui_updates_project_hint_without_focusing_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    project = tmp_path / "demo.xpr"
    project.write_text("", encoding="utf-8")
    manager = VivadoSessionManager(default_workspace=tmp_path)
    wait_calls: list[dict[str, object]] = []

    def fake_wait_for_gui(**kwargs):
        wait_calls.append(kwargs)
        return {
            "requested": True,
            "platform": "win32",
            "platform_supported": True,
            "visible": True,
            "activated": kwargs["activate"],
            "windows": [{"handle": 456, "pid": kwargs["root_pid"], "title": "demo - Vivado 2023.1"}],
            "detail": "Matched 1 Vivado GUI window.",
        }

    def fake_probe_gui(**kwargs):
        return {
            "requested": True,
            "platform": "win32",
            "platform_supported": True,
            "visible": True,
            "activated": False,
            "windows": [{"handle": 456, "pid": kwargs["root_pid"], "title": "demo - Vivado 2023.1"}],
            "detail": "Matched 1 Vivado GUI window.",
        }

    monkeypatch.setattr("vivado_mcp.session.wait_for_vivado_gui", fake_wait_for_gui)
    monkeypatch.setattr("vivado_mcp.session.probe_vivado_gui", fake_probe_gui)

    started = manager.start_session(vivado_path=str(wrapper), open_gui=True, gui_wait_seconds=0)
    session_ref = str(started["session_ref"])

    result = manager.open_project(
        session_ref=session_ref,
        project_path=str(project),
        timeout_seconds=5,
        gui_wait_seconds=5,
    )

    assert result["ok"] is True
    assert result["gui"]["visible"] is True
    assert result["gui"]["activated"] is False
    assert any("demo.xpr" in call["title_hints"] for call in wait_calls)

    manager.stop_session(session_ref, timeout_seconds=5)


def test_fileset_and_source_workflow_returns_structured_state(tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    started = manager.start_session(vivado_path=str(wrapper), open_gui=False)
    session_ref = str(started["session_ref"])

    top_v = tmp_path / "top.v"
    alu_v = tmp_path / "alu.v"
    top_v.write_text("// top\n", encoding="utf-8")
    alu_v.write_text("// alu\n", encoding="utf-8")
    timing_xdc = tmp_path / "timing.xdc"
    pinout_xdc = tmp_path / "pinout.xdc"
    timing_xdc.write_text("create_clock -name clk -period 10 [get_ports clk]\n", encoding="utf-8")
    pinout_xdc.write_text("set_property PACKAGE_PIN E3 [get_ports clk]\n", encoding="utf-8")

    filesets = manager.list_filesets(session_ref=session_ref, timeout_seconds=5)
    assert filesets["ok"] is True
    assert filesets["filesets"]["has_project"] is True
    sources = {row["name"]: row for row in filesets["filesets"]["filesets"]}
    assert "sources_1" in sources
    assert "constrs_1" in sources
    assert sources["sources_1"]["file_count"] == 3

    created = manager.create_fileset(
        session_ref=session_ref,
        name="constrs_extra",
        kind="constrs",
        timeout_seconds=5,
    )
    assert created["ok"] is True
    assert created["result"] == "fileset=constrs_extra"

    described = manager.describe_fileset(session_ref=session_ref, name="sources_1", timeout_seconds=5)
    assert described["ok"] is True
    assert described["fileset_summary"]["name"] == "sources_1"
    assert described["fileset_summary"]["properties"]["TOP"] == "top"
    assert described["fileset_summary"]["files"][0]["file_type"] == "Verilog"

    added = manager.add_sources(
        session_ref=session_ref,
        sources=[str(alu_v)],
        constraints=[str(timing_xdc)],
        top="alu",
        defines=["DEBUG=1"],
        library="work",
        file_type="Verilog",
        used_in=["synthesis", "implementation"],
        timeout_seconds=5,
    )
    assert added["ok"] is True
    assert added["result"] == "sources_updated"

    props = manager.set_file_properties(
        session_ref=session_ref,
        paths=[str(alu_v)],
        properties={"LIBRARY": "custom_lib", "PROCESSING_ORDER": 5},
        timeout_seconds=5,
    )
    assert props["ok"] is True
    assert props["result"] == "file_properties_set"
    assert props["expect_destructive"] is True

    top = manager.set_top(session_ref=session_ref, top="alu", fileset="sources_1", timeout_seconds=5)
    assert top["ok"] is True
    assert top["result"] == "top=alu"
    assert top["expect_destructive"] is True

    removed = manager.remove_sources(session_ref=session_ref, paths=[str(alu_v)], timeout_seconds=5)
    assert removed["ok"] is True
    assert removed["result"] == "files_removed"
    assert removed["expect_destructive"] is True

    diag = manager.constraint_diagnostics(session_ref=session_ref, timeout_seconds=5)
    assert diag["ok"] is True
    diagnostics = diag["diagnostics"]
    assert diagnostics["has_project"] is True
    assert any(fs["name"] == "constrs_1" for fs in diagnostics["constrs_filesets"])
    assert any(cf["path"].endswith("timing.xdc") for cf in diagnostics["constraint_files"])
    assert diagnostics["xdc_markers"]["create_clock"] == 1
    assert diagnostics["xdc_markers"]["set_input_delay"] == 1
    assert diagnostics["xdc_markers"]["get_ports"] == 1
    assert diagnostics["xdc_file_markers"][0]["path"].endswith("timing.xdc")

    audit = manager.source_audit(session_ref=session_ref, timeout_seconds=5)
    assert audit["ok"] is True
    assert audit["audit"]["summary"]["fileset_count"] >= 1
    assert audit["audit_artifact_uri"].startswith(f"vivado://sessions/{session_ref}/artifacts/")

    order = manager.xdc_order_check(session_ref=session_ref, timeout_seconds=5)
    assert order["ok"] is True
    assert "constrs_1" in order["order"]["filesets"]

    applied_fileset = manager.fileset_apply(
        session_ref=session_ref,
        fileset="sources_1",
        include_dirs=[str(tmp_path / "include")],
        defines=["DEBUG=1"],
        top="alu",
        timeout_seconds=5,
        capture_diff=True,
    )
    assert applied_fileset["ok"] is True
    assert applied_fileset["result"] == "fileset_applied"
    assert applied_fileset["state_diff"]["ok"] is True

    dry_fileset = manager.fileset_apply(
        session_ref=session_ref,
        fileset="sources_1",
        include_dirs=[str(tmp_path / "include")],
        defines=["DEBUG=1"],
        top="alu",
        timeout_seconds=5,
        dry_run=True,
    )
    assert dry_fileset["dry_run"] is True
    assert dry_fileset["plan"]["actions"][0]["action"] == "set_include_dirs"
    assert dry_fileset["plan"]["would_execute_tcl"] is True

    applied_constraints = manager.constraint_set_apply(
        session_ref=session_ref,
        fileset="constrs_extra",
        create_if_missing=True,
        add=[str(timing_xdc)],
        used_in=["synthesis", "implementation"],
        reorder=[str(timing_xdc)],
        active=True,
        timeout_seconds=5,
        capture_diff=True,
    )
    assert applied_constraints["ok"] is True
    assert applied_constraints["result"] == "constraint_set_applied"
    assert applied_constraints["state_diff"]["ok"] is True

    dry_constraints = manager.constraint_set_apply(
        session_ref=session_ref,
        fileset="constrs_extra",
        add=[str(timing_xdc)],
        reorder=[str(timing_xdc)],
        timeout_seconds=5,
        dry_run=True,
    )
    assert dry_constraints["dry_run"] is True
    assert dry_constraints["plan"]["actions"][0]["action"] == "add_xdc"
    assert dry_constraints["plan"]["recommendations"][0]["tool"] == "vivado_xdc_order_check"

    manager.stop_session(session_ref, timeout_seconds=5)


def test_focus_gui_explicitly_activates_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)
    wait_calls: list[dict[str, object]] = []

    def fake_wait_for_gui(**kwargs):
        wait_calls.append(kwargs)
        return {
            "requested": True,
            "platform": "win32",
            "platform_supported": True,
            "visible": True,
            "activated": kwargs["activate"],
            "windows": [{"handle": 456, "pid": kwargs["root_pid"], "title": "Vivado 2023.1"}],
            "detail": "Matched 1 Vivado GUI window.",
        }

    monkeypatch.setattr("vivado_mcp.session.wait_for_vivado_gui", fake_wait_for_gui)
    monkeypatch.setattr("vivado_mcp.session.probe_vivado_gui", fake_wait_for_gui)

    started = manager.start_session(vivado_path=str(wrapper), open_gui=True, gui_wait_seconds=0)
    focused = manager.focus_gui(str(started["session_ref"]), timeout_seconds=5)

    assert focused["gui"]["visible"] is True
    assert focused["gui"]["activated"] is True
    assert wait_calls[-1]["activate"] is True

    manager.stop_session(str(started["session_ref"]), timeout_seconds=5)


def test_stop_session_cleans_up_managed_gui_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    manager = VivadoSessionManager(default_workspace=tmp_path)

    def fake_wait_for_gui(**kwargs):
        return {
            "requested": True,
            "platform": "win32",
            "platform_supported": True,
            "visible": True,
            "activated": False,
            "watched_pids": [999],
            "windows": [{"handle": 789, "pid": 999, "title": "Vivado 2023.1"}],
            "detail": "Matched 1 Vivado GUI window.",
        }

    monkeypatch.setattr("vivado_mcp.session.wait_for_vivado_gui", fake_wait_for_gui)
    monkeypatch.setattr("vivado_mcp.session.probe_vivado_gui", fake_wait_for_gui)
    monkeypatch.setattr(
        "vivado_mcp.session._terminate_processes",
        lambda pids, timeout_seconds=5: {"terminated_pids": sorted(pids), "errors": []},
    )

    started = manager.start_session(vivado_path=str(wrapper), open_gui=True, gui_wait_seconds=0)
    stopped = manager.stop_session(str(started["session_ref"]), timeout_seconds=5)

    assert stopped["process_exit_code"] == 0
    assert stopped["gui_cleanup"]["terminated_pids"] == [999]


def _make_fake_wrapper(tmp_path: Path) -> Path:
    fake = Path(__file__).resolve().parents[1] / "fixtures" / "fake_vivado.py"
    wrapper = tmp_path / "vivado.bat"
    wrapper.write_text(f'@echo off\n"{sys.executable}" "{fake}" %*\n', encoding="utf-8")
    return wrapper
