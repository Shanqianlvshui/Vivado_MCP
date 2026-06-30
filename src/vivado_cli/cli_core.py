from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any, Callable

from .session import (
    _analysis_type_from_artifact,
    _artifact_kind,
    _artifact_relative,
    _artifact_tool_hint,
    _parse_result,
    _report_type_from_artifact,
    _result_to_dict,
    _summary_type_from_artifact,
    artifact_uri,
)
from .types import CapabilityProfile, TclCommandResult
from .vivado_locator import _vivado_command, locate_vivado


@dataclass
class CliSessionRecord:
    session_ref: str
    session_dir: Path
    workspace_dir: Path
    vivado_path: Path
    open_gui: bool
    capability_profile: CapabilityProfile
    process_pid: int
    log_path: Path
    current_project_path: Path | None = None
    bridge_kind: str = "cli"


def sessions_root(workspace: str | Path) -> Path:
    return Path(workspace).resolve() / ".vivado_cli" / "sessions"


def start_session(
    *,
    workspace: str | Path,
    vivado_path: str | None = None,
    open_gui: bool = True,
    capability_profile: CapabilityProfile = "trusted-local",
    startup_timeout_seconds: int = 45,
) -> dict[str, object]:
    workspace_dir = Path(workspace).resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    executable = locate_vivado(vivado_path)
    session_ref = uuid.uuid4().hex
    session_dir = sessions_root(workspace_dir) / session_ref
    session_dir.mkdir(parents=True, exist_ok=True)
    for child in ("inbox", "running", "done", "summaries", "reports"):
        (session_dir / child).mkdir(parents=True, exist_ok=True)

    log_path = session_dir / "process.log"
    bridge = resources.files("vivado_cli.assets").joinpath("cli_bridge.tcl")
    args = [
        "-mode",
        "gui" if open_gui else "tcl",
        "-source",
        str(bridge),
        "-tclargs",
        str(session_dir),
    ]
    if open_gui:
        args.append("--gui")

    log_file = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        _vivado_command(executable, args),
        cwd=workspace_dir,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    record = CliSessionRecord(
        session_ref=session_ref,
        session_dir=session_dir,
        workspace_dir=workspace_dir,
        vivado_path=executable,
        open_gui=open_gui,
        capability_profile=capability_profile,
        process_pid=process.pid,
        log_path=log_path,
        bridge_kind="cli",
    )
    _write_record(record)
    try:
        _wait_for_status(session_dir, "idle", timeout_seconds=startup_timeout_seconds)
    except Exception:
        process.terminate()
        raise
    return session_state(workspace=workspace_dir, session_ref=session_ref)


def list_sessions(*, workspace: str | Path) -> dict[str, object]:
    root = sessions_root(workspace)
    records = [_read_record(path) for path in sorted(root.glob("*/session.json"))]
    return {"sessions": [session_state(workspace=workspace, session_ref=record.session_ref) for record in records]}


def adopt_session(
    *,
    workspace: str | Path,
    session_dir: str | Path,
    process_pid: int,
    session_ref: str | None = None,
    vivado_path: str | Path | None = None,
    open_gui: bool = True,
    capability_profile: CapabilityProfile = "trusted-local",
    current_project_path: str | Path | None = None,
) -> dict[str, object]:
    workspace_dir = Path(workspace).resolve()
    source_session_dir = Path(session_dir).resolve()
    if not source_session_dir.exists():
        raise FileNotFoundError(f"session_dir does not exist: {source_session_dir}")
    for child in ("inbox", "running", "done"):
        child_path = source_session_dir / child
        if not child_path.is_dir():
            raise FileNotFoundError(f"session_dir is missing bridge subdirectory {child!r}: {child_path}")
    if not _pid_running(int(process_pid)):
        raise RuntimeError(f"Vivado session process is not running: pid={process_pid}")

    ref = session_ref or source_session_dir.name
    record_dir = sessions_root(workspace_dir) / ref
    record_dir.mkdir(parents=True, exist_ok=True)
    executable = Path(vivado_path).resolve() if vivado_path else Path("")
    log_path = source_session_dir / "process.log"
    record = CliSessionRecord(
        session_ref=ref,
        session_dir=source_session_dir,
        workspace_dir=workspace_dir,
        vivado_path=executable,
        open_gui=open_gui,
        capability_profile=capability_profile,
        process_pid=int(process_pid),
        log_path=log_path,
        current_project_path=Path(current_project_path).resolve() if current_project_path else None,
        bridge_kind=_detect_bridge_kind(source_session_dir),
    )
    _write_record(record, record_path=record_dir / "session.json")
    return session_state(workspace=workspace_dir, session_ref=ref)


def session_state(*, workspace: str | Path, session_ref: str) -> dict[str, object]:
    record = load_session(workspace=workspace, session_ref=session_ref)
    bridge = _bridge_state(record)
    return {
        "session_ref": record.session_ref,
        "session_dir": str(record.session_dir),
        "workspace_dir": str(record.workspace_dir),
        "vivado_path": str(record.vivado_path),
        "open_gui": record.open_gui,
        "capability_profile": record.capability_profile,
        "process_pid": record.process_pid,
        "process_running": _pid_running(record.process_pid),
        "current_project_path": str(record.current_project_path) if record.current_project_path else None,
        "bridge": bridge,
        "bridge_kind": bridge["kind"],
        "bridge_compatible": bridge["compatible"],
        "status": _read_status(record.session_dir / "status.txt"),
        "gui_status": _read_status(record.session_dir / "gui_status.txt"),
        "log_path": str(record.log_path),
    }


def session_artifacts(
    *,
    workspace: str | Path,
    session_ref: str,
    kind: str | None = None,
    report_type: str | None = None,
    limit: int | None = None,
    include_internal: bool = True,
) -> dict[str, object]:
    record = load_session(workspace=workspace, session_ref=session_ref)
    artifacts = _artifact_index(record, include_internal=include_internal)["artifacts"]
    if kind:
        artifacts = [artifact for artifact in artifacts if artifact.get("kind") == kind]
    if report_type:
        artifacts = [artifact for artifact in artifacts if artifact.get("report_type") == report_type]
    artifacts = _limit_tail(artifacts, limit)
    return {
        "ok": True,
        "session_ref": session_ref,
        "session_dir": str(record.session_dir),
        "artifacts": artifacts,
        "count": len(artifacts),
        "filters": {"kind": kind, "report_type": report_type, "limit": limit, "include_internal": include_internal},
    }


def session_timeline(
    *,
    workspace: str | Path,
    session_ref: str,
    kind: str | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    record = load_session(workspace=workspace, session_ref=session_ref)
    events = _artifact_index(record, include_internal=True)["artifacts"]
    if kind:
        events = [event for event in events if event.get("kind") == kind]
    events = _limit_tail(events, limit)
    counts: dict[str, int] = {}
    for event in events:
        event_kind = str(event.get("kind") or "other")
        counts[event_kind] = counts.get(event_kind, 0) + 1
    return {
        "ok": True,
        "session_ref": session_ref,
        "session_dir": str(record.session_dir),
        "events": events,
        "counts": counts,
        "count": len(events),
        "filters": {"kind": kind, "limit": limit},
    }


def read_artifact(
    *,
    workspace: str | Path,
    session_ref: str,
    artifact_id: str,
    max_chars: int = 20000,
) -> dict[str, object]:
    if max_chars < 0:
        raise ValueError("max_chars must be zero or greater")
    record = load_session(workspace=workspace, session_ref=session_ref)
    relative = _artifact_relative(session_ref, artifact_id)
    path = (record.session_dir / relative).resolve()
    session_root = record.session_dir.resolve()
    if session_root not in [path, *path.parents]:
        raise PermissionError("Artifact path escapes session directory")
    if not path.is_file():
        raise FileNotFoundError(f"Artifact not found: {relative}")
    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n\n[truncated]\n"
    kind = _artifact_kind(path)
    return {
        "ok": True,
        "session_ref": session_ref,
        "artifact_id": relative,
        "relative_path": relative,
        "path": str(path),
        "artifact_uri": artifact_uri(session_ref, relative),
        "kind": kind,
        "size_bytes": path.stat().st_size,
        "text": text,
        "truncated": truncated,
        "max_chars": max_chars,
    }


def session_recovery(
    *,
    workspace: str | Path,
    session_ref: str,
    limit: int = 10,
) -> dict[str, object]:
    record = load_session(workspace=workspace, session_ref=session_ref)
    state = session_state(workspace=workspace, session_ref=session_ref)
    timeline = session_timeline(workspace=workspace, session_ref=session_ref)
    events = timeline["events"] if isinstance(timeline.get("events"), list) else []
    latest = _latest_recovery_artifacts(events)
    report_analysis_payload = _read_json_artifact_by_event(record, latest.get("report_analysis"))
    xsim_analysis_payload = _read_json_artifact_by_event(record, latest.get("xsim_log_analysis"))
    snapshot_payload = _read_json_artifact_by_event(record, latest.get("state_snapshot"))
    next_action_plan = _cli_recovery_next_action_plan(
        report_analysis_payload=report_analysis_payload,
        xsim_analysis_payload=xsim_analysis_payload,
        latest=latest,
    )
    return {
        "ok": True,
        "session_ref": session_ref,
        "session_dir": str(record.session_dir),
        "current_project_path": str(record.current_project_path) if record.current_project_path else None,
        "state": state,
        "latest": latest,
        "summary": {
            "event_count": timeline.get("count", 0),
            "counts": timeline.get("counts", {}),
            "report_analysis_issue_count": _analysis_issue_count(report_analysis_payload),
            "xsim_issue_count": _analysis_issue_count(xsim_analysis_payload),
        },
        "quality_gates": _nested_dict(report_analysis_payload, ["analysis", "quality_gates"]) or {},
        "next_action_plan": next_action_plan,
        "recommendations": _cli_recovery_recommendations(latest, next_action_plan),
        "timeline_preview": _limit_tail(events, limit),
        "state_snapshot": _snapshot_summary(snapshot_payload),
    }


def load_session(*, workspace: str | Path, session_ref: str) -> CliSessionRecord:
    path = sessions_root(workspace) / session_ref / "session.json"
    if not path.exists():
        raise FileNotFoundError(f"CLI session not found: {session_ref}")
    return _read_record(path)


def open_project(
    *,
    workspace: str | Path,
    session_ref: str,
    project_path: str | Path,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    from .tcl import open_project_tcl

    project = Path(project_path).resolve()
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=open_project_tcl(project),
        timeout_seconds=timeout_seconds,
    )
    if result.get("ok"):
        record = load_session(workspace=workspace, session_ref=session_ref)
        record.current_project_path = project
        _write_record(record)
    result["state"] = session_state(workspace=workspace, session_ref=session_ref)
    return result


def run_tcl(
    *,
    workspace: str | Path,
    session_ref: str,
    tcl: str,
    timeout_seconds: int = 60,
    expect_destructive: bool = False,
) -> dict[str, object]:
    return submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=tcl,
        timeout_seconds=timeout_seconds,
        expect_destructive=expect_destructive,
    )


