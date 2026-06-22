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
    assert "FAKE REPORT" in report["report_text"]
    assert report["report_summary"]["parsed"] is True
    assert report["report_summary"]["status"] == "pass"
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


def _make_fake_wrapper(tmp_path: Path) -> Path:
    fake = Path(__file__).resolve().parents[1] / "fixtures" / "fake_vivado.py"
    wrapper = tmp_path / "vivado.bat"
    wrapper.write_text(f'@echo off\n"{sys.executable}" "{fake}" %*\n', encoding="utf-8")
    return wrapper
