from __future__ import annotations

import json
import os
import hashlib
import subprocess
import sys
import time
from pathlib import Path

from vivado_cli import cli
from vivado_cli import cli_core


def test_cli_tcl_review_reports_destructive_command(capsys) -> None:
    code = cli.main(["tcl", "review", "--tcl", "file delete -force ./build"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requires_expect_destructive"] is True
    assert any("file delete" in risk["matches"] for risk in payload["risks"])
    assert payload["source"]["kind"] == "tcl"
    assert payload["source"]["line_count"] == 1


def test_cli_tcl_help_includes_official_doc_search_for_core_commands(capsys) -> None:
    code = cli.main(["tcl", "help", "create_clock"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["command"] == "create_clock"
    assert payload["official_doc_topic"] == "constraints"
    assert payload["official_search"]["topic"] == "constraints"
    assert payload["official_search"]["ok"] is True
    assert payload["coverage"]["coverage_status"] == "raw_tcl"
    assert payload["recommended_sequence"][0]["step"] == "official_docs"


def test_cli_tcl_review_accepts_positional_file(tmp_path: Path, capsys) -> None:
    script = tmp_path / "program_device.tcl"
    script_text = "program_hw_devices [current_hw_device]\n"
    script.write_text(script_text, encoding="utf-8")

    code = cli.main(["tcl", "review", str(script)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requires_expect_destructive"] is True
    assert any("program_hw_devices" in risk["matches"] for risk in payload["risks"])
    assert payload["source"]["kind"] == "path"
    assert payload["source"]["path"] == str(script.resolve())
    assert payload["source"]["sha256"] == hashlib.sha256(script_text.encode("utf-8")).hexdigest()


def test_cli_tcl_review_file_source_reports_source_metadata(tmp_path: Path, capsys) -> None:
    script = tmp_path / "reset_run.tcl"
    script_text = "reset_run synth_1\n"
    script.write_text(script_text, encoding="utf-8")

    code = cli.main(["tcl", "review", "--file", str(script)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"]["kind"] == "file"
    assert payload["source"]["path"] == str(script.resolve())
    assert payload["source"]["line_count"] == 1
    assert payload["source"]["sha256"] == hashlib.sha256(script_text.encode("utf-8")).hexdigest()


def test_cli_tcl_review_reads_stdin(capsys, monkeypatch) -> None:
    script_text = "return ok\n"
    monkeypatch.setattr(sys, "stdin", _Stdin(script_text))

    code = cli.main(["tcl", "review", "--stdin"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["source"]["kind"] == "stdin"
    assert payload["source"]["line_count"] == 1
    assert payload["source"]["sha256"] == hashlib.sha256(script_text.encode("utf-8")).hexdigest()


def test_cli_accepts_pretty_after_subcommand(capsys) -> None:
    code = cli.main(["tcl", "review", "--tcl", "return ok", "--pretty"])

    assert code == 0
    output = capsys.readouterr().out
    assert output.startswith("{\n")
    assert json.loads(output)["ok"] is True


def test_cli_lists_packaged_skills(capsys) -> None:
    code = cli.main(["skills", "list"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    skill_ids = [skill["skill_id"] for skill in payload["skills"]]
    assert payload["ok"] is True
    assert "project-build-flow" in skill_ids
    assert "raw-tcl-expert" in skill_ids


def test_cli_get_skill_returns_markdown_body(capsys) -> None:
    code = cli.main(["skills", "get", "gui-session"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["skill"]["skill_id"] == "gui-session"
    assert "GUI Session" in payload["skill"]["body"]


def test_cli_help_topic_returns_structured_guidance(capsys) -> None:
    code = cli.main(["help", "topic", "project-build"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["help"]["topic"] == "project_flow"
    assert "vivado://skills/project-build-flow" in payload["help"]["related_resources"]


def test_cli_tools_list_and_describe(capsys) -> None:
    code = cli.main(["tools", "list", "--query", "launch-local"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert [tool["command"] for tool in payload["tools"]] == ["run launch-local"]

    code = cli.main(["tools", "describe", "run", "launch-local"])
    assert code == 0
    described = json.loads(capsys.readouterr().out)
    tool = described["tool"]
    assert described["ok"] is True
    assert tool["tool_id"] == "vivado_run_launch_local"
    assert tool["requires_session"] is True
    assert tool["details"]["interface"] == "CLI command"

    code = cli.main(["tools", "list", "--query", "capture-ila"])
    assert code == 0
    hw_tools = json.loads(capsys.readouterr().out)
    assert [tool["command"] for tool in hw_tools["tools"]] == ["hw capture-ila"]

    code = cli.main(["tools", "describe", "hw", "spi-read"])
    assert code == 0
    spi_tool = json.loads(capsys.readouterr().out)["tool"]
    assert spi_tool["tool_id"] == "vivado_hw_spi_read"
    assert spi_tool["risk_level"] == "hardware_access"

    code = cli.main(["tools", "describe", "hw", "list-debug-cores"])
    assert code == 0
    debug_tool = json.loads(capsys.readouterr().out)["tool"]
    assert debug_tool["tool_id"] == "vivado_hw_list_debug_cores"
    assert debug_tool["risk_level"] == "hardware_access"

    code = cli.main(["tools", "describe", "hw", "vio-read"])
    assert code == 0
    vio_tool = json.loads(capsys.readouterr().out)["tool"]
    assert vio_tool["tool_id"] == "vivado_hw_vio_read"
    assert vio_tool["risk_level"] == "hardware_access"

    code = cli.main(["tools", "describe", "hw", "vio-write"])
    assert code == 0
    vio_write_tool = json.loads(capsys.readouterr().out)["tool"]
    assert vio_write_tool["tool_id"] == "vivado_hw_vio_write"
    assert vio_write_tool["risk_level"] == "hardware_write"


def test_cli_adopts_existing_bridge_session(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    workspace = tmp_path / "workspace"
    legacy_workspace = tmp_path / "legacy"

    assert (
        cli.main(
            [
                "--workspace",
                str(legacy_workspace),
                "session",
                "start",
                "--vivado-path",
                str(wrapper),
                "--no-gui",
                "--timeout",
                "5",
            ]
        )
        == 0
    )
    started = json.loads(capsys.readouterr().out)
    source_session_dir = started["session_dir"]
    source_pid = started["process_pid"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "session",
            "adopt",
            "--session-dir",
            source_session_dir,
            "--pid",
            str(source_pid),
            "--session-ref",
            "adopted",
            "--vivado-path",
            str(wrapper),
            "--no-gui",
        ]
    )
    assert code == 0
    adopted = json.loads(capsys.readouterr().out)
    assert adopted["session_ref"] == "adopted"
    assert adopted["session_dir"] == source_session_dir
    assert (workspace / ".vivado_cli" / "sessions" / "adopted" / "session.json").exists()

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "session",
            "run-tcl",
            "--session",
            "adopted",
            "--tcl",
            'return "version=[version -short]"',
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["result"] == "version=2023.1"

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", "adopted", "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_marks_legacy_mcp_bridge_and_refuses_tcl(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    legacy = tmp_path / ".vivado_mcp" / "sessions" / "legacy"
    for child in ("inbox", "running", "done"):
        (legacy / child).mkdir(parents=True, exist_ok=True)
    (legacy / "process.log").write_text("vivado -source C:/tools/mcp_bridge.tcl\n", encoding="utf-8")
    (legacy / "status.txt").write_text("state=idle\ntime=now\ndetail=ready\n", encoding="utf-8")
    (legacy / "inbox" / "stale.tcl").write_text("return stale\n", encoding="utf-8")

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "session",
            "adopt",
            "--session-dir",
            str(legacy),
            "--pid",
            str(os.getpid()),
            "--session-ref",
            "legacy",
            "--no-gui",
        ]
    )

    assert code == 0
    adopted = json.loads(capsys.readouterr().out)
    assert adopted["bridge_kind"] == "mcp_legacy"
    assert adopted["bridge_compatible"] is False
    assert adopted["bridge"]["pending_inbox"] == 1
    assert adopted["bridge"]["incomplete_commands"] == 0
    assert adopted["bridge"]["recommendations"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "session",
            "run-tcl",
            "--session",
            "legacy",
            "--tcl",
            'return "version=[version -short]"',
            "--timeout",
            "5",
        ]
    )

    assert code == 1
    rejected = json.loads(capsys.readouterr().err)
    assert rejected["type"] == "RuntimeError"
    assert "bridge_kind='mcp_legacy'" in rejected["error"]


def test_cli_session_lifecycle_uses_persistent_record(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    workspace = tmp_path / "workspace"

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "session",
            "start",
            "--vivado-path",
            str(wrapper),
            "--no-gui",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    started = json.loads(capsys.readouterr().out)
    session_ref = started["session_ref"]
    assert started["status"]["state"] == "idle"
    assert (workspace / ".vivado_cli" / "sessions" / session_ref / "session.json").exists()

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "session",
            "run-tcl",
            "--session",
            session_ref,
            "--tcl",
            'return "version=[version -short]"',
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["result"] == "version=2023.1"

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "session",
            "open-project",
            "--session",
            session_ref,
            str(workspace / "demo.xpr"),
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    opened = json.loads(capsys.readouterr().out)
    assert opened["ok"] is True
    assert opened["state"]["current_project_path"].endswith("demo.xpr")

    code = cli.main(["--workspace", str(workspace), "session", "list"])
    assert code == 0
    listed = json.loads(capsys.readouterr().out)
    assert [session["session_ref"] for session in listed["sessions"]] == [session_ref]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "session",
            "stop",
            "--session",
            session_ref,
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    stopped = json.loads(capsys.readouterr().out)
    assert stopped["process_running"] is False


def test_cli_run_tcl_reads_stdin(tmp_path: Path, capsys, monkeypatch) -> None:
    wrapper = _make_fake_wrapper(tmp_path)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]
    monkeypatch.setattr(sys, "stdin", _Stdin('return "version=[version -short]"\n'))

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "session",
            "run-tcl",
            "--session",
            session_ref,
            "--stdin",
            "--timeout",
            "5",
        ]
    )

    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["result"] == "version=2023.1"

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_bd_summary_parses_fake_vivado_output(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "bd",
            "summary",
            "--session",
            session_ref,
            "--design",
            "design_1",
            "--validate",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["ok"] is True
    assert summary["bd_summary"]["has_block_design"] is True
    assert summary["bd_summary"]["current_bd_design"] == "design_1"

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_project_summary_parses_fake_vivado_output(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "project",
            "summary",
            "--session",
            session_ref,
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["ok"] is True
    assert summary["project_summary"]["has_project"] is True
    assert summary["project_summary"]["current_project"] == "fake_project"
    assert summary["project_summary"]["runs"][0]["name"] == "synth_1"

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_capture_ila_requires_hardware_acknowledgement(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "hw",
            "capture-ila",
            "--session",
            session_ref,
            "--ila",
            "hw_ila_0",
            "--timeout",
            "5",
        ]
    )

    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["type"] == "PermissionError"
    assert "expect-hardware-access" in error["error"]

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_list_debug_cores_requires_hardware_acknowledgement(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "hw",
            "list-debug-cores",
            "--session",
            session_ref,
            "--timeout",
            "5",
        ]
    )

    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["type"] == "PermissionError"
    assert "expect-hardware-access" in error["error"]

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_list_debug_cores_parses_fake_vivado_output(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "hw",
            "list-debug-cores",
            "--session",
            session_ref,
            "--expect-hardware-access",
            "--timeout",
            "5",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["expect_hardware_access"] is True
    assert Path(payload["debug_cores_path"]).exists()
    assert Path(payload["debug_cores_json_path"]).exists()
    cores = payload["debug_cores"]
    assert cores["ila_count"] == 1
    assert cores["vio_count"] == 1
    assert cores["probe_count"] == 6
    assert cores["ilas"][0]["cell_name"] == "top/u_ila_0"
    assert cores["vios"][0]["cell_name"] == "chip_config/vio_spi_readback"
    assert cores["vios"][0]["probes"][0]["name"] == "chip_config/spi_read_status"

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_vio_read_requires_hardware_acknowledgement(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "hw",
            "vio-read",
            "--session",
            session_ref,
            "--vio",
            "hw_vio_0",
            "--probe",
            "chip_config/spi_read_status",
            "--timeout",
            "5",
        ]
    )

    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["type"] == "PermissionError"
    assert "expect-hardware-access" in error["error"]

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_vio_read_parses_fake_vivado_values(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "hw",
            "vio-read",
            "--session",
            session_ref,
            "--vio",
            "hw_vio_0",
            "--probe",
            "chip_config/spi_read_status",
            "--probe",
            "chip_config/spi_read_req",
            "--expect-hardware-access",
            "--timeout",
            "5",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["expect_hardware_access"] is True
    assert Path(payload["vio_read_path"]).exists()
    assert Path(payload["vio_read_json_path"]).exists()
    vio_read = payload["vio_read"]
    assert vio_read["vio"] == "hw_vio_0"
    assert vio_read["probe_count"] == 2
    assert vio_read["probes"][0]["name"] == "chip_config/spi_read_status"
    assert vio_read["probes"][0]["value"] == "0D028103"
    assert vio_read["probes"][0]["decoded_int"] == int("0D028103", 16)
    assert vio_read["probes"][1]["name"] == "chip_config/spi_read_req"
    assert vio_read["probes"][1]["value"] == "0"

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_vio_write_requires_both_acknowledgements(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    base = [
        "--workspace",
        str(workspace),
        "hw",
        "vio-write",
        "--session",
        session_ref,
        "--vio",
        "hw_vio_0",
        "--set",
        "chip_config/spi_read_req=1",
        "--timeout",
        "5",
    ]

    code = cli.main(base)
    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["type"] == "PermissionError"
    assert "expect-hardware-access" in error["error"]

    code = cli.main([*base, "--expect-hardware-access"])
    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["type"] == "PermissionError"
    assert "expect-vio-write" in error["error"]

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_vio_write_parses_fake_vivado_writeback(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "hw",
            "vio-write",
            "--session",
            session_ref,
            "--vio",
            "hw_vio_0",
            "--set",
            "chip_config/spi_read_req=1",
            "--expect-hardware-access",
            "--expect-vio-write",
            "--timeout",
            "5",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["expect_hardware_access"] is True
    assert payload["expect_vio_write"] is True
    assert Path(payload["vio_write_path"]).exists()
    assert Path(payload["vio_write_json_path"]).exists()
    vio_write = payload["vio_write"]
    assert vio_write["vio"] == "hw_vio_0"
    assert vio_write["all_write_ok"] is True
    assert vio_write["writes"][0]["name"] == "chip_config/spi_read_req"
    assert vio_write["writes"][0]["before_value"] == "0"
    assert vio_write["writes"][0]["after_value"] == "1"
    assert vio_write["writes"][0]["write_ok"] is True

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_capture_ila_analyzes_fake_vivado_csv(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "hw",
            "capture-ila",
            "--session",
            session_ref,
            "--ila",
            "hw_ila_0",
            "--label",
            "generic_adc",
            "--analysis",
            "adc14",
            "--sample-rate-hz",
            "80",
            "--expect-hardware-access",
            "--timeout",
            "5",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["expect_hardware_access"] is True
    assert Path(payload["capture_path"]).exists()
    assert Path(payload["analysis_path"]).exists()
    assert payload["analysis"]["signals"]["top/sine[13:0]"]["min"] == -100
    assert payload["analysis"]["signals"]["top/sine[13:0]"]["peak_frequency_hz"] == 20.0
    assert payload["analysis"]["signals"]["top/sine[13:0]"]["near_clip"] is False

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_spi_read_requires_hardware_acknowledgement(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "hw",
            "spi-read",
            "--session",
            session_ref,
            "--vio",
            "hw_vio_0",
            "--status-probe",
            "spi/status",
            "--req-probe",
            "spi/req",
            "--target-probe",
            "spi/target",
            "--addr-probe",
            "spi/addr",
            "--reg",
            "2:0x0281",
            "--timeout",
            "5",
        ]
    )

    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["type"] == "PermissionError"
    assert "expect-hardware-access" in error["error"]

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_hw_spi_read_decodes_fake_vivado_status(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "hw",
            "spi-read",
            "--session",
            session_ref,
            "--vio",
            "hw_vio_0",
            "--status-probe",
            "spi/status",
            "--req-probe",
            "spi/req",
            "--target-probe",
            "spi/target",
            "--addr-probe",
            "spi/addr",
            "--reg",
            "2:0x0281",
            "--reg",
            "2:0x0300",
            "--expect-hardware-access",
            "--timeout",
            "5",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["expect_hardware_access"] is True
    assert Path(payload["spi_read_path"]).exists()
    assert Path(payload["spi_read_json_path"]).exists()
    summary = payload["spi_read_summary"]
    assert summary["all_read_ok"] is True
    assert summary["read_ok_count"] == 2
    assert summary["reads"][0]["data_hex"] == "0x03"
    assert summary["reads"][1]["requested_addr_hex"] == "0x0300"
    assert summary["reads"][1]["data_hex"] == "0x01"

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_status_filters_runs(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "status",
            "--session",
            session_ref,
            "--run",
            "synth_1",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    status = json.loads(capsys.readouterr().out)
    assert status["ok"] is True
    assert status["runs"] == [{"name": "synth_1", "status": "synth_design Complete!", "progress": "100%"}]
    assert "project_summary" not in status

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_launch_returns_immediately(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    started = json.loads(capsys.readouterr().out)
    session_ref = started["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "launch",
            "--session",
            session_ref,
            "synth_1",
            "--jobs",
            "4",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    launched = json.loads(capsys.readouterr().out)
    assert launched["ok"] is True
    assert launched["run"] == "synth_1"
    assert launched["status"]["status"] == "complete"
    command_text = Path(launched["command_path"]).read_text(encoding="utf-8")
    assert "launch_runs -jobs 4 {synth_1}" in command_text
    assert "wait_on_run" not in command_text

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_diagnose_reports_queued_run_without_worker(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "diagnose",
            "--session",
            session_ref,
            "synth_1",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    diagnosed = json.loads(capsys.readouterr().out)
    diagnosis = diagnosed["run_diagnosis"]
    assert diagnosed["ok"] is True
    assert diagnosis["has_run"] is True
    assert diagnosis["properties"]["STATUS"] == "Queued..."
    assert diagnosis["filesystem"]["queue_markers"][0]["name"] == ".Vivado_Synthesis.queue.rst"
    assert diagnosis["issues"][0]["issue_id"] == "run.queued_without_worker"
    assert Path(diagnosed["diagnosis_path"]).exists()

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_diagnose_ignores_stale_worker_logs(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "diagnose",
            "--session",
            session_ref,
            "synth_with_stale_log",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    diagnosis = json.loads(capsys.readouterr().out)["run_diagnosis"]
    assert diagnosis["filesystem"]["logs"][0]["name"] == "runme.log"
    assert diagnosis["issues"][0]["issue_id"] == "run.queued_without_worker"
    assert diagnosis["issues"][0]["stale_logs"][0]["name"] == "runme.log"

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_launch_local_starts_generated_script(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "launch-local",
            "--session",
            session_ref,
            "--jobs",
            "4",
            "synth_1",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    launched = json.loads(capsys.readouterr().out)
    assert launched["ok"] is True
    assert launched["mode"] == "local_run_script"
    assert launched["prepared"] is False
    assert launched["prepare_result"] is None
    assert launched["process_pid"] > 0
    assert launched["local_run_status"] == "running"
    assert launched["script_path"].endswith("runme.bat")
    assert Path(launched["log_path"]).exists()
    assert Path(launched["exit_code_path"]).name.endswith(".exitcode")
    assert Path(launched["local_run_record_path"]).exists()

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_status_includes_running_local_tracker(tmp_path: Path, capsys, monkeypatch) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    assert (
        cli.main(
            [
                "--workspace",
                str(workspace),
                "run",
                "launch-local",
                "--session",
                session_ref,
                "synth_1",
                "--timeout",
                "5",
            ]
        )
        == 0
    )
    launched = json.loads(capsys.readouterr().out)
    launched_pid = int(launched["process_pid"])
    launched_exit_code = Path(launched["exit_code_path"]).resolve()
    original_pid_running = cli_core._pid_running
    original_read_exit_code = cli_core._read_exit_code

    def fake_read_exit_code(path: Path) -> int | None:
        if path.resolve() == launched_exit_code:
            return None
        return original_read_exit_code(path)

    def fake_pid_running(pid: int) -> bool:
        if pid == launched_pid:
            return True
        return original_pid_running(pid)

    monkeypatch.setattr(cli_core, "_read_exit_code", fake_read_exit_code)
    monkeypatch.setattr(cli_core, "_pid_running", fake_pid_running)
    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "status",
            "--session",
            session_ref,
            "--run",
            "synth_1",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    status = json.loads(capsys.readouterr().out)
    assert status["local_runs"][0]["local_run_status"] == "running"
    assert status["local_runs"][0]["process_pid"] == launched_pid
    assert status["runs"][0]["local_run"]["log_path"] == launched["log_path"]

    monkeypatch.setattr(cli_core, "_read_exit_code", original_read_exit_code)
    monkeypatch.setattr(cli_core, "_pid_running", original_pid_running)
    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_status_reports_completed_local_exit_code(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    assert cli.main(["--workspace", str(workspace), "run", "launch-local", "--session", session_ref, "synth_1", "--timeout", "5"]) == 0
    launched = json.loads(capsys.readouterr().out)
    assert _wait_for_path(Path(launched["exit_code_path"]))

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "status",
            "--session",
            session_ref,
            "--run",
            "synth_1",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    status = json.loads(capsys.readouterr().out)
    local = status["local_runs"][0]
    assert local["local_run_status"] == "completed"
    assert local["exit_code"] == 0
    assert local["process_running"] is False

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_launch_local_prepares_missing_script(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "launch-local",
            "--session",
            session_ref,
            "--jobs",
            "4",
            "needs_script",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    launched = json.loads(capsys.readouterr().out)
    assert launched["ok"] is True
    assert launched["prepared"] is True
    assert launched["prepare_result"]["jobs"] == 4
    assert launched["script_path"].endswith("runme.bat")
    assert Path(launched["log_path"]).exists()

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_diagnose_reports_missing_dcp(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "diagnose",
            "--session",
            session_ref,
            "synth_missing_dcp",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    diagnosis = json.loads(capsys.readouterr().out)["run_diagnosis"]
    issue_ids = [issue["issue_id"] for issue in diagnosis["issues"]]
    assert "run.failed" in issue_ids
    assert "run.missing_dcp" in issue_ids
    missing_dcp_issue = next(issue for issue in diagnosis["issues"] if issue["issue_id"] == "run.missing_dcp")
    assert missing_dcp_issue["missing_dcp_paths"] == ["c:/fake/bd/ip/missing_ip/missing_ip.dcp"]

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_logs_returns_tail(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "logs",
            "--session",
            session_ref,
            "synth_with_log",
            "--tail",
            "2",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    logs = json.loads(capsys.readouterr().out)
    assert logs["ok"] is True
    assert logs["log_path"].endswith("runme.log")
    assert logs["text"] == "line 2\nline 3"
    assert any(path.endswith("runme.log") for path in logs["available_logs"])

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_logs_prefers_latest_local_log(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    assert cli.main(["--workspace", str(workspace), "run", "launch-local", "--session", session_ref, "synth_with_log", "--timeout", "5"]) == 0
    launched = json.loads(capsys.readouterr().out)
    assert _wait_for_path(Path(launched["log_path"]))

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "logs",
            "--session",
            session_ref,
            "synth_with_log",
            "--tail",
            "2",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    logs = json.loads(capsys.readouterr().out)
    assert logs["log_path"] == launched["log_path"]
    assert Path(logs["log_path"]).name.startswith("vivado_cli_local_")
    assert any(path.endswith("runme.log") for path in logs["available_logs"])

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_cli_run_reset_requires_expect_destructive(tmp_path: Path, capsys) -> None:
    wrapper = _make_fake_wrapper(tmp_path, open_design=True)
    workspace = tmp_path / "workspace"

    assert cli.main(["--workspace", str(workspace), "session", "start", "--vivado-path", str(wrapper), "--no-gui", "--timeout", "5"]) == 0
    session_ref = json.loads(capsys.readouterr().out)["session_ref"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "reset",
            "--session",
            session_ref,
            "synth_1",
            "--timeout",
            "5",
        ]
    )
    assert code == 1
    denied = json.loads(capsys.readouterr().err)
    assert denied["type"] == "PermissionError"
    assert "--expect-destructive" in denied["error"]

    code = cli.main(
        [
            "--workspace",
            str(workspace),
            "run",
            "reset",
            "--session",
            session_ref,
            "synth_1",
            "--expect-destructive",
            "--timeout",
            "5",
        ]
    )
    assert code == 0
    reset = json.loads(capsys.readouterr().out)
    assert reset["ok"] is True
    assert reset["expect_destructive"] is True
    assert reset["status"] == {"run": "synth_1", "status": "Not started", "progress": "0%"}
    command_text = Path(reset["command_path"]).read_text(encoding="utf-8")
    assert "reset_run" in command_text

    assert cli.main(["--workspace", str(workspace), "session", "stop", "--session", session_ref, "--timeout", "5"]) == 0
    capsys.readouterr()


def test_python_module_entrypoint_reports_version() -> None:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else src_path
    result = subprocess.run(
        [sys.executable, "-m", "vivado_cli", "--version"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.startswith("vivado-cli ")


def _make_fake_wrapper(tmp_path: Path, *, open_design: bool = False) -> Path:
    fake = Path(__file__).resolve().parents[1] / "fixtures" / "fake_vivado.py"
    wrapper = tmp_path / "vivado.bat"
    extra = " --fake-open-design" if open_design else ""
    wrapper.write_text(f'@echo off\n"{sys.executable}" "{fake}"{extra} %*\n', encoding="utf-8")
    return wrapper


def _wait_for_path(path: Path, *, timeout_seconds: float = 5.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return path.exists()


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