def source_tcl(
    *,
    workspace: str | Path,
    session_ref: str,
    script_path: str | Path,
    tclargs: list[str] | None = None,
    timeout_seconds: int = 120,
    expect_destructive: bool = False,
) -> dict[str, object]:
    from .tcl import quote_tcl, set_argv_tcl

    path = Path(script_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Tcl script does not exist: {path}")
    body = "\n".join([set_argv_tcl(tclargs or []), f"source {quote_tcl(path)}"])
    return submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=body,
        timeout_seconds=timeout_seconds,
        expect_destructive=expect_destructive,
    )


def tcl_help(
    *,
    workspace: str | Path,
    session_ref: str,
    command: str,
    timeout_seconds: int = 30,
) -> dict[str, object]:
    from .tcl import quote_tcl

    if not command.strip():
        raise ValueError("command must not be empty")
    return submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=f"return [help {quote_tcl(command)}]",
        timeout_seconds=timeout_seconds,
    )


def bd_summary(
    *,
    workspace: str | Path,
    session_ref: str,
    design_name: str | None = None,
    bd_path: str | Path | None = None,
    validate: bool = False,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    from .bd_summary import parse_bd_summary
    from .tcl import bd_summary_tcl

    record = load_session(workspace=workspace, session_ref=session_ref)
    output_path = record.session_dir / "summaries" / f"bd_summary_{uuid.uuid4().hex[:8]}.tsv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=bd_summary_tcl(
            output_path,
            design_name=design_name,
            bd_path=Path(bd_path).resolve() if bd_path else None,
            validate=validate,
        ),
        timeout_seconds=timeout_seconds,
    )
    result["summary_path"] = str(output_path)
    if output_path.exists():
        result["bd_summary"] = parse_bd_summary(output_path)
    return result


def bd_validate(
    *,
    workspace: str | Path,
    session_ref: str,
    design_name: str | None = None,
    bd_path: str | Path | None = None,
    save: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    from .bd_summary import parse_bd_validate_result
    from .tcl import bd_validate_tcl

    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=bd_validate_tcl(
            design_name=design_name,
            bd_path=Path(bd_path).resolve() if bd_path else None,
            save=save,
        ),
        timeout_seconds=timeout_seconds,
        expect_destructive=save,
    )
    result["validation"] = parse_bd_validate_result(str(result.get("result") or ""))
    return result


def report(
    *,
    workspace: str | Path,
    session_ref: str,
    report_type: str,
    output_name: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, object]:
    from .report_parser import parse_report
    from .tcl import report_tcl

    record = load_session(workspace=workspace, session_ref=session_ref)
    safe_name = output_name or f"{report_type}_{uuid.uuid4().hex[:8]}.rpt"
    if Path(safe_name).is_absolute() or len(Path(safe_name).parts) != 1:
        raise PermissionError("output_name must be a filename, not a path")
    output_path = record.session_dir / "reports" / safe_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=report_tcl(report_type, output_path),
        timeout_seconds=timeout_seconds,
    )
    result["report_path"] = str(output_path)
    if output_path.exists():
        text = output_path.read_text(encoding="utf-8", errors="replace")
        result["report_text"] = text[:8000]
        result["report_summary"] = parse_report(report_type, text)
    return result


def fileset_list(
    *,
    workspace: str | Path,
    session_ref: str,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    from .fileset_summary import parse_list_filesets
    from .tcl import list_filesets_tcl

    record = load_session(workspace=workspace, session_ref=session_ref)
    output_path = record.session_dir / "summaries" / f"filesets_{uuid.uuid4().hex[:8]}.tsv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=list_filesets_tcl(output_path),
        timeout_seconds=timeout_seconds,
    )
    result["filesets_path"] = str(output_path)
    result["filesets_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(record.session_dir).as_posix())
    if output_path.exists():
        result["filesets"] = parse_list_filesets(output_path)
    return result


def fileset_describe(
    *,
    workspace: str | Path,
    session_ref: str,
    name: str,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    from .fileset_summary import parse_describe_fileset
    from .tcl import describe_fileset_tcl

    if not name.strip():
        raise ValueError("fileset name must not be empty")
    record = load_session(workspace=workspace, session_ref=session_ref)
    output_path = record.session_dir / "summaries" / f"fileset_{_safe_artifact_stem(name)}_{uuid.uuid4().hex[:8]}.tsv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=describe_fileset_tcl(output_path, name=name),
        timeout_seconds=timeout_seconds,
    )
    result["fileset"] = name
    result["fileset_desc_path"] = str(output_path)
    result["fileset_desc_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(record.session_dir).as_posix())
    if output_path.exists():
        result["fileset_description"] = parse_describe_fileset(output_path)
    return result


def fileset_create(
    *,
    workspace: str | Path,
    session_ref: str,
    name: str,
    kind: str,
    timeout_seconds: int = 60,
    state_diff: bool = True,
) -> dict[str, object]:
    from .tcl import create_fileset_tcl

    if not name.strip():
        raise ValueError("fileset name must not be empty")
    if not kind.strip():
        raise ValueError("fileset type must not be empty")
    def action() -> dict[str, object]:
        return submit_tcl(
            workspace=workspace,
            session_ref=session_ref,
            tcl=create_fileset_tcl(name=name, kind=kind),
            timeout_seconds=timeout_seconds,
        )

    result = _capture_state_diff_around(
        workspace=workspace,
        session_ref=session_ref,
        operation="fileset_create",
        filesets=[name],
        timeout_seconds=timeout_seconds,
        enabled=state_diff,
        action=action,
    )
    result["requested_fileset"] = name
    result["requested_type"] = kind
    result.update(_parse_key_value_result(str(result.get("result") or "")))
    return result


def fileset_add_files(
    *,
    workspace: str | Path,
    session_ref: str,
    fileset: str,
    files: list[str | Path],
    include_dirs: list[str | Path] | None = None,
    defines: list[str] | None = None,
    top: str | None = None,
    library: str | None = None,
    file_type: str | None = None,
    used_in: list[str] | None = None,
    processing_order: int | None = None,
    timeout_seconds: int = 60,
    state_diff: bool = True,
) -> dict[str, object]:
    from .tcl import add_sources_tcl

    if not fileset.strip():
        raise ValueError("fileset must not be empty")
    if not files:
        raise ValueError("Provide at least one file to add")
    paths = [Path(path).resolve() for path in files]

    def action() -> dict[str, object]:
        return submit_tcl(
            workspace=workspace,
            session_ref=session_ref,
            tcl=add_sources_tcl(
                sources=paths,
                constraints=[],
                top=top,
                sources_fileset=fileset,
                include_dirs=[Path(path).resolve() for path in include_dirs or []],
                defines=defines,
                library=library,
                file_type=file_type,
                used_in=used_in,
                processing_order=processing_order,
            ),
            timeout_seconds=timeout_seconds,
        )

    result = _capture_state_diff_around(
        workspace=workspace,
        session_ref=session_ref,
        operation="fileset_add_files",
        filesets=[fileset],
        timeout_seconds=timeout_seconds,
        enabled=state_diff,
        action=action,
    )
    result["fileset"] = fileset
    result["files"] = [str(path) for path in paths]
    return result


def fileset_remove_files(
    *,
    workspace: str | Path,
    session_ref: str,
    files: list[str | Path],
    fileset: str | None = None,
    force: bool = False,
    timeout_seconds: int = 60,
    expect_destructive: bool = False,
    state_diff: bool = True,
) -> dict[str, object]:
    from .tcl import remove_files_tcl

    if not expect_destructive:
        raise PermissionError("Removing files from a project/fileset changes project state; pass --expect-destructive")
    paths = [Path(path).resolve() for path in files]

    def action() -> dict[str, object]:
        return submit_tcl(
            workspace=workspace,
            session_ref=session_ref,
            tcl=remove_files_tcl(paths=paths, fileset=fileset, force=force),
            timeout_seconds=timeout_seconds,
            expect_destructive=True,
        )

    result = _capture_state_diff_around(
        workspace=workspace,
        session_ref=session_ref,
        operation="fileset_remove_files",
        filesets=[fileset] if fileset else None,
        timeout_seconds=timeout_seconds,
        enabled=state_diff,
        action=action,
    )
    result["fileset"] = fileset
    result["files"] = [str(path) for path in paths]
    result["force"] = force
    return result


def fileset_set_file_properties(
    *,
    workspace: str | Path,
    session_ref: str,
    files: list[str | Path],
    properties: dict[str, str],
    fileset: str | None = None,
    timeout_seconds: int = 60,
    state_diff: bool = True,
) -> dict[str, object]:
    from .tcl import set_file_properties_tcl

    paths = [Path(path).resolve() for path in files]

    def action() -> dict[str, object]:
        return submit_tcl(
            workspace=workspace,
            session_ref=session_ref,
            tcl=set_file_properties_tcl(paths=paths, properties=properties, fileset=fileset),
            timeout_seconds=timeout_seconds,
        )

    result = _capture_state_diff_around(
        workspace=workspace,
        session_ref=session_ref,
        operation="fileset_set_file_properties",
        filesets=[fileset] if fileset else None,
        timeout_seconds=timeout_seconds,
        enabled=state_diff,
        action=action,
    )
    result["fileset"] = fileset
    result["files"] = [str(path) for path in paths]
    result["properties"] = dict(properties)
    return result


def fileset_set_top(
    *,
    workspace: str | Path,
    session_ref: str,
    top: str | None,
    fileset: str | None = None,
    timeout_seconds: int = 60,
    state_diff: bool = True,
) -> dict[str, object]:
    from .tcl import set_top_tcl

    def action() -> dict[str, object]:
        return submit_tcl(
            workspace=workspace,
            session_ref=session_ref,
            tcl=set_top_tcl(top=top, fileset=fileset),
            timeout_seconds=timeout_seconds,
        )

    if top is None:
        result = action()
    else:
        result = _capture_state_diff_around(
            workspace=workspace,
            session_ref=session_ref,
            operation="fileset_set_top",
            filesets=[fileset] if fileset else None,
            timeout_seconds=timeout_seconds,
            enabled=state_diff,
            action=action,
        )
    result["fileset"] = fileset
    result.update(_parse_key_value_result(str(result.get("result") or "")))
    return result


def fileset_apply(
    *,
    workspace: str | Path,
    session_ref: str,
    fileset: str,
    include_dirs: list[str | Path] | None = None,
    defines: list[str] | None = None,
    top: str | None = None,
    properties: dict[str, str] | None = None,
    update_compile_order: bool = True,
    timeout_seconds: int = 60,
    state_diff: bool = True,
) -> dict[str, object]:
    from .tcl import fileset_apply_tcl

    resolved_include_dirs = [Path(path).resolve() for path in include_dirs or []] if include_dirs is not None else None

    def action() -> dict[str, object]:
        return submit_tcl(
            workspace=workspace,
            session_ref=session_ref,
            tcl=fileset_apply_tcl(
                fileset=fileset,
                include_dirs=resolved_include_dirs,
                defines=defines,
                top=top,
                properties=properties,
                update_compile_order=update_compile_order,
            ),
            timeout_seconds=timeout_seconds,
        )

    result = _capture_state_diff_around(
        workspace=workspace,
        session_ref=session_ref,
        operation="fileset_apply",
        filesets=[fileset],
        timeout_seconds=timeout_seconds,
        enabled=state_diff,
        action=action,
    )
    result["fileset"] = fileset
    result["include_dirs"] = [str(path) for path in resolved_include_dirs or []]
    result["defines"] = defines or []
    result["top"] = top
    result["properties"] = dict(properties or {})
    result["update_compile_order"] = update_compile_order
    return result


def constraint_diagnostics(
    *,
    workspace: str | Path,
    session_ref: str,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    from .fileset_summary import parse_constraint_diagnostics
    from .tcl import constraint_diagnostics_tcl

    record = load_session(workspace=workspace, session_ref=session_ref)
    output_path = record.session_dir / "summaries" / f"constraint_diag_{uuid.uuid4().hex[:8]}.tsv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=constraint_diagnostics_tcl(output_path),
        timeout_seconds=timeout_seconds,
    )
    result["constraint_diagnostics_path"] = str(output_path)
    result["constraint_diagnostics_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(record.session_dir).as_posix())
    if output_path.exists():
        result["constraint_diagnostics"] = parse_constraint_diagnostics(output_path)
    return result


def constraint_check_order(
    *,
    workspace: str | Path,
    session_ref: str,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    from .fileset_summary import analyze_xdc_order

    result = constraint_diagnostics(workspace=workspace, session_ref=session_ref, timeout_seconds=timeout_seconds)
    diagnostics = result.get("constraint_diagnostics")
    if isinstance(diagnostics, dict):
        result["xdc_order"] = analyze_xdc_order(diagnostics)
    return result


def constraint_apply(
    *,
    workspace: str | Path,
    session_ref: str,
    fileset: str,
    create_if_missing: bool = False,
    add: list[str | Path] | None = None,
    remove: list[str | Path] | None = None,
    used_in: list[str] | None = None,
    reorder: list[str | Path] | None = None,
    active: bool | None = None,
    timeout_seconds: int = 60,
    expect_destructive: bool = False,
    state_diff: bool = True,
) -> dict[str, object]:
    from .tcl import constraint_set_apply_tcl

    if remove and not expect_destructive:
        raise PermissionError("Removing XDC files from a constraint set changes project state; pass --expect-destructive")
    add_paths = [Path(path).resolve() for path in add or []]
    remove_paths = [Path(path).resolve() for path in remove or []]
    reorder_paths = [Path(path).resolve() for path in reorder or []]

    def action() -> dict[str, object]:
        return submit_tcl(
            workspace=workspace,
            session_ref=session_ref,
            tcl=constraint_set_apply_tcl(
                fileset=fileset,
                create_if_missing=create_if_missing,
                add=add_paths,
                remove=remove_paths,
                used_in=used_in,
                reorder=reorder_paths,
                active=active,
            ),
            timeout_seconds=timeout_seconds,
            expect_destructive=bool(remove_paths),
        )

    result = _capture_state_diff_around(
        workspace=workspace,
        session_ref=session_ref,
        operation="constraint_apply",
        filesets=[fileset],
        timeout_seconds=timeout_seconds,
        enabled=state_diff,
        action=action,
    )
    result["fileset"] = fileset
    result["create_if_missing"] = create_if_missing
    result["add"] = [str(path) for path in add_paths]
    result["remove"] = [str(path) for path in remove_paths]
    result["used_in"] = used_in
    result["reorder"] = [str(path) for path in reorder_paths]
    result["active"] = active
    return result


def _capture_state_diff_around(
    *,
    workspace: str | Path,
    session_ref: str,
    operation: str,
    filesets: list[str] | None,
    timeout_seconds: int,
    enabled: bool = True,
    action: Callable[[], dict[str, object]],
) -> dict[str, object]:
    if not enabled:
        result = action()
        result["state_tracking"] = {
            "enabled": False,
            "operation": operation,
            "reason": "disabled_by_user",
        }
        return result

    try:
        before = _capture_state_snapshot(
            workspace=workspace,
            session_ref=session_ref,
            label=f"{operation}_before",
            filesets=filesets,
            timeout_seconds=_snapshot_timeout(timeout_seconds),
        )
    except Exception as exc:  # noqa: BLE001 - State capture must not block the requested mutation.
        result = action()
        result["state_tracking"] = {
            "enabled": False,
            "operation": operation,
            "error": f"before snapshot failed: {exc}",
        }
        return result

    result = action()
    try:
        after = _capture_state_snapshot(
            workspace=workspace,
            session_ref=session_ref,
            label=f"{operation}_after",
            filesets=filesets,
            timeout_seconds=_snapshot_timeout(timeout_seconds),
        )
        diff_result = _write_state_diff(
            workspace=workspace,
            session_ref=session_ref,
            before_state=before["state"],
            after_state=after["state"],
            operation=operation,
        )
    except Exception as exc:  # noqa: BLE001 - Preserve the operation result even if post-capture fails.
        result["state_tracking"] = {
            "enabled": False,
            "operation": operation,
            "before": _snapshot_ref(before),
            "error": f"after snapshot or diff failed: {exc}",
        }
        return result

    result["state_before"] = _snapshot_ref(before)
    result["state_after"] = _snapshot_ref(after)
    result["state_diff"] = diff_result
    result["state_tracking"] = {
        "enabled": True,
        "operation": operation,
        "before": _snapshot_ref(before),
        "after": _snapshot_ref(after),
        "diff": {
            "changed": diff_result["changed"],
            "summary": diff_result.get("summary", {}),
            "diff_path": diff_result.get("diff_path"),
            "diff_artifact_uri": diff_result.get("diff_artifact_uri"),
        },
    }
    return result


def _capture_state_snapshot(
    *,
    workspace: str | Path,
    session_ref: str,
    label: str,
    filesets: list[str] | None,
    timeout_seconds: int,
) -> dict[str, object]:
    from .state_diff import state_digest

    record = load_session(workspace=workspace, session_ref=session_ref)
    state: dict[str, object] = {
        "session_ref": session_ref,
        "workspace_dir": str(record.workspace_dir),
        "current_project_path": str(record.current_project_path) if record.current_project_path else None,
        "project": {},
        "filesets": {},
        "fileset_descriptions": [],
        "constraints": {},
        "errors": [],
    }
    errors = state["errors"]
    assert isinstance(errors, list)

    try:
        project = project_summary(workspace=workspace, session_ref=session_ref, timeout_seconds=timeout_seconds)
        state["project"] = project.get("project_summary", {})
    except Exception as exc:  # noqa: BLE001 - Keep partial snapshots useful.
        errors.append({"section": "project", "error": str(exc)})

    fileset_summary: dict[str, object] = {}
    try:
        fileset_result = fileset_list(workspace=workspace, session_ref=session_ref, timeout_seconds=timeout_seconds)
        payload = fileset_result.get("filesets")
        if isinstance(payload, dict):
            fileset_summary = payload
            state["filesets"] = payload
    except Exception as exc:  # noqa: BLE001
        errors.append({"section": "filesets", "error": str(exc)})

    describe_names = _state_filesets_to_describe(filesets, fileset_summary)
    descriptions: list[dict[str, object]] = []
    for name in describe_names:
        try:
            desc_result = fileset_describe(workspace=workspace, session_ref=session_ref, name=name, timeout_seconds=timeout_seconds)
            desc = desc_result.get("fileset_description")
            if isinstance(desc, dict) and desc.get("name"):
                descriptions.append(desc)
            else:
                descriptions.append({"name": name, "missing": True, "properties": {}, "files": []})
        except Exception as exc:  # noqa: BLE001
            descriptions.append({"name": name, "missing": True, "properties": {}, "files": [], "error": str(exc)})
    state["fileset_descriptions"] = descriptions

    try:
        constraints = constraint_diagnostics(workspace=workspace, session_ref=session_ref, timeout_seconds=timeout_seconds)
        state["constraints"] = constraints.get("constraint_diagnostics", {})
    except Exception as exc:  # noqa: BLE001
        errors.append({"section": "constraints", "error": str(exc)})

    snapshot_id = f"state_{_safe_artifact_stem(label)}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    state["snapshot"] = {
        "id": snapshot_id,
        "label": label,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "digest": state_digest(state),
        "scope": {"filesets": describe_names},
    }
    snapshots_dir = record.session_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshots_dir / f"{snapshot_id}.json"
    snapshot_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "snapshot_id": snapshot_id,
        "label": label,
        "digest": state["snapshot"]["digest"],
        "state": state,
        "snapshot_path": str(snapshot_path),
        "snapshot_artifact_uri": artifact_uri(session_ref, snapshot_path.relative_to(record.session_dir).as_posix()),
    }


def _write_state_diff(
    *,
    workspace: str | Path,
    session_ref: str,
    before_state: object,
    after_state: object,
    operation: str,
) -> dict[str, object]:
    from .state_diff import diff_states

    if not isinstance(before_state, dict) or not isinstance(after_state, dict):
        raise ValueError("before_state and after_state must be JSON objects")
    record = load_session(workspace=workspace, session_ref=session_ref)
    diff = diff_states(before_state, after_state)
    diffs_dir = record.session_dir / "diffs"
    diffs_dir.mkdir(parents=True, exist_ok=True)
    diff_path = diffs_dir / f"state_diff_{_safe_artifact_stem(operation)}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.json"
    diff_path.write_text(json.dumps(diff, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "ok": True,
        "session_ref": session_ref,
        "operation": operation,
        "changed": diff["changed"],
        "summary": diff.get("summary", {}),
        "diff": diff,
        "diff_path": str(diff_path),
        "diff_artifact_uri": artifact_uri(session_ref, diff_path.relative_to(record.session_dir).as_posix()),
    }


def _state_filesets_to_describe(filesets: list[str] | None, fileset_summary: dict[str, object]) -> list[str]:
    names = [name.strip() for name in filesets or [] if name and name.strip()]
    if names:
        return _dedupe_strings(names)
    rows = fileset_summary.get("filesets") if isinstance(fileset_summary, dict) else []
    if not isinstance(rows, list):
        return []
    interesting: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        category = str(row.get("category") or "").lower()
        name = str(row.get("name") or "")
        if name and category in {"source", "constraint", "simulation"}:
            interesting.append(name)
    return _dedupe_strings(interesting[:8])


def _snapshot_ref(snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.get("snapshot_id"),
        "label": snapshot.get("label"),
        "digest": snapshot.get("digest"),
        "snapshot_path": snapshot.get("snapshot_path"),
        "snapshot_artifact_uri": snapshot.get("snapshot_artifact_uri"),
    }


def _snapshot_timeout(operation_timeout_seconds: int) -> int:
    return min(max(int(operation_timeout_seconds), 30), 120)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def list_debug_cores(
    *,
    workspace: str | Path,
    session_ref: str,
    timeout_seconds: int = 60,
    expect_hardware_access: bool = False,
) -> dict[str, object]:
    from .hardware_summary import parse_debug_cores_tsv
    from .tcl import hw_debug_cores_tcl

    if not expect_hardware_access:
        raise PermissionError("Debug core listing touches live hardware state; pass --expect-hardware-access")
    record = load_session(workspace=workspace, session_ref=session_ref)
    hardware_dir = record.session_dir / "hardware"
    hardware_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = hardware_dir / f"debug_cores_{uuid.uuid4().hex[:8]}.tsv"
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=hw_debug_cores_tcl(tsv_path),
        timeout_seconds=timeout_seconds,
        expect_destructive=False,
    )
    result["expect_hardware_access"] = expect_hardware_access
    result["debug_cores_path"] = str(tsv_path)
    result["debug_cores_artifact_uri"] = artifact_uri(session_ref, tsv_path.relative_to(record.session_dir).as_posix())
    if tsv_path.exists():
        summary = parse_debug_cores_tsv(tsv_path)
        result["debug_cores"] = summary
        json_path = tsv_path.with_suffix(".json")
        json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        result["debug_cores_json_path"] = str(json_path)
        result["debug_cores_json_artifact_uri"] = artifact_uri(
            session_ref,
            json_path.relative_to(record.session_dir).as_posix(),
        )
    return result


def vio_read(
    *,
    workspace: str | Path,
    session_ref: str,
    vio: str,
    probes: list[str] | None = None,
    all_probes: bool = False,
    value_radix: str = "auto",
    timeout_seconds: int = 60,
    expect_hardware_access: bool = False,
) -> dict[str, object]:
    from .hardware_summary import parse_vio_read_tsv
    from .tcl import hw_vio_read_tcl

    if not expect_hardware_access:
        raise PermissionError("VIO read touches live hardware state; pass --expect-hardware-access")
    if not vio.strip():
        raise ValueError("vio must not be empty")
    if not all_probes and not probes:
        raise ValueError("Provide at least one --probe or pass --all-probes")
    record = load_session(workspace=workspace, session_ref=session_ref)
    hardware_dir = record.session_dir / "hardware"
    hardware_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = hardware_dir / f"vio_read_{_safe_artifact_stem(vio)}_{uuid.uuid4().hex[:8]}.tsv"
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=hw_vio_read_tcl(
            tsv_path,
            vio=vio,
            probes=probes,
            all_probes=all_probes,
        ),
        timeout_seconds=timeout_seconds,
        expect_destructive=False,
    )
    result["expect_hardware_access"] = expect_hardware_access
    result["vio"] = vio
    result["probes"] = probes or []
    result["all_probes"] = all_probes
    result["value_radix"] = value_radix
    result["vio_read_path"] = str(tsv_path)
    result["vio_read_artifact_uri"] = artifact_uri(session_ref, tsv_path.relative_to(record.session_dir).as_posix())
    if tsv_path.exists():
        summary = parse_vio_read_tsv(tsv_path, value_radix=value_radix)
        result["vio_read"] = summary
        json_path = tsv_path.with_suffix(".json")
        json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        result["vio_read_json_path"] = str(json_path)
        result["vio_read_json_artifact_uri"] = artifact_uri(
            session_ref,
            json_path.relative_to(record.session_dir).as_posix(),
        )
    return result


def vio_write(
    *,
    workspace: str | Path,
    session_ref: str,
    vio: str,
    writes: list[dict[str, str]],
    value_radix: str = "auto",
    timeout_seconds: int = 60,
    expect_hardware_access: bool = False,
    expect_vio_write: bool = False,
) -> dict[str, object]:
    from .hardware_summary import parse_vio_write_tsv
    from .tcl import hw_vio_write_tcl

    if not expect_hardware_access:
        raise PermissionError("VIO write touches live hardware state; pass --expect-hardware-access")
    if not expect_vio_write:
        raise PermissionError("VIO write changes hardware debug outputs; pass --expect-vio-write")
    if not vio.strip():
        raise ValueError("vio must not be empty")
    if not writes:
        raise ValueError("Provide at least one --set probe=value")
    for write in writes:
        if not str(write.get("probe") or "").strip():
            raise ValueError("VIO write probe must not be empty")
        if str(write.get("value") or "") == "":
            raise ValueError("VIO write value must not be empty")
    record = load_session(workspace=workspace, session_ref=session_ref)
    hardware_dir = record.session_dir / "hardware"
    hardware_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = hardware_dir / f"vio_write_{_safe_artifact_stem(vio)}_{uuid.uuid4().hex[:8]}.tsv"
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=hw_vio_write_tcl(
            tsv_path,
            vio=vio,
            writes=writes,
        ),
        timeout_seconds=timeout_seconds,
        expect_destructive=False,
    )
    result["expect_hardware_access"] = expect_hardware_access
    result["expect_vio_write"] = expect_vio_write
    result["vio"] = vio
    result["writes"] = writes
    result["value_radix"] = value_radix
    result["vio_write_path"] = str(tsv_path)
    result["vio_write_artifact_uri"] = artifact_uri(session_ref, tsv_path.relative_to(record.session_dir).as_posix())
    if tsv_path.exists():
        summary = parse_vio_write_tsv(tsv_path, value_radix=value_radix)
        result["vio_write"] = summary
        json_path = tsv_path.with_suffix(".json")
        json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        result["vio_write_json_path"] = str(json_path)
        result["vio_write_json_artifact_uri"] = artifact_uri(
            session_ref,
            json_path.relative_to(record.session_dir).as_posix(),
        )
    return result


def capture_ila(
    *,
    workspace: str | Path,
    session_ref: str,
    ila: str | None = None,
    cell_name: str | None = None,
    depth: int = 1024,
    label: str | None = None,
    analysis: str = "none",
    sample_rate_hz: float | None = None,
    signed_width: int | None = None,
    timeout_seconds: int = 60,
    expect_hardware_access: bool = False,
) -> dict[str, object]:
    from .hardware_summary import analyze_ila_csv
    from .tcl import hw_ila_capture_tcl

    if not expect_hardware_access:
        raise PermissionError("ILA capture touches live hardware state; pass --expect-hardware-access")
    if not ila and not cell_name:
        raise ValueError("Provide --ila or --cell-name")
    if depth < 1:
        raise ValueError("depth must be greater than zero")
    record = load_session(workspace=workspace, session_ref=session_ref)
    captures_dir = record.session_dir / "hardware"
    captures_dir.mkdir(parents=True, exist_ok=True)
    stem_label = label or ila or cell_name or "ila"
    stem = f"ila_capture_{_safe_artifact_stem(stem_label)}_{uuid.uuid4().hex[:8]}"
    csv_path = captures_dir / f"{stem}.csv"
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=hw_ila_capture_tcl(
            csv_path,
            ila=ila,
            cell_name=cell_name,
            depth=depth,
        ),
        timeout_seconds=timeout_seconds,
        expect_destructive=False,
    )
    result["expect_hardware_access"] = expect_hardware_access
    result["ila"] = ila
    result["cell_name"] = cell_name
    result["depth"] = depth
    result["capture_path"] = str(csv_path)
    result["capture_artifact_uri"] = artifact_uri(session_ref, csv_path.relative_to(record.session_dir).as_posix())
    if csv_path.exists():
        analysis_payload = analyze_ila_csv(
            csv_path,
            mode=analysis,
            sample_rate_hz=sample_rate_hz,
            signed_width=signed_width,
        )
        result["analysis"] = analysis_payload
        if analysis != "none":
            analysis_path = csv_path.with_suffix(".analysis.json")
            analysis_path.write_text(json.dumps(analysis_payload, indent=2, sort_keys=True), encoding="utf-8")
            result["analysis_path"] = str(analysis_path)
            result["analysis_artifact_uri"] = artifact_uri(
                session_ref,
                analysis_path.relative_to(record.session_dir).as_posix(),
            )
    return result


def spi_read(
    *,
    workspace: str | Path,
    session_ref: str,
    vio: str,
    status_probe: str,
    req_probe: str,
    target_probe: str,
    addr_probe: str,
    registers: list[dict[str, int]],
    status_layout: dict[str, object] | None = None,
    status_radix: str = "hex",
    poll_count: int = 80,
    poll_interval_ms: int = 25,
    timeout_seconds: int = 60,
    expect_hardware_access: bool = False,
) -> dict[str, object]:
    from .hardware_summary import normalize_spi_status_layout, parse_spi_read_tsv
    from .tcl import hw_spi_read_tcl

    if not expect_hardware_access:
        raise PermissionError("SPI read touches live hardware state; pass --expect-hardware-access")
    if not vio.strip():
        raise ValueError("vio must not be empty")
    if not all(probe.strip() for probe in (status_probe, req_probe, target_probe, addr_probe)):
        raise ValueError("status, req, target, and addr probes must not be empty")
    if not registers:
        raise ValueError("Provide at least one register with --target/--addr or --reg")
    if poll_count < 1:
        raise ValueError("poll_count must be greater than zero")
    if poll_interval_ms < 0:
        raise ValueError("poll_interval_ms must be zero or greater")

    layout = normalize_spi_status_layout(status_layout)
    record = load_session(workspace=workspace, session_ref=session_ref)
    hardware_dir = record.session_dir / "hardware"
    hardware_dir.mkdir(parents=True, exist_ok=True)
    stem = f"spi_read_{_safe_artifact_stem(vio)}_{uuid.uuid4().hex[:8]}"
    tsv_path = hardware_dir / f"{stem}.tsv"
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=hw_spi_read_tcl(
            tsv_path,
            vio=vio,
            status_probe=status_probe,
            req_probe=req_probe,
            target_probe=target_probe,
            addr_probe=addr_probe,
            registers=registers,
            status_layout=layout,
            status_radix=status_radix,
            poll_count=poll_count,
            poll_interval_ms=poll_interval_ms,
        ),
        timeout_seconds=timeout_seconds,
        expect_destructive=False,
    )
    result["expect_hardware_access"] = expect_hardware_access
    result["vio"] = vio
    result["probes"] = {
        "status": status_probe,
        "req": req_probe,
        "target": target_probe,
        "addr": addr_probe,
    }
    result["registers"] = registers
    result["status_layout"] = layout
    result["status_radix"] = status_radix
    result["poll_count"] = poll_count
    result["poll_interval_ms"] = poll_interval_ms
    result["spi_read_path"] = str(tsv_path)
    result["spi_read_artifact_uri"] = artifact_uri(session_ref, tsv_path.relative_to(record.session_dir).as_posix())
    if tsv_path.exists():
        summary = parse_spi_read_tsv(tsv_path, status_layout=layout, status_radix=status_radix)
        result["spi_read_summary"] = summary
        json_path = tsv_path.with_suffix(".json")
        json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        result["spi_read_json_path"] = str(json_path)
        result["spi_read_json_artifact_uri"] = artifact_uri(
            session_ref,
            json_path.relative_to(record.session_dir).as_posix(),
        )
    return result


def project_summary(
    *,
    workspace: str | Path,
    session_ref: str,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    from .project_summary import parse_project_summary
    from .tcl import project_summary_tcl

    record = load_session(workspace=workspace, session_ref=session_ref)
    output_path = record.session_dir / "summaries" / f"project_summary_{uuid.uuid4().hex[:8]}.tsv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=project_summary_tcl(output_path),
        timeout_seconds=timeout_seconds,
    )
    result["summary_path"] = str(output_path)
    if output_path.exists():
        result["project_summary"] = parse_project_summary(output_path)
    return result


def run_status(
    *,
    workspace: str | Path,
    session_ref: str,
    run_name: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    record = load_session(workspace=workspace, session_ref=session_ref)
    result = project_summary(
        workspace=workspace,
        session_ref=session_ref,
        timeout_seconds=timeout_seconds,
    )
    summary = result.get("project_summary")
    if not isinstance(summary, dict):
        return {
            "ok": bool(result.get("ok")),
            "session_ref": session_ref,
            "summary_path": result.get("summary_path"),
            "runs": [],
            "local_runs": _local_run_records(record, run_name=run_name),
            "error": result.get("error") or "project summary was not produced",
        }

    runs = summary.get("runs")
    if not isinstance(runs, list):
        runs = []
    local_runs = _local_run_records(record, run_name=run_name)
    if run_name:
        runs = [run for run in runs if isinstance(run, dict) and run.get("name") == run_name]
        if not runs and not local_runs:
            raise ValueError(f"Run not found: {run_name}")
    local_by_run = {
        str(local.get("run")): local
        for local in local_runs
        if isinstance(local, dict) and local.get("run")
    }
    merged_runs: list[object] = []
    for run in runs:
        if not isinstance(run, dict):
            merged_runs.append(run)
            continue
        local = local_by_run.get(str(run.get("name") or ""))
        if local is None:
            merged_runs.append(run)
            continue
        merged = dict(run)
        merged["local_run"] = local
        merged_runs.append(merged)
    return {
        "ok": bool(result.get("ok")),
        "session_ref": session_ref,
        "summary_path": result.get("summary_path"),
        "runs": merged_runs,
        "local_runs": local_runs,
    }


def launch_run(
    *,
    workspace: str | Path,
    session_ref: str,
    run_name: str,
    jobs: int | None = None,
    to_step: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    from .tcl import launch_run_tcl

    if not run_name.strip():
        raise ValueError("run_name must not be empty")
    if jobs is not None and jobs < 1:
        raise ValueError("jobs must be greater than zero")
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=launch_run_tcl(run_name=run_name, jobs=jobs, to_step=to_step),
        timeout_seconds=timeout_seconds,
        expect_destructive=False,
    )
    result["run"] = run_name
    result["jobs"] = jobs
    result["to_step"] = to_step
    result["status"] = _parse_key_value_result(str(result.get("result") or ""))
    return result


def diagnose_run(
    *,
    workspace: str | Path,
    session_ref: str,
    run_name: str,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    from .tcl import run_diagnose_tcl

    if not run_name.strip():
        raise ValueError("run_name must not be empty")
    record = load_session(workspace=workspace, session_ref=session_ref)
    safe_run = _safe_artifact_stem(run_name)
    output_path = record.session_dir / "summaries" / f"run_diagnose_{safe_run}_{uuid.uuid4().hex[:8]}.tsv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=run_diagnose_tcl(output_path, run_name),
        timeout_seconds=timeout_seconds,
        expect_destructive=False,
    )
    result["diagnosis_path"] = str(output_path)
    if output_path.exists():
        result["run_diagnosis"] = _parse_run_diagnosis(output_path)
    return result


def reset_run(
    *,
    workspace: str | Path,
    session_ref: str,
    run_name: str,
    timeout_seconds: int = 60,
    expect_destructive: bool = False,
) -> dict[str, object]:
    from .tcl import reset_run_tcl

    if not expect_destructive:
        raise PermissionError("run reset requires --expect-destructive because reset_run discards run outputs")
    if not run_name.strip():
        raise ValueError("run_name must not be empty")
    result = submit_tcl(
        workspace=workspace,
        session_ref=session_ref,
        tcl=reset_run_tcl(run_name),
        timeout_seconds=timeout_seconds,
        expect_destructive=True,
    )
    result["run"] = run_name
    result["status"] = _parse_key_value_result(str(result.get("result") or ""))
    return result


def launch_run_local(
    *,
    workspace: str | Path,
    session_ref: str,
    run_name: str,
    jobs: int | None = None,
    to_step: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    if not run_name.strip():
        raise ValueError("run_name must not be empty")
    if jobs is not None and jobs < 1:
        raise ValueError("jobs must be greater than zero")
    diagnosis_result = diagnose_run(
        workspace=workspace,
        session_ref=session_ref,
        run_name=run_name,
        timeout_seconds=timeout_seconds,
    )
    diagnosis = diagnosis_result.get("run_diagnosis")
    if not isinstance(diagnosis, dict) or diagnosis.get("has_run") is not True:
        raise ValueError(f"Run not found: {run_name}")
    filesystem = diagnosis.get("filesystem")
    if not isinstance(filesystem, dict):
        raise RuntimeError(f"Run directory could not be diagnosed for {run_name}")
    run_dir = Path(str(filesystem.get("path") or ""))
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")
    script = _local_run_script(run_dir)
    prepare_result: dict[str, object] | None = None
    if not script.exists() or to_step is not None:
        prepare_result = launch_run(
            workspace=workspace,
            session_ref=session_ref,
            run_name=run_name,
            jobs=jobs,
            to_step=to_step,
            timeout_seconds=timeout_seconds,
        )
        diagnosis_result = diagnose_run(
            workspace=workspace,
            session_ref=session_ref,
            run_name=run_name,
            timeout_seconds=timeout_seconds,
        )
        diagnosis = diagnosis_result.get("run_diagnosis")
        if not isinstance(diagnosis, dict):
            raise RuntimeError(f"Run directory could not be diagnosed after launch_runs for {run_name}")
        filesystem = diagnosis.get("filesystem")
        if not isinstance(filesystem, dict):
            raise RuntimeError(f"Run directory could not be diagnosed after launch_runs for {run_name}")
        run_dir = Path(str(filesystem.get("path") or ""))
        script = _local_run_script(run_dir)
        if not script.exists():
            raise FileNotFoundError(f"Vivado run script does not exist after launch_runs: {script}")

    record = load_session(workspace=workspace, session_ref=session_ref)
    safe_run = _safe_artifact_stem(run_name)
    local_runs_dir = record.session_dir / "local_runs"
    local_runs_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"vivado_cli_local_{safe_run}_{uuid.uuid4().hex[:8]}.log"
    exit_code_path = local_runs_dir / f"{safe_run}_{uuid.uuid4().hex[:8]}.exitcode"
    wrapper_path = _write_local_run_wrapper(
        script=script,
        exit_code_path=exit_code_path,
        wrapper_path=local_runs_dir / f"{safe_run}_{uuid.uuid4().hex[:8]}{'.cmd' if sys.platform == 'win32' else '.sh'}",
    )
    command, creationflags = _local_run_command(wrapper_path)
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            command,
            cwd=run_dir,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    launch_record = {
        "ok": True,
        "run": run_name,
        "mode": "local_run_script",
        "process_pid": process.pid,
        "local_run_status": "running",
        "prepared": prepare_result is not None,
        "prepare_result": prepare_result,
        "run_dir": str(run_dir),
        "script_path": str(script),
        "wrapper_path": str(wrapper_path),
        "log_path": str(log_path),
        "exit_code_path": str(exit_code_path),
        "diagnosis_path": diagnosis_result.get("diagnosis_path"),
        "status_before_launch": diagnosis.get("properties", {}),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "started_epoch": time.time(),
    }
    record_path = _write_local_run_record(record, launch_record)
    launch_record["local_run_record_path"] = str(record_path)
    return launch_record


def run_logs(
    *,
    workspace: str | Path,
    session_ref: str,
    run_name: str,
    log_name: str | None = None,
    tail_lines: int = 80,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    if tail_lines < 1:
        raise ValueError("tail_lines must be greater than zero")
    diagnosis_result = diagnose_run(
        workspace=workspace,
        session_ref=session_ref,
        run_name=run_name,
        timeout_seconds=timeout_seconds,
    )
    diagnosis = diagnosis_result.get("run_diagnosis")
    if not isinstance(diagnosis, dict) or diagnosis.get("has_run") is not True:
        raise ValueError(f"Run not found: {run_name}")
    filesystem = diagnosis.get("filesystem")
    if not isinstance(filesystem, dict):
        raise RuntimeError(f"Run directory could not be diagnosed for {run_name}")
    run_dir = Path(str(filesystem.get("path") or ""))
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")
    log_path = _select_run_log(run_dir, log_name=log_name)
    if log_path is None:
        return {
            "ok": True,
            "run": run_name,
            "run_dir": str(run_dir),
            "log_path": None,
            "tail_lines": tail_lines,
            "text": "",
            "available_logs": [],
            "diagnosis_path": diagnosis_result.get("diagnosis_path"),
        }
    return {
        "ok": True,
        "run": run_name,
        "run_dir": str(run_dir),
        "log_path": str(log_path),
        "tail_lines": tail_lines,
        "text": _tail_text(log_path, tail_lines),
        "available_logs": [str(path) for path in _run_log_candidates(run_dir)],
        "diagnosis_path": diagnosis_result.get("diagnosis_path"),
    }


def stop_session(
    *,
    workspace: str | Path,
    session_ref: str,
    force: bool = False,
    timeout_seconds: int = 20,
) -> dict[str, object]:
    from .tcl import stop_bridge_tcl

    record = load_session(workspace=workspace, session_ref=session_ref)
    stop_result: dict[str, object] | None = None
    if _pid_running(record.process_pid):
        try:
            _require_cli_bridge(record, operation="stop session through the CLI bridge")
            stop_result = submit_tcl(
                workspace=workspace,
                session_ref=session_ref,
                tcl=stop_bridge_tcl(),
                timeout_seconds=max(5, timeout_seconds // 2),
            )
        except Exception as exc:
            stop_result = {"ok": False, "error": str(exc)}
    deadline = time.time() + timeout_seconds
    while time.time() < deadline and _pid_running(record.process_pid):
        time.sleep(0.1)
    if _pid_running(record.process_pid):
        _terminate_pid(record.process_pid, force=force)
    return {
        "session_ref": session_ref,
        "process_running": _pid_running(record.process_pid),
        "stop_result": stop_result,
        "state": session_state(workspace=workspace, session_ref=session_ref),
    }


def submit_tcl(
    *,
    workspace: str | Path,
    session_ref: str,
    tcl: str,
    timeout_seconds: int,
    expect_destructive: bool = False,
) -> dict[str, object]:
    record = load_session(workspace=workspace, session_ref=session_ref)
    _require_cli_bridge(record, operation="submit Tcl")
    if record.capability_profile == "safe":
        raise PermissionError("Raw Tcl is disabled for safe capability profile")
    result = _submit_tcl(record, tcl=tcl, timeout_seconds=timeout_seconds)
    return _result_to_dict(result, expect_destructive=expect_destructive)


def _submit_tcl(record: CliSessionRecord, *, tcl: str, timeout_seconds: int) -> TclCommandResult:
    if not _pid_running(record.process_pid):
        raise RuntimeError(f"Vivado session process is not running: pid={record.process_pid}")
    command_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    command_path = record.session_dir / "inbox" / f"{command_id}.tcl"
    result_path = record.session_dir / "done" / f"{command_id}.result.txt"
    running_path = record.session_dir / "running" / f"{command_id}.tcl"
    command_path.parent.mkdir(parents=True, exist_ok=True)
    command_path.write_text(tcl, encoding="utf-8")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if result_path.exists():
            final_command_path = running_path if running_path.exists() else command_path
            return _parse_result(command_id, result_path, final_command_path)
        if not _pid_running(record.process_pid):
            grace_deadline = time.time() + 1.0
            while time.time() < grace_deadline:
                if result_path.exists():
                    final_command_path = running_path if running_path.exists() else command_path
                    return _parse_result(command_id, result_path, final_command_path)
                time.sleep(0.05)
            raise RuntimeError(f"Vivado exited before command result was written: pid={record.process_pid}")
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for Tcl command {command_id}")


def _write_record(record: CliSessionRecord, *, record_path: Path | None = None) -> None:
    payload = asdict(record)
    for key in ("session_dir", "workspace_dir", "vivado_path", "log_path", "current_project_path"):
        value = payload.get(key)
        payload[key] = str(value) if value is not None else None
    path = record_path or (record.session_dir / "session.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_key_value_result(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def _safe_artifact_stem(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)
    return safe or "run"


def _local_run_record_path(record: CliSessionRecord, run_name: str) -> Path:
    return record.session_dir / "local_runs" / f"{_safe_artifact_stem(run_name)}.json"


def _write_local_run_record(record: CliSessionRecord, payload: dict[str, object]) -> Path:
    path = _local_run_record_path(record, str(payload.get("run") or "run"))
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(payload)
    saved["last_observed_at"] = datetime.now().isoformat(timespec="seconds")
    saved["last_observed_epoch"] = time.time()
    path.write_text(json.dumps(saved, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _local_run_records(record: CliSessionRecord, *, run_name: str | None = None) -> list[dict[str, object]]:
    if run_name:
        paths = [_local_run_record_path(record, run_name)]
    else:
        paths = sorted((record.session_dir / "local_runs").glob("*.json"))
    records: list[dict[str, object]] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            records.append(
                {
                    "run": path.stem,
                    "local_run_record_path": str(path),
                    "local_run_status": "unreadable",
                    "error": str(exc),
                }
            )
            continue
        if not isinstance(payload, dict):
            records.append(
                {
                    "run": path.stem,
                    "local_run_record_path": str(path),
                    "local_run_status": "unreadable",
                    "error": "local run record is not a JSON object",
                }
            )
            continue
        records.append(_refresh_local_run_record(record, payload, record_path=path))
    return sorted(records, key=lambda item: float(item.get("started_epoch") or 0))


def _refresh_local_run_record(
    record: CliSessionRecord,
    payload: dict[str, object],
    *,
    record_path: Path,
) -> dict[str, object]:
    refreshed = dict(payload)
    exit_code_path = Path(str(refreshed.get("exit_code_path") or ""))
    exit_code = _read_exit_code(exit_code_path)
    process_pid = int(refreshed.get("process_pid") or 0)
    process_running = False if exit_code is not None else _pid_running(process_pid)
    if exit_code is not None:
        refreshed["exit_code"] = exit_code
        refreshed["local_run_status"] = "completed" if exit_code == 0 else "failed"
    elif process_running:
        refreshed["local_run_status"] = "running"
    else:
        refreshed["local_run_status"] = "exited_unknown"
    refreshed["process_running"] = process_running
    refreshed["local_run_record_path"] = str(record_path)
    log_path = Path(str(refreshed.get("log_path") or ""))
    if log_path.is_file():
        refreshed["log_file"] = _file_info(log_path)
    refreshed["last_observed_at"] = datetime.now().isoformat(timespec="seconds")
    refreshed["last_observed_epoch"] = time.time()
    try:
        record_root = record.session_dir.resolve()
        resolved_path = record_path.resolve()
        if record_root in [resolved_path, *resolved_path.parents]:
            record_path.write_text(json.dumps(refreshed, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    return refreshed


def _read_exit_code(path: Path) -> int | None:
    if not str(path) or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    try:
        return int(text.splitlines()[-1])
    except (IndexError, ValueError):
        return None


def _parse_run_diagnosis(path: Path) -> dict[str, object]:
    diagnosis: dict[str, object] = {
        "has_run": False,
        "run": "",
        "properties": {},
        "filesystem": {},
        "issues": [],
    }
    properties: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        key = parts[0]
        values = parts[1:]
        if key == "has_run":
            diagnosis["has_run"] = values[:1] == ["1"]
        elif key == "run":
            diagnosis["run"] = values[0] if values else ""
        elif key == "property" and values:
            properties[values[0]] = values[1] if len(values) > 1 else ""
    diagnosis["properties"] = properties
    diagnosis["filesystem"] = _diagnose_run_directory(properties.get("DIRECTORY") or properties.get("LAUNCH_DIRECTORY") or "")
    diagnosis["issues"] = _diagnose_run_issues(diagnosis)
    return diagnosis


def _diagnose_run_directory(directory: str) -> dict[str, object]:
    if not directory:
        return {"path": "", "exists": False, "queue_markers": [], "logs": [], "recent_files": []}
    path = Path(directory)
    data: dict[str, object] = {
        "path": str(path),
        "exists": path.is_dir(),
        "queue_markers": [],
        "logs": [],
        "recent_files": [],
    }
    if not path.is_dir():
        return data
    try:
        children = [child for child in path.iterdir() if child.is_file()]
    except OSError as exc:
        data["error"] = str(exc)
        return data
    data["queue_markers"] = [_file_info(child) for child in children if child.name.endswith(".queue.rst")]
    data["logs"] = [_file_info(child) for child in children if child.suffix.lower() in {".log", ".jou", ".vds"}]
    data["recent_files"] = [_file_info(child) for child in sorted(children, key=_mtime_or_zero, reverse=True)[:20]]
    return data


def _file_info(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size": stat.st_size,
        "mtime_epoch": stat.st_mtime,
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "age_seconds": max(0, int(time.time() - stat.st_mtime)),
    }


def _mtime_or_zero(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _diagnose_run_issues(diagnosis: dict[str, object]) -> list[dict[str, object]]:
    if diagnosis.get("has_run") is not True:
        return [
            {
                "issue_id": "run.not_found",
                "severity": "error",
                "message": "The requested run does not exist in the current Vivado project.",
                "next_actions": ["Check the run name with `vivado-cli run status`."],
            }
        ]

    properties = diagnosis.get("properties") if isinstance(diagnosis.get("properties"), dict) else {}
    filesystem = diagnosis.get("filesystem") if isinstance(diagnosis.get("filesystem"), dict) else {}
    status = str(properties.get("STATUS") or "")
    progress = str(properties.get("PROGRESS") or "")
    queue_markers = filesystem.get("queue_markers") if isinstance(filesystem, dict) else []
    logs = filesystem.get("logs") if isinstance(filesystem, dict) else []
    issues: list[dict[str, object]] = []
    newest_queue_mtime = max(
        (float(marker.get("mtime_epoch", 0)) for marker in queue_markers if isinstance(marker, dict)),
        default=0.0,
    )
    logs_after_queue = [
        log
        for log in logs
        if isinstance(log, dict) and float(log.get("mtime_epoch", 0)) >= newest_queue_mtime
    ]

    if "fail" in status.lower() or "error" in status.lower():
        issues.append(
            {
                "issue_id": "run.failed",
                "severity": "error",
                "message": f"Run status reports failure: {status}",
                "next_actions": ["Inspect run logs and Vivado messages before relaunching."],
            }
        )
    elif status.startswith("Queued") and queue_markers and not logs_after_queue:
        max_age = max((int(marker.get("age_seconds", 0)) for marker in queue_markers if isinstance(marker, dict)), default=0)
        issues.append(
            {
                "issue_id": "run.queued_without_worker",
                "severity": "warning",
                "message": "The run is queued and the run directory has no current worker log yet.",
                "queue_age_seconds": max_age,
                "stale_logs": [log for log in logs if isinstance(log, dict)],
                "next_actions": [
                    "Poll with `vivado-cli run status --run <name>`.",
                    "If the queue marker keeps aging and no log appears, review the Vivado Run Manager before resetting the run.",
                ],
            }
        )
    elif status == "Not started" and progress == "0%":
        issues.append(
            {
                "issue_id": "run.not_started",
                "severity": "info",
                "message": "The run has not been launched.",
                "next_actions": ["Launch with `vivado-cli run launch <name>` when ready."],
            }
        )

    issues.extend(_diagnose_run_log_issues(filesystem))
    return issues


def _diagnose_run_log_issues(filesystem: dict[str, object]) -> list[dict[str, object]]:
    logs = filesystem.get("logs") if isinstance(filesystem, dict) else []
    if not isinstance(logs, list):
        return []

    texts: list[tuple[str, str]] = []
    for info in sorted(
        (item for item in logs if isinstance(item, dict)),
        key=lambda item: float(item.get("mtime_epoch", 0)),
        reverse=True,
    )[:3]:
        path = Path(str(info.get("path") or ""))
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[-65536:]
        except OSError:
            continue
        texts.append((path.name, text))

    missing_dcp_paths: list[str] = []
    for _name, text in texts:
        missing_dcp_paths.extend(re.findall(r"DCP does not exist:\s*([^\r\n]+)", text))
        missing_dcp_paths.extend(re.findall(r"generated file not found '([^']+\.dcp)'", text))

    if not missing_dcp_paths:
        return []

    unique_paths = list(dict.fromkeys(path.strip() for path in missing_dcp_paths if path.strip()))
    return [
        {
            "issue_id": "run.missing_dcp",
            "severity": "error",
            "message": "The latest run log reports missing IP/OOC DCP files.",
            "missing_dcp_paths": unique_paths[:10],
            "next_actions": [
                "Launch or regenerate the referenced IP/OOC runs before relaunching the top run.",
                "Use `vivado-cli run status` to find queued or not-started *_synth_1 sub-runs.",
            ],
        }
    ]


def _local_run_script(run_dir: Path) -> Path:
    if sys.platform == "win32":
        return run_dir / "runme.bat"
    return run_dir / "runme.sh"


def _write_local_run_wrapper(*, script: Path, exit_code_path: Path, wrapper_path: Path) -> Path:
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        wrapper_path.write_text(
            "\r\n".join(
                [
                    "@echo off",
                    f'call "{script}"',
                    "set \"vivado_cli_exit=%ERRORLEVEL%\"",
                    f'> "{exit_code_path}" echo %vivado_cli_exit%',
                    "exit /b %vivado_cli_exit%",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    else:
        wrapper_path.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f'"{script}"',
                    "vivado_cli_exit=$?",
                    f'printf "%s\\n" "$vivado_cli_exit" > "{exit_code_path}"',
                    'exit "$vivado_cli_exit"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        try:
            wrapper_path.chmod(0o755)
        except OSError:
            pass
    return wrapper_path


def _local_run_command(wrapper_path: Path) -> tuple[list[str], int]:
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return ["cmd.exe", "/d", "/c", str(wrapper_path)], creationflags
    return ["/bin/sh", str(wrapper_path)], 0


def _select_run_log(run_dir: Path, *, log_name: str | None) -> Path | None:
    if log_name:
        requested = run_dir / log_name
        if Path(log_name).is_absolute() or requested.resolve().parent != run_dir.resolve():
            raise PermissionError("log_name must be a filename in the run directory")
        if not requested.exists():
            raise FileNotFoundError(f"Run log does not exist: {requested}")
        return requested
    preferred = _local_run_log_candidates(run_dir)
    preferred.append(run_dir / "runme.log")
    preferred.extend(_run_log_candidates(run_dir))
    seen: set[Path] = set()
    for path in preferred:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file():
            return path
    return None


def _run_log_candidates(run_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in ("*.log", "*.vds", "*.jou"):
        candidates.extend(path for path in run_dir.glob(pattern) if path.is_file())
    return sorted(candidates, key=_mtime_or_zero, reverse=True)


def _local_run_log_candidates(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob("vivado_cli_local_*.log"), key=_mtime_or_zero, reverse=True)


def _tail_text(path: Path, lines: int) -> str:
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def _read_record(path: Path) -> CliSessionRecord:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CliSessionRecord(
        session_ref=str(payload["session_ref"]),
        session_dir=Path(payload["session_dir"]).resolve(),
        workspace_dir=Path(payload["workspace_dir"]).resolve(),
        vivado_path=Path(payload["vivado_path"]).resolve(),
        open_gui=bool(payload["open_gui"]),
        capability_profile=str(payload.get("capability_profile") or "trusted-local"),  # type: ignore[arg-type]
        process_pid=int(payload["process_pid"]),
        log_path=Path(payload["log_path"]).resolve(),
        current_project_path=Path(payload["current_project_path"]).resolve() if payload.get("current_project_path") else None,
        bridge_kind=str(payload.get("bridge_kind") or _detect_bridge_kind(Path(payload["session_dir"]).resolve())),
    )


def _detect_bridge_kind(session_dir: Path) -> str:
    text = " ".join(
        _read_optional_text(path)
        for path in (
            session_dir / "launch_args.txt",
            session_dir / "process.log",
        )
    ).lower()
    normalized = str(session_dir).replace("\\", "/").lower()
    if "cli_bridge.tcl" in text or ".vivado_cli" in normalized:
        return "cli"
    if "mcp_bridge.tcl" in text or ".vivado_mcp" in normalized:
        return "mcp_legacy"
    return "unknown"


def _read_optional_text(path: Path, *, max_chars: int = 8000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _artifact_index(record: CliSessionRecord, *, include_internal: bool) -> dict[str, object]:
    artifacts: list[dict[str, object]] = []
    for path in sorted(record.session_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(record.session_dir).as_posix()
        if not include_internal and relative.startswith(("inbox/", "running/", "done/")):
            continue
        kind = _artifact_kind(path)
        if not include_internal and kind not in {"report", "analysis", "simulation_log", "checkpoint", "snapshot", "summary"}:
            continue
        stat = path.stat()
        row: dict[str, object] = {
            "artifact_id": relative,
            "relative_path": relative,
            "kind": kind,
            "path": str(path),
            "artifact_uri": artifact_uri(record.session_ref, relative),
            "size_bytes": stat.st_size,
            "size": stat.st_size,
            "created_at": _mtime_iso(stat.st_mtime),
            "modified_at": _mtime_iso(stat.st_mtime),
            "tool_hint": _cli_tool_name(_artifact_tool_hint(path, kind)),
        }
        report_type = _report_type_from_artifact(path)
        if report_type:
            row["report_type"] = report_type
        analysis_type = _analysis_type_from_artifact(path)
        if analysis_type:
            row["analysis_type"] = analysis_type
        summary_type = _summary_type_from_artifact(path)
        if summary_type:
            row["summary_type"] = summary_type
        artifacts.append(row)
    artifacts.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("artifact_id") or "")))
    return {"artifacts": artifacts, "count": len(artifacts)}


def _mtime_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def _limit_tail(items: list[Any], limit: int | None) -> list[Any]:
    if limit is None:
        return items
    max_items = max(0, int(limit))
    return items[-max_items:] if max_items else []


def _latest_recovery_artifacts(events: list[object]) -> dict[str, object]:
    latest: dict[str, object] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "")
        analysis_type = str(event.get("analysis_type") or "")
        summary_type = str(event.get("summary_type") or "")
        if kind == "analysis" and analysis_type:
            latest[analysis_type] = event
        elif kind == "snapshot":
            latest["state_snapshot"] = event
        elif kind == "checkpoint":
            latest["checkpoint"] = event
        elif kind == "report":
            latest["report"] = event
        elif kind == "summary" and summary_type:
            latest[f"{summary_type}_summary"] = event
        elif kind == "simulation_log":
            latest["simulation_log"] = event
    return latest


def _read_json_artifact_by_event(record: CliSessionRecord, event: object) -> dict[str, object] | None:
    if not isinstance(event, dict):
        return None
    artifact_id = event.get("artifact_uri") or event.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id:
        return None
    try:
        relative = _artifact_relative(record.session_ref, artifact_id)
        path = (record.session_dir / relative).resolve()
        session_root = record.session_dir.resolve()
        if session_root not in [path, *path.parents] or not path.is_file() or path.suffix.lower() != ".json":
            return None
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError, PermissionError):
        return None


def _cli_recovery_next_action_plan(
    *,
    report_analysis_payload: dict[str, object] | None,
    xsim_analysis_payload: dict[str, object] | None,
    latest: dict[str, object],
) -> list[dict[str, object]]:
    report_plan = _nested_list(report_analysis_payload, ["analysis", "next_action_plan"])
    if report_plan:
        return _normalize_plan_tools(report_plan[:5])
    xsim_plan = _nested_list(xsim_analysis_payload, ["analysis", "next_action_plan"])
    if xsim_plan:
        return _normalize_plan_tools(xsim_plan[:5])
    if latest.get("report_analysis"):
        return [{"tool": "vivado-cli report", "why": "Refresh report diagnostics and inspect quality gates."}]
    if latest.get("simulation_log"):
        return [{"tool": "vivado-cli assist next --goal simulation", "why": "Plan the next simulation log inspection step."}]
    if latest.get("state_snapshot"):
        return [{"tool": "vivado-cli session timeline", "why": "Find a prior snapshot or diff before resuming stateful work."}]
    return [{"tool": "vivado-cli project summary", "why": "No analysis artifact was found; inspect current project state first."}]


def _normalize_plan_tools(plan: list[object]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for item in plan:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        tool = str(row.get("tool") or "")
        row["tool"] = _cli_tool_name(tool)
        normalized.append(row)
    return normalized


def _cli_tool_name(tool: str) -> str:
    aliases = {
        "vivado_session_timeline": "vivado-cli session timeline",
        "vivado_read_artifact": "vivado-cli session read-artifact",
        "vivado_run_tcl": "vivado-cli session run-tcl",
        "vivado_analyze_reports": "vivado-cli report",
        "vivado_project_summary": "vivado-cli project summary",
        "vivado_constraint_diagnostics": "vivado-cli constraint diagnostics",
        "vivado_describe_fileset": "vivado-cli fileset describe",
        "vivado_bd_summary": "vivado-cli bd summary",
        "vivado_capture_state": "vivado-cli session recovery",
        "vivado_list_ips": "vivado-cli tcl help get_ips",
        "vivado_nonproject_audit": "vivado-cli assist next --goal non-project",
        "vivado_nonproject_*_design": "vivado-cli assist next --goal non-project",
        "vivado_simulation_audit": "vivado-cli assist next --goal simulation",
        "vivado_report": "vivado-cli report",
        "vivado_state_diff": "vivado-cli session timeline",
        "vivado_analyze_xsim_logs": "vivado-cli assist next --goal simulation",
    }
    if tool.startswith("vivado-cli "):
        return tool
    return aliases.get(tool, tool or "vivado-cli assist next")


def _cli_recovery_recommendations(latest: dict[str, object], next_action_plan: list[dict[str, object]]) -> list[dict[str, str]]:
    recommendations = [
        {"tool": "vivado-cli session timeline", "why": "Review chronological command, result, report, snapshot, and analysis artifacts before resuming."},
    ]
    if latest.get("report_analysis"):
        recommendations.append({"tool": "vivado-cli session read-artifact", "why": "Read the latest report analysis JSON if more detail is needed."})
    if next_action_plan:
        first = next_action_plan[0]
        recommendations.append(
            {
                "tool": str(first.get("tool") or "vivado-cli assist next"),
                "why": str(first.get("why") or "Continue from the latest analysis recommendation."),
            }
        )
    return recommendations


def _analysis_issue_count(payload: dict[str, object] | None) -> int:
    issues = _nested_list(payload, ["analysis", "issues"])
    return len(issues)


def _snapshot_summary(payload: dict[str, object] | None) -> dict[str, object]:
    if not payload:
        return {}
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    return {
        "snapshot": snapshot,
        "current_project": project.get("current_project") if isinstance(project, dict) else None,
        "errors": payload.get("errors", []),
    }


def _nested_list(payload: dict[str, object] | None, keys: list[str]) -> list[object]:
    value: object = payload
    for key in keys:
        if not isinstance(value, dict):
            return []
        value = value.get(key)
    return value if isinstance(value, list) else []


def _nested_dict(payload: dict[str, object] | None, keys: list[str]) -> dict[str, object] | None:
    value: object = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, dict) else None


def _bridge_state(record: CliSessionRecord) -> dict[str, object]:
    kind = record.bridge_kind or _detect_bridge_kind(record.session_dir)
    pending = _count_files(record.session_dir / "inbox", "*.tcl")
    running_artifacts = _count_files(record.session_dir / "running", "*.tcl")
    done = _count_files(record.session_dir / "done", "*.result.txt")
    incomplete = _count_running_without_result(record.session_dir)
    compatible = kind == "cli"
    recommendations: list[str] = []
    if not compatible:
        recommendations.append("start a fresh CLI session with `vivado-cli session start`; do not run CLI Tcl against this bridge")
    if pending:
        recommendations.append("pending Tcl commands are still in inbox; the bridge may be stale or incompatible")
    if incomplete:
        recommendations.append("running Tcl artifacts without result files remain; the bridge may have been interrupted")
    if incomplete and not _pid_running(record.process_pid):
        recommendations.append("incomplete Tcl commands remain but the Vivado process is gone; clean up the session or start a new one")
    return {
        "kind": kind,
        "compatible": compatible,
        "pending_inbox": pending,
        "running_artifacts": running_artifacts,
        "incomplete_commands": incomplete,
        "done_results": done,
        "recommendations": recommendations,
    }


def _count_files(directory: Path, pattern: str) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.glob(pattern) if path.is_file())


def _count_running_without_result(session_dir: Path) -> int:
    running_dir = session_dir / "running"
    done_dir = session_dir / "done"
    if not running_dir.is_dir():
        return 0
    count = 0
    for path in running_dir.glob("*.tcl"):
        if not (done_dir / f"{path.stem}.result.txt").exists():
            count += 1
    return count


def _require_cli_bridge(record: CliSessionRecord, *, operation: str) -> None:
    state = _bridge_state(record)
    if state["kind"] != "cli":
        raise RuntimeError(
            f"Cannot {operation}: session {record.session_ref!r} uses bridge_kind={state['kind']!r}. "
            "Start or adopt a vivado-cli cli_bridge.tcl session instead."
        )


def _wait_for_status(session_dir: Path, expected: str, *, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    status_path = session_dir / "status.txt"
    while time.time() < deadline:
        status = _read_status(status_path)
        if status.get("state") == expected:
            return
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for session status {expected!r}")


def _read_status(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            result[key] = value
    return result


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return f'"{pid}"' in completed.stdout or f",{pid}," in completed.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except PermissionError:
        return True


def _terminate_pid(pid: int, *, force: bool) -> None:
    import signal

    try:
        if sys.platform == "win32":
            args = ["taskkill", "/PID", str(pid)]
            if force:
                args.append("/F")
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
