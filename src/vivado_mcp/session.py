from __future__ import annotations

import os
import json
import re
import signal
import subprocess
import threading
import time
import uuid
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote

from .gui_probe import probe_vivado_gui, wait_for_vivado_gui
from .policy import PathPolicy
from .tcl import stop_bridge_tcl
from .types import CapabilityProfile, SessionRecord, TclCommandResult
from .vivado_locator import _vivado_command, locate_vivado


class VivadoSessionError(RuntimeError):
    pass


class VivadoSessionManager:
    def __init__(self, default_workspace: Path | None = None, path_policy: PathPolicy | None = None) -> None:
        self.default_workspace = (default_workspace or Path.cwd()).resolve()
        self.path_policy = path_policy or PathPolicy.from_environment(self.default_workspace)
        self._sessions: dict[str, _RunningSession] = {}
        self._lock = threading.Lock()

    def start_session(
        self,
        *,
        vivado_path: str | None = None,
        workspace_dir: str | None = None,
        open_gui: bool = True,
        capability_profile: CapabilityProfile = "trusted-local",
        startup_timeout_seconds: int = 45,
        gui_wait_seconds: int = 20,
        activate_gui: bool = False,
    ) -> dict[str, object]:
        workspace = self.path_policy.require_under_roots(
            workspace_dir or self.default_workspace,
            label="workspace_dir",
            must_exist=False,
        )
        workspace.mkdir(parents=True, exist_ok=True)

        executable = locate_vivado(vivado_path)
        session_ref = uuid.uuid4().hex
        session_dir = workspace / ".vivado_mcp" / "sessions" / session_ref
        session_dir.mkdir(parents=True, exist_ok=True)
        log_path = session_dir / "process.log"
        bridge = resources.files("vivado_mcp.assets").joinpath("mcp_bridge.tcl")

        args = [
            "-mode",
            "tcl",
            "-source",
            str(bridge),
            "-tclargs",
            str(session_dir),
        ]
        if open_gui:
            args.append("--gui")
        command = _vivado_command(executable, args)

        log_file = log_path.open("w", encoding="utf-8", errors="replace")
        process = subprocess.Popen(
            command,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output_thread = threading.Thread(target=_pipe_output, args=(process, log_file), daemon=True)
        output_thread.start()

        record = SessionRecord(
            session_ref=session_ref,
            vivado_path=executable,
            session_dir=session_dir,
            workspace_dir=workspace,
            open_gui=open_gui,
            capability_profile=capability_profile,
            log_path=log_path,
        )
        running = _RunningSession(record=record, process=process, log_file=log_file, output_thread=output_thread)

        try:
            self._wait_for_idle(running, startup_timeout_seconds)
            gui_state = self._wait_for_gui(running, timeout_seconds=gui_wait_seconds, activate=activate_gui)
        except Exception:
            if process.poll() is None:
                process.terminate()
            log_file.close()
            raise

        with self._lock:
            self._sessions[session_ref] = running

        state = self.session_state(session_ref)
        return {
            "session_ref": session_ref,
            "vivado_path": str(executable),
            "session_dir": str(session_dir),
            "open_gui": open_gui,
            "capability_profile": capability_profile,
            "allowed_roots": [str(root) for root in self.path_policy.roots],
            "gui": gui_state,
            "state": state,
        }

    def list_sessions(self) -> dict[str, object]:
        with self._lock:
            refs = list(self._sessions)
        sessions: list[dict[str, object]] = []
        for session_ref in refs:
            try:
                sessions.append(self.session_state(session_ref))
            except KeyError:
                continue
        return {"sessions": sessions}

    def session_state(self, session_ref: str) -> dict[str, object]:
        running = self._get(session_ref)
        status = _read_status(running.record.session_dir / "status.txt")
        return {
            "session_ref": session_ref,
            "process_running": running.process.poll() is None,
            "process_exit_code": running.process.poll(),
            "status": status,
            "gui": self._gui_state(running, activate=False),
            "session_dir": str(running.record.session_dir),
            "workspace_dir": str(running.record.workspace_dir),
            "log_path": str(running.record.log_path),
            "open_gui": running.record.open_gui,
            "capability_profile": running.record.capability_profile,
            "allowed_roots": [str(root) for root in self.path_policy.roots],
        }

    def list_artifacts(
        self,
        session_ref: str,
        *,
        kind: str | None = None,
        report_type: str | None = None,
    ) -> dict[str, object]:
        running = self._get(session_ref)
        artifacts = self._artifact_index_for_running(running, include_all=True)["artifacts"]
        if kind:
            artifacts = [artifact for artifact in artifacts if artifact.get("kind") == kind]
        if report_type:
            artifacts = [artifact for artifact in artifacts if artifact.get("report_type") == report_type]
        return {"session_ref": session_ref, "artifacts": artifacts, "count": len(artifacts)}

    def session_timeline(
        self,
        *,
        session_ref: str,
        kind: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        running = self._get(session_ref)
        events = self._artifact_index_for_running(running, include_all=True)["artifacts"]
        if kind:
            events = [event for event in events if event.get("kind") == kind]
        events.sort(key=lambda event: (str(event.get("created_at") or ""), str(event.get("artifact_id") or "")))
        if limit is not None:
            max_events = max(0, int(limit))
            events = events[-max_events:] if max_events else []
        counts = dict(Counter(str(event.get("kind") or "other") for event in events))
        return {
            "session_ref": session_ref,
            "session_dir": str(running.record.session_dir),
            "events": events,
            "counts": counts,
            "count": len(events),
        }

    def recovery_brief(self, *, session_ref: str) -> dict[str, object]:
        running = self._get(session_ref)
        timeline = self.session_timeline(session_ref=session_ref)
        events = timeline["events"] if isinstance(timeline.get("events"), list) else []
        latest = _latest_recovery_artifacts(events)
        report_analysis_payload = self._read_json_artifact_by_uri(running, latest.get("report_analysis"))
        xsim_analysis_payload = self._read_json_artifact_by_uri(running, latest.get("xsim_log_analysis"))
        snapshot_payload = self._read_json_artifact_by_uri(running, latest.get("state_snapshot"))
        next_action_plan = _recovery_next_action_plan(
            report_analysis_payload=report_analysis_payload,
            xsim_analysis_payload=xsim_analysis_payload,
            latest=latest,
        )
        return {
            "ok": True,
            "session_ref": session_ref,
            "session_dir": str(running.record.session_dir),
            "current_project_path": str(running.record.current_project_path) if running.record.current_project_path else None,
            "latest": latest,
            "summary": {
                "event_count": timeline.get("count", 0),
                "counts": timeline.get("counts", {}),
                "report_analysis_issue_count": _analysis_issue_count(report_analysis_payload),
                "xsim_issue_count": _analysis_issue_count(xsim_analysis_payload),
            },
            "quality_gates": _recovery_quality_gates(report_analysis_payload),
            "next_action_plan": next_action_plan,
            "recommendations": _recovery_recommendations(latest, next_action_plan),
            "timeline_preview": events[-10:],
            "state_snapshot": _snapshot_summary(snapshot_payload),
        }

    def read_artifact(self, session_ref: str, artifact_id: str, max_chars: int = 20000) -> dict[str, object]:
        running = self._get(session_ref)
        relative = _artifact_relative(running.record.session_ref, artifact_id)
        path = (running.record.session_dir / relative).resolve()
        session_root = running.record.session_dir.resolve()
        if session_root not in [path, *path.parents]:
            raise PermissionError("Artifact path escapes session directory")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {relative}")
        text = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars] + "\n\n[truncated]\n"
        return {
            "session_ref": session_ref,
            "artifact_id": artifact_id,
            "relative_path": relative,
            "path": str(path),
            "artifact_uri": artifact_uri(session_ref, relative),
            "text": text,
            "truncated": truncated,
        }

    def capture_state(
        self,
        *,
        session_ref: str,
        label: str | None = None,
        include_bd: bool = True,
        validate_bd: bool = False,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .state_diff import state_digest

        running = self._get(session_ref)
        snapshots_dir = running.record.session_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_id = f"state_{_safe_label(label)}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        output_path = snapshots_dir / f"{snapshot_id}.json"

        state = self._collect_state(
            running=running,
            include_bd=include_bd,
            validate_bd=validate_bd,
            timeout_seconds=timeout_seconds,
        )
        state["snapshot"] = {
            "id": snapshot_id,
            "label": label,
            "created_at": _timestamp(),
            "digest": state_digest(state),
        }
        output_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "ok": True,
            "session_ref": session_ref,
            "snapshot_id": snapshot_id,
            "label": label,
            "digest": state["snapshot"]["digest"],
            "state": state,
            "snapshot_path": str(output_path),
            "snapshot_artifact_uri": artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix()),
        }

    def state_diff(
        self,
        *,
        session_ref: str,
        before_artifact_id: str | None = None,
        after_artifact_id: str | None = None,
        before_state: dict[str, object] | None = None,
        after_state: dict[str, object] | None = None,
    ) -> dict[str, object]:
        from .state_diff import diff_states

        running = self._get(session_ref)
        before = before_state or self._read_state_artifact(running, before_artifact_id, label="before_artifact_id")
        after = after_state or self._read_state_artifact(running, after_artifact_id, label="after_artifact_id")
        diff = diff_states(before, after)
        diffs_dir = running.record.session_dir / "diffs"
        diffs_dir.mkdir(parents=True, exist_ok=True)
        output_path = diffs_dir / f"state_diff_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.json"
        output_path.write_text(json.dumps(diff, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "ok": True,
            "session_ref": session_ref,
            "changed": diff["changed"],
            "diff": diff,
            "diff_path": str(output_path),
            "diff_artifact_uri": artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix()),
        }

    def run_tcl(
        self,
        *,
        session_ref: str,
        tcl: str,
        timeout_seconds: int = 60,
        expect_destructive: bool = False,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        running = self._get(session_ref)
        if running.record.capability_profile == "safe":
            raise PermissionError("Raw Tcl is disabled for safe capability profile")
        return self._capture_diff_around(
            running=running,
            label="run_tcl",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(running, tcl, timeout_seconds=timeout_seconds),
                expect_destructive=expect_destructive,
            ),
        )

    def source_tcl(
        self,
        *,
        session_ref: str,
        script_path: str,
        tclargs: list[str] | None = None,
        timeout_seconds: int = 120,
        expect_destructive: bool = False,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import quote_tcl, set_argv_tcl

        path = Path(script_path).resolve()
        running = self._get(session_ref)
        if running.record.capability_profile == "safe":
            raise PermissionError("Raw Tcl is disabled for safe capability profile")
        if running.record.capability_profile != "unrestricted":
            path = self.path_policy.require_under_roots(path, label="script_path", must_exist=True)
        if not path.exists():
            raise FileNotFoundError(f"Tcl script does not exist: {path}")
        args = tclargs or []
        body = "\n".join(
            [
                set_argv_tcl(args),
                f"source {quote_tcl(path)}",
            ]
        )
        return self._capture_diff_around(
            running=running,
            label="source_tcl",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    tcl=body,
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=expect_destructive,
            ),
        )

    def tcl_command_help(self, *, session_ref: str, command: str, timeout_seconds: int = 30) -> dict[str, object]:
        from .tcl import quote_tcl

        if not command.strip():
            raise ValueError("command must not be empty")
        running = self._get(session_ref)
        tcl = f"return [help {quote_tcl(command)}]"
        result = self._submit_tcl(running, tcl, timeout_seconds=timeout_seconds)
        return _result_to_dict(result, expect_destructive=False)

    def stop_session(self, session_ref: str, *, force: bool = False, timeout_seconds: int = 20) -> dict[str, object]:
        running = self._get(session_ref)
        gui_before_stop = self._gui_state(running, activate=False)
        managed_gui_pids = _managed_gui_pids(gui_before_stop)
        stop_result: dict[str, object] | None = None
        if running.process.poll() is None:
            try:
                result = self._submit_tcl(running, stop_bridge_tcl(), timeout_seconds=max(5, timeout_seconds // 2))
                stop_result = _result_to_dict(result, expect_destructive=False)
            except Exception as exc:
                stop_result = {"error": str(exc)}

        deadline = time.time() + timeout_seconds
        while time.time() < deadline and running.process.poll() is None:
            time.sleep(0.1)

        if running.process.poll() is None:
            if force:
                running.process.kill()
            else:
                running.process.terminate()
            try:
                running.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                running.process.kill()
                running.process.wait(timeout=10)

        running.log_file.close()
        gui_cleanup = _terminate_processes(managed_gui_pids)
        with self._lock:
            self._sessions.pop(session_ref, None)

        return {
            "session_ref": session_ref,
            "process_exit_code": running.process.returncode,
            "stop_result": stop_result,
            "gui_before_stop": gui_before_stop,
            "gui_cleanup": gui_cleanup,
            "log_path": str(running.record.log_path),
        }

    def create_project(
        self,
        *,
        session_ref: str,
        project_name: str,
        project_dir: str,
        part: str | None = None,
        board_part: str | None = None,
        force: bool = False,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .tcl import create_project_tcl

        if not part and not board_part:
            raise ValueError("Either part or board_part is required")
        tcl = create_project_tcl(
            project_name=project_name,
            project_dir=self.path_policy.require_under_roots(project_dir, label="project_dir", must_exist=False),
            part=part,
            board_part=board_part,
            force=force,
        )
        running = self._get(session_ref)
        result = self._submit_tcl(running, tcl, timeout_seconds=timeout_seconds)
        return _result_to_dict(result, expect_destructive=force)

    def open_project(
        self,
        *,
        session_ref: str,
        project_path: str,
        timeout_seconds: int = 120,
        gui_wait_seconds: int = 20,
        focus_gui: bool = False,
    ) -> dict[str, object]:
        from .tcl import open_project_tcl

        running = self._get(session_ref)
        path = self.path_policy.require_under_roots(project_path, label="project_path", must_exist=True)
        result = self._submit_tcl(running, open_project_tcl(path), timeout_seconds=timeout_seconds)
        if result.ok:
            running.record.current_project_path = path
        data = _result_to_dict(result, expect_destructive=False)
        data["gui"] = self._wait_for_gui(running, timeout_seconds=gui_wait_seconds, activate=focus_gui)
        return data

    def focus_gui(self, session_ref: str, *, timeout_seconds: int = 10) -> dict[str, object]:
        running = self._get(session_ref)
        return {
            "session_ref": session_ref,
            "gui": self._wait_for_gui(running, timeout_seconds=timeout_seconds, activate=True),
        }

    def add_sources(
        self,
        *,
        session_ref: str,
        sources: list[str] | None = None,
        constraints: list[str] | None = None,
        top: str | None = None,
        sources_fileset: str | None = None,
        include_dirs: list[str] | None = None,
        defines: list[str] | None = None,
        library: str | None = None,
        file_type: str | None = None,
        used_in: list[str] | None = None,
        processing_order: int | None = None,
        timeout_seconds: int = 120,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import add_sources_tcl

        source_paths = [self.path_policy.require_under_roots(path, label="source", must_exist=True) for path in sources or []]
        constraint_paths = [
            self.path_policy.require_under_roots(path, label="constraint", must_exist=True) for path in constraints or []
        ]
        include_paths = [
            self.path_policy.require_under_roots(path, label="include_dir", must_exist=False) for path in include_dirs or []
        ]
        running = self._get(session_ref)
        return self._capture_diff_around(
            running=running,
            label="add_sources",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    add_sources_tcl(
                        sources=source_paths,
                        constraints=constraint_paths,
                        top=top,
                        sources_fileset=sources_fileset,
                        include_dirs=include_paths,
                        defines=defines,
                        library=library,
                        file_type=file_type,
                        used_in=used_in,
                        processing_order=processing_order,
                    ),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=False,
            ),
        )

    def remove_sources(
        self,
        *,
        session_ref: str,
        paths: list[str],
        fileset: str | None = None,
        force: bool = False,
        timeout_seconds: int = 120,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import remove_files_tcl

        if not paths:
            raise ValueError("paths must contain at least one source to remove")
        resolved = [self.path_policy.require_under_roots(path, label="source", must_exist=True) for path in paths]
        running = self._get(session_ref)
        return self._capture_diff_around(
            running=running,
            label="remove_sources",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    remove_files_tcl(paths=resolved, fileset=fileset, force=force),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=True,
            ),
        )

    def set_file_properties(
        self,
        *,
        session_ref: str,
        paths: list[str],
        properties: dict[str, object],
        fileset: str | None = None,
        timeout_seconds: int = 60,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import set_file_properties_tcl

        if not paths:
            raise ValueError("paths must contain at least one file")
        if not properties:
            raise ValueError("properties must contain at least one key/value pair")
        resolved = [self.path_policy.require_under_roots(path, label="file", must_exist=True) for path in paths]
        running = self._get(session_ref)
        return self._capture_diff_around(
            running=running,
            label="set_file_properties",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    set_file_properties_tcl(paths=resolved, properties=properties, fileset=fileset),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=True,
            ),
        )

    def set_top(
        self,
        *,
        session_ref: str,
        top: str | None = None,
        fileset: str | None = None,
        timeout_seconds: int = 60,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import set_top_tcl

        running = self._get(session_ref)
        return self._capture_diff_around(
            running=running,
            label="set_top",
            capture_diff=capture_diff and top is not None,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    set_top_tcl(top=top, fileset=fileset),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=top is not None,
            ),
        )

    def list_filesets(
        self,
        *,
        session_ref: str,
        timeout_seconds: int = 60,
    ) -> dict[str, object]:
        from .fileset_summary import parse_list_filesets
        from .tcl import list_filesets_tcl

        running = self._get(session_ref)
        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"filesets_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(
            running,
            list_filesets_tcl(output_path),
            timeout_seconds=timeout_seconds,
        )
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["filesets"] = parse_list_filesets(output_path)
        return result

    def create_fileset(
        self,
        *,
        session_ref: str,
        name: str,
        kind: str = "constrs",
        timeout_seconds: int = 120,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import create_fileset_tcl

        if not name.strip():
            raise ValueError("fileset name must not be empty")
        running = self._get(session_ref)
        return self._capture_diff_around(
            running=running,
            label="create_fileset",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    create_fileset_tcl(name=name, kind=kind),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=True,
            ),
        )

    def describe_fileset(
        self,
        *,
        session_ref: str,
        name: str,
        timeout_seconds: int = 60,
    ) -> dict[str, object]:
        if not name.strip():
            raise ValueError("fileset name must not be empty")
        running = self._get(session_ref)
        return self._describe_fileset_for_running(running, name=name, timeout_seconds=timeout_seconds)

    def constraint_diagnostics(
        self,
        *,
        session_ref: str,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .fileset_summary import parse_constraint_diagnostics
        from .tcl import constraint_diagnostics_tcl

        running = self._get(session_ref)
        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"constraint_diag_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(
            running,
            constraint_diagnostics_tcl(output_path),
            timeout_seconds=timeout_seconds,
        )
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["diagnostics"] = parse_constraint_diagnostics(output_path)
        return result

    def source_audit(
        self,
        *,
        session_ref: str,
        filesets: list[str] | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .fileset_summary import analyze_source_audit

        running = self._get(session_ref)
        project = self._project_summary_for_running(running, timeout_seconds=timeout_seconds)
        fileset_list = self._list_filesets_for_running(running, timeout_seconds=timeout_seconds)
        constraints = self._constraint_diagnostics_for_running(running, timeout_seconds=timeout_seconds)
        available = fileset_list.get("filesets", {})
        selected_names = filesets or [
            str(row.get("name"))
            for row in available.get("filesets", [])
            if isinstance(row, dict) and _fileset_category(row) in {"source", "simulation", "constraint"}
        ]
        described: list[dict[str, object]] = []
        describe_errors: list[dict[str, object]] = []
        for name in selected_names:
            try:
                desc = self._describe_fileset_for_running(running, name=name, timeout_seconds=timeout_seconds)
            except Exception as exc:
                describe_errors.append({"fileset": name, "error": str(exc)})
                continue
            if "fileset_summary" in desc:
                described.append(desc["fileset_summary"])
        audit = analyze_source_audit(
            project.get("project_summary", {}),
            available,
            described,
            constraints.get("diagnostics", {}),
        )
        if describe_errors:
            audit.setdefault("issues", []).append(
                {
                    "issue_id": "fileset.describe_failed",
                    "severity": "medium",
                    "filesets": describe_errors,
                }
            )
        audits_dir = running.record.session_dir / "audits"
        audits_dir.mkdir(parents=True, exist_ok=True)
        output_path = audits_dir / f"source_audit_{uuid.uuid4().hex[:8]}.json"
        output_path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "ok": True,
            "session_ref": session_ref,
            "audit": audit,
            "audit_path": str(output_path),
            "audit_artifact_uri": artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix()),
            "project_summary_artifact_uri": project.get("summary_artifact_uri"),
            "filesets_summary_artifact_uri": fileset_list.get("summary_artifact_uri"),
            "constraint_diagnostics_artifact_uri": constraints.get("summary_artifact_uri"),
        }

    def xdc_order_check(self, *, session_ref: str, timeout_seconds: int = 120) -> dict[str, object]:
        from .fileset_summary import analyze_xdc_order

        running = self._get(session_ref)
        diagnostics = self._constraint_diagnostics_for_running(running, timeout_seconds=timeout_seconds)
        order = analyze_xdc_order(diagnostics.get("diagnostics", {}))
        audits_dir = running.record.session_dir / "audits"
        audits_dir.mkdir(parents=True, exist_ok=True)
        output_path = audits_dir / f"xdc_order_{uuid.uuid4().hex[:8]}.json"
        output_path.write_text(json.dumps(order, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "ok": True,
            "session_ref": session_ref,
            "order": order,
            "order_path": str(output_path),
            "order_artifact_uri": artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix()),
            "constraint_diagnostics_artifact_uri": diagnostics.get("summary_artifact_uri"),
        }

    def fileset_apply(
        self,
        *,
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
        from .tcl import fileset_apply_tcl

        include_paths = (
            None
            if include_dirs is None
            else [self.path_policy.require_under_roots(path, label="include_dir", must_exist=False) for path in include_dirs]
        )
        running = self._get(session_ref)
        if dry_run:
            return {
                "ok": True,
                "session_ref": session_ref,
                "dry_run": True,
                "expect_destructive": True,
                "plan": _fileset_apply_plan(
                    fileset=fileset,
                    include_dirs=include_paths,
                    defines=defines,
                    top=top,
                    properties=properties,
                    update_compile_order=update_compile_order,
                ),
            }
        return self._capture_diff_around(
            running=running,
            label="fileset_apply",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    fileset_apply_tcl(
                        fileset=fileset,
                        include_dirs=include_paths,
                        defines=defines,
                        top=top,
                        properties=properties,
                        update_compile_order=update_compile_order,
                    ),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=True,
            ),
        )

    def constraint_set_apply(
        self,
        *,
        session_ref: str,
        fileset: str,
        create_if_missing: bool = False,
        add: list[str] | None = None,
        remove: list[str] | None = None,
        used_in: list[str] | None = None,
        reorder: list[str] | None = None,
        active: bool | None = None,
        timeout_seconds: int = 120,
        capture_diff: bool = False,
        dry_run: bool = False,
    ) -> dict[str, object]:
        from .tcl import constraint_set_apply_tcl

        add_paths = [self.path_policy.require_under_roots(path, label="constraint", must_exist=True) for path in add or []]
        remove_paths = [self.path_policy.require_under_roots(path, label="constraint", must_exist=True) for path in remove or []]
        reorder_paths = [self.path_policy.require_under_roots(path, label="constraint", must_exist=True) for path in reorder or []]
        running = self._get(session_ref)
        if dry_run:
            return {
                "ok": True,
                "session_ref": session_ref,
                "dry_run": True,
                "expect_destructive": True,
                "plan": _constraint_set_apply_plan(
                    fileset=fileset,
                    create_if_missing=create_if_missing,
                    add=add_paths,
                    remove=remove_paths,
                    used_in=used_in,
                    reorder=reorder_paths,
                    active=active,
                ),
            }
        return self._capture_diff_around(
            running=running,
            label="constraint_set_apply",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    constraint_set_apply_tcl(
                        fileset=fileset,
                        create_if_missing=create_if_missing,
                        add=add_paths,
                        remove=remove_paths,
                        used_in=used_in,
                        reorder=reorder_paths,
                        active=active,
                    ),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=True,
            ),
        )

    def bd_open_or_create(
        self,
        *,
        session_ref: str,
        design_name: str | None = None,
        bd_path: str | None = None,
        create_if_missing: bool = True,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .tcl import bd_open_or_create_tcl

        running = self._get(session_ref)
        resolved_bd_path = self.path_policy.require_under_roots(bd_path, label="bd_path", must_exist=True) if bd_path else None
        result = self._submit_tcl(
            running,
            bd_open_or_create_tcl(design_name=design_name, bd_path=resolved_bd_path, create_if_missing=create_if_missing),
            timeout_seconds=timeout_seconds,
        )
        return _result_to_dict(result, expect_destructive=create_if_missing)

    def bd_summary(
        self,
        *,
        session_ref: str,
        design_name: str | None = None,
        bd_path: str | None = None,
        validate: bool = False,
        timeout_seconds: int = 60,
    ) -> dict[str, object]:
        from .bd_summary import parse_bd_summary
        from .tcl import bd_summary_tcl

        running = self._get(session_ref)
        resolved_bd_path = self.path_policy.require_under_roots(bd_path, label="bd_path", must_exist=True) if bd_path else None
        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"bd_summary_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(
            running,
            bd_summary_tcl(output_path, design_name=design_name, bd_path=resolved_bd_path, validate=validate),
            timeout_seconds=timeout_seconds,
        )
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["bd_summary"] = parse_bd_summary(output_path)
        return result

    def bd_audit(
        self,
        *,
        session_ref: str,
        design_name: str | None = None,
        bd_path: str | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .bd_summary import analyze_bd_audit

        summary = self.bd_summary(
            session_ref=session_ref,
            design_name=design_name,
            bd_path=bd_path,
            validate=True,
            timeout_seconds=timeout_seconds,
        )
        bd_state = summary.get("bd_summary") if isinstance(summary.get("bd_summary"), dict) else {}
        audit = analyze_bd_audit(bd_state)
        audit["session_ref"] = session_ref
        audit["summary_path"] = summary.get("summary_path", "")
        audit["summary_artifact_uri"] = summary.get("summary_artifact_uri", "")
        return audit

    def bd_apply(
        self,
        *,
        session_ref: str,
        actions: list[dict[str, object]],
        design_name: str | None = None,
        bd_path: str | None = None,
        validate: bool = True,
        save: bool = True,
        timeout_seconds: int = 300,
        capture_diff: bool = False,
        dry_run: bool = False,
    ) -> dict[str, object]:
        from .tcl import bd_apply_tcl

        if not actions:
            raise ValueError("actions must contain at least one BD action")
        running = self._get(session_ref)
        resolved_bd_path = self.path_policy.require_under_roots(bd_path, label="bd_path", must_exist=True) if bd_path else None
        if dry_run:
            return {
                "ok": True,
                "session_ref": session_ref,
                "dry_run": True,
                "expect_destructive": True,
                "plan": _bd_apply_plan(
                    actions=actions,
                    design_name=design_name,
                    bd_path=resolved_bd_path,
                    validate=validate,
                    save=save,
                ),
            }
        return self._capture_diff_around(
            running=running,
            label="bd_apply",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    bd_apply_tcl(actions=actions, design_name=design_name, bd_path=resolved_bd_path, validate=validate, save=save),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=True,
            ),
        )

    def bd_validate(
        self,
        *,
        session_ref: str,
        design_name: str | None = None,
        bd_path: str | None = None,
        save: bool = False,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .bd_summary import parse_bd_validate_result
        from .tcl import bd_validate_tcl

        running = self._get(session_ref)
        resolved_bd_path = self.path_policy.require_under_roots(bd_path, label="bd_path", must_exist=True) if bd_path else None
        raw_result = self._submit_tcl(
            running,
            bd_validate_tcl(design_name=design_name, bd_path=resolved_bd_path, save=save),
            timeout_seconds=timeout_seconds,
        )
        result = _result_to_dict(raw_result, expect_destructive=save)
        result["validation"] = parse_bd_validate_result(str(result.get("result") or ""))
        return result

    def bd_generate(
        self,
        *,
        session_ref: str,
        design_name: str | None = None,
        bd_path: str | None = None,
        target: str = "all",
        make_wrapper: bool = True,
        wrapper_top: bool = True,
        timeout_seconds: int = 600,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import bd_generate_tcl

        running = self._get(session_ref)
        resolved_bd_path = self.path_policy.require_under_roots(bd_path, label="bd_path", must_exist=True) if bd_path else None
        return self._capture_diff_around(
            running=running,
            label="bd_generate",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    bd_generate_tcl(
                        design_name=design_name,
                        bd_path=resolved_bd_path,
                        target=target,
                        make_wrapper=make_wrapper,
                        wrapper_top=wrapper_top,
                    ),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=True,
            ),
        )

    def launch_run(
        self,
        *,
        session_ref: str,
        run_name: str,
        jobs: int | None = None,
        to_step: str | None = None,
        timeout_seconds: int = 3600,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import launch_run_tcl

        running = self._get(session_ref)
        return self._capture_diff_around(
            running=running,
            label=f"launch_run_{run_name}",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    launch_run_tcl(run_name=run_name, jobs=jobs, to_step=to_step),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=False,
            ),
        )

    def report(
        self,
        *,
        session_ref: str,
        report_type: str,
        output_name: str | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, object]:
        from .tcl import report_tcl

        running = self._get(session_ref)
        reports_dir = running.record.session_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self.path_policy.require_output_name(output_name or f"{report_type}_{uuid.uuid4().hex[:8]}.rpt")
        output_path = reports_dir / safe_name
        raw_result = self._submit_tcl(running, report_tcl(report_type, output_path), timeout_seconds=timeout_seconds)
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["report_path"] = str(output_path)
        if output_path.exists():
            from .report_parser import parse_report

            report_text = output_path.read_text(encoding="utf-8", errors="replace")
            result["report_text"] = report_text[:8000]
            result["report_summary"] = parse_report(report_type, report_text)
        return result

    def analyze_reports(
        self,
        *,
        session_ref: str,
        report_types: list[str] | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, object]:
        from .report_context import unavailable_report_reasons
        from .report_parser import analyze_report_summaries, append_report_generation_issues, append_report_unavailable_issues

        selected = report_types or ["timing_summary", "clock_interaction", "utilization", "drc", "power", "methodology"]
        running = self._get(session_ref)
        report_context = self._report_context_for_running(running, timeout_seconds=timeout_seconds)
        context = report_context.get("report_context", {}) if isinstance(report_context.get("report_context"), dict) else {}
        unavailable = unavailable_report_reasons(context, selected)
        unavailable_by_type = {str(row.get("report_type") or ""): row for row in unavailable}
        reports: dict[str, dict[str, object]] = {}
        summaries: dict[str, dict[str, object]] = {}
        errors: list[dict[str, object]] = []
        for report_type in selected:
            if report_type in unavailable_by_type:
                reports[report_type] = {
                    "ok": False,
                    "skipped": True,
                    "reason": unavailable_by_type[report_type].get("reason"),
                    "next_step": unavailable_by_type[report_type].get("next_step"),
                    "suggested_tools": unavailable_by_type[report_type].get("suggested_tools"),
                }
                continue
            try:
                report = self.report(session_ref=session_ref, report_type=report_type, timeout_seconds=timeout_seconds)
            except Exception as exc:
                errors.append({"report_type": report_type, "error": str(exc)})
                continue
            reports[report_type] = {
                "ok": report.get("ok"),
                "report_path": report.get("report_path"),
                "report_artifact_uri": _path_artifact_uri(Path(str(report.get("report_path")))) if report.get("report_path") else None,
                "result_artifact_uri": report.get("result_artifact_uri"),
                "command_artifact_uri": report.get("command_artifact_uri"),
            }
            if report.get("ok") is False:
                errors.append(
                    {
                        "report_type": report_type,
                        "ok": False,
                        "error": report.get("error") or report.get("result") or "Vivado report command returned a non-zero result.",
                        "report_path": report.get("report_path"),
                        "report_artifact_uri": reports[report_type].get("report_artifact_uri"),
                        "result_artifact_uri": report.get("result_artifact_uri"),
                        "command_artifact_uri": report.get("command_artifact_uri"),
                    }
                )
            summary = report.get("report_summary")
            if isinstance(summary, dict):
                summaries[report_type] = summary
        analysis = analyze_report_summaries(summaries)
        if unavailable:
            analysis = append_report_unavailable_issues(analysis, unavailable)
        if errors:
            analysis = append_report_generation_issues(analysis, errors)
        analyses_dir = running.record.session_dir / "analyses"
        analyses_dir.mkdir(parents=True, exist_ok=True)
        output_path = analyses_dir / f"report_analysis_{uuid.uuid4().hex[:8]}.json"
        output_payload = {"reports": reports, "summaries": summaries, "analysis": analysis, "report_context": context}
        output_path.write_text(json.dumps(output_payload, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "ok": True,
            "session_ref": session_ref,
            "report_context": context,
            "report_context_artifact_uri": report_context.get("summary_artifact_uri"),
            "reports": reports,
            "summaries": summaries,
            "analysis": analysis,
            "analysis_path": str(output_path),
            "analysis_artifact_uri": artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix()),
        }

    def hardware_discover(
        self,
        *,
        session_ref: str,
        expect_hardware_access: bool = False,
        hw_server_url: str | None = None,
        target: str | None = None,
        open_target: bool = True,
        refresh: bool = False,
        timeout_seconds: int = 120,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .hardware_summary import parse_hardware_summary
        from .tcl import hardware_discover_tcl

        if not expect_hardware_access:
            raise PermissionError("Hardware discovery touches hw_server/target state; pass expect_hardware_access=true")
        running = self._get(session_ref)
        def operation() -> dict[str, object]:
            summaries_dir = running.record.session_dir / "summaries"
            summaries_dir.mkdir(parents=True, exist_ok=True)
            output_path = summaries_dir / f"hardware_{uuid.uuid4().hex[:8]}.tsv"
            raw_result = self._submit_tcl(
                running,
                hardware_discover_tcl(
                    output_path,
                    hw_server_url=hw_server_url,
                    target=target,
                    open_target=open_target,
                    refresh=refresh,
                ),
                timeout_seconds=timeout_seconds,
            )
            result = _result_to_dict(raw_result, expect_destructive=False)
            result["expect_hardware_access"] = expect_hardware_access
            result["summary_path"] = str(output_path)
            result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
            if output_path.exists():
                result["hardware"] = parse_hardware_summary(output_path)
            return result

        return self._capture_diff_around(
            running=running,
            label="hardware_discover",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=operation,
        )

    def nonproject_read_sources(
        self,
        *,
        session_ref: str,
        verilog: list[str] | None = None,
        systemverilog: list[str] | None = None,
        vhdl: list[str] | None = None,
        xdc: list[str] | None = None,
        include_dirs: list[str] | None = None,
        defines: list[str] | None = None,
        library: str | None = None,
        timeout_seconds: int = 120,
        dry_run: bool = False,
    ) -> dict[str, object]:
        from .nonproject_summary import parse_nonproject_summary
        from .tcl import nonproject_read_sources_tcl

        verilog_paths = [self.path_policy.require_under_roots(path, label="verilog", must_exist=True) for path in verilog or []]
        systemverilog_paths = [
            self.path_policy.require_under_roots(path, label="systemverilog", must_exist=True)
            for path in systemverilog or []
        ]
        vhdl_paths = [self.path_policy.require_under_roots(path, label="vhdl", must_exist=True) for path in vhdl or []]
        xdc_paths = [self.path_policy.require_under_roots(path, label="xdc", must_exist=True) for path in xdc or []]
        include_paths = [
            self.path_policy.require_under_roots(path, label="include_dir", must_exist=False) for path in include_dirs or []
        ]
        running = self._get(session_ref)
        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"nonproject_sources_{uuid.uuid4().hex[:8]}.tsv"
        script = nonproject_read_sources_tcl(
            output_path,
            verilog=verilog_paths,
            systemverilog=systemverilog_paths,
            vhdl=vhdl_paths,
            xdc=xdc_paths,
            include_dirs=include_paths,
            defines=defines,
            library=library,
        )
        if dry_run:
            return {
                "ok": True,
                "session_ref": session_ref,
                "dry_run": True,
                "expect_destructive": False,
                "summary_path": str(output_path),
                "summary_artifact_uri": artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix()),
                "plan": _nonproject_read_plan(
                    output_path=output_path,
                    verilog=verilog_paths,
                    systemverilog=systemverilog_paths,
                    vhdl=vhdl_paths,
                    xdc=xdc_paths,
                    include_dirs=include_paths,
                    defines=defines,
                    library=library,
                    tcl_preview=script,
                ),
            }
        raw_result = self._submit_tcl(
            running,
            script,
            timeout_seconds=timeout_seconds,
        )
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["nonproject"] = parse_nonproject_summary(output_path)
        return result

    def nonproject_audit(
        self,
        *,
        session_ref: str,
        expected_top: str | None = None,
        expected_part: str | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .nonproject_summary import analyze_nonproject_audit

        running = self._get(session_ref)
        summary, source_paths = self._nonproject_state_for_running(running)
        audit = analyze_nonproject_audit(summary, expected_top=expected_top, expected_part=expected_part)
        audit["session_ref"] = session_ref
        audit["summary_sources"] = [
            {
                "summary_path": str(path),
                "summary_artifact_uri": artifact_uri(session_ref, path.relative_to(running.record.session_dir).as_posix()),
            }
            for path in source_paths
        ]
        audit["timeout_seconds"] = timeout_seconds
        return audit

    def nonproject_run_step(
        self,
        *,
        session_ref: str,
        step: str,
        part: str | None = None,
        top: str | None = None,
        checkpoint_name: str | None = None,
        report_types: list[str] | None = None,
        extra_args: dict[str, object] | None = None,
        timeout_seconds: int = 3600,
        dry_run: bool = False,
    ) -> dict[str, object]:
        from .nonproject_summary import analyze_nonproject_audit, nonproject_step_prerequisites, parse_nonproject_summary
        from .report_parser import parse_report
        from .tcl import nonproject_run_step_tcl

        running = self._get(session_ref)
        summaries_dir = running.record.session_dir / "summaries"
        reports_dir = running.record.session_dir / "reports" / "nonproject"
        checkpoints_dir = running.record.session_dir / "checkpoints"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)
        checkpoints_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"nonproject_{_safe_label(step)}_{uuid.uuid4().hex[:8]}.tsv"
        checkpoint_path = None
        if checkpoint_name is not None:
            safe_checkpoint = self.path_policy.require_output_name(checkpoint_name, default_suffix=".dcp")
            checkpoint_path = checkpoints_dir / safe_checkpoint
        reports = {
            report_type: reports_dir / f"{_safe_label(step)}_{report_type}_{uuid.uuid4().hex[:8]}.rpt"
            for report_type in report_types or []
        }
        summary_state, _summary_paths = self._nonproject_state_for_running(running)
        prerequisites = nonproject_step_prerequisites(step, summary_state, part=part, top=top)
        tcl_error = None
        try:
            script = nonproject_run_step_tcl(
                output_path,
                step=step,
                part=part,
                top=top,
                checkpoint_path=checkpoint_path,
                reports=reports,
                extra_args=extra_args,
            )
        except ValueError as exc:
            if not dry_run:
                raise
            script = ""
            tcl_error = str(exc)
        plan = _nonproject_step_plan(
            output_path=output_path,
            step=step,
            part=part,
            top=top,
            checkpoint_path=checkpoint_path,
            reports=reports,
            extra_args=extra_args,
            tcl_preview=script,
        )
        if tcl_error is not None:
            plan["would_execute_tcl"] = False
            plan["tcl_error"] = tcl_error
        if dry_run:
            return {
                "ok": prerequisites["ok"] and tcl_error is None,
                "session_ref": session_ref,
                "dry_run": True,
                "expect_destructive": False,
                "summary_path": str(output_path),
                "summary_artifact_uri": artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix()),
                "prerequisites": prerequisites,
                "plan": plan,
            }
        raw_result = self._submit_tcl(
            running,
            script,
            timeout_seconds=timeout_seconds,
        )
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        result["prerequisites"] = prerequisites
        result["plan"] = plan
        if output_path.exists():
            result["nonproject"] = parse_nonproject_summary(output_path)
        report_summaries: dict[str, dict[str, object]] = {}
        report_artifacts: dict[str, dict[str, object]] = {}
        for report_type, report_path in reports.items():
            report_artifacts[report_type] = {
                "report_path": str(report_path),
                "report_artifact_uri": artifact_uri(session_ref, report_path.relative_to(running.record.session_dir).as_posix()),
            }
            if report_path.exists():
                report_summaries[report_type] = parse_report(
                    report_type,
                    report_path.read_text(encoding="utf-8", errors="replace"),
                )
        if report_artifacts:
            result["reports"] = report_artifacts
        if report_summaries:
            result["report_summaries"] = report_summaries
        if checkpoint_path is not None:
            result["checkpoint_path"] = str(checkpoint_path)
            result["checkpoint_artifact_uri"] = artifact_uri(
                session_ref,
                checkpoint_path.relative_to(running.record.session_dir).as_posix(),
            )
        merged_state, summary_paths = self._nonproject_state_for_running(running)
        result["nonproject_audit"] = analyze_nonproject_audit(merged_state)
        result["nonproject_summary_sources"] = [
            artifact_uri(session_ref, path.relative_to(running.record.session_dir).as_posix()) for path in summary_paths
        ]
        return result

    def ip_catalog_search(
        self,
        *,
        session_ref: str,
        query: str | None = None,
        vendor: str | None = None,
        library: str | None = None,
        name: str | None = None,
        taxonomy: str | None = None,
        limit: int = 25,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .ip_summary import parse_ip_catalog
        from .tcl import ip_catalog_search_tcl

        running = self._get(session_ref)
        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"ip_catalog_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(
            running,
            ip_catalog_search_tcl(
                output_path,
                query=query,
                vendor=vendor,
                library=library,
                name=name,
                taxonomy=taxonomy,
                limit=limit,
            ),
            timeout_seconds=timeout_seconds,
        )
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["catalog"] = parse_ip_catalog(output_path)
        return result

    def ip_create(
        self,
        *,
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
        from .tcl import ip_create_tcl

        resolved_vlnv = _resolve_ip_vlnv(
            vlnv=vlnv,
            vendor=vendor,
            library=library,
            ip_name=ip_name,
            version=version,
        )
        resolved_output_dir = self.path_policy.require_under_roots(output_dir, label="ip_output_dir", must_exist=False)
        running = self._get(session_ref)
        if dry_run:
            return {
                "ok": True,
                "session_ref": session_ref,
                "dry_run": True,
                "expect_destructive": True,
                "plan": _ip_create_plan(
                    vlnv=resolved_vlnv,
                    module_name=module_name,
                    output_dir=resolved_output_dir,
                    properties=properties,
                ),
            }
        return self._capture_diff_around(
            running=running,
            label=f"ip_create_{module_name}",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    ip_create_tcl(
                        vlnv=resolved_vlnv,
                        module_name=module_name,
                        output_dir=resolved_output_dir,
                        properties=properties,
                    ),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=True,
            ),
        )

    def ip_list(self, *, session_ref: str, timeout_seconds: int = 120) -> dict[str, object]:
        from .ip_summary import parse_ip_list
        from .tcl import ip_list_tcl

        running = self._get(session_ref)
        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"ips_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(running, ip_list_tcl(output_path), timeout_seconds=timeout_seconds)
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["ips"] = parse_ip_list(output_path)
        return result

    def ip_describe(self, *, session_ref: str, name: str, timeout_seconds: int = 120) -> dict[str, object]:
        from .ip_summary import parse_ip_detail
        from .tcl import ip_describe_tcl

        if not name.strip():
            raise ValueError("IP name must not be empty")
        running = self._get(session_ref)
        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"ip_desc_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(running, ip_describe_tcl(output_path, name=name), timeout_seconds=timeout_seconds)
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["ip"] = parse_ip_detail(output_path)
        return result

    def ip_upgrade_check(self, *, session_ref: str, timeout_seconds: int = 120) -> dict[str, object]:
        from .ip_summary import analyze_ip_upgrade

        listed = self.ip_list(session_ref=session_ref, timeout_seconds=timeout_seconds)
        summary = listed.get("ips") if isinstance(listed.get("ips"), dict) else {}
        analysis = analyze_ip_upgrade(summary)
        analysis["session_ref"] = session_ref
        analysis["summary_path"] = listed.get("summary_path", "")
        analysis["summary_artifact_uri"] = listed.get("summary_artifact_uri", "")
        return analysis

    def ip_upgrade(
        self,
        *,
        session_ref: str,
        name: str,
        expect_upgrade: bool = False,
        timeout_seconds: int = 300,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import ip_upgrade_tcl

        if not expect_upgrade:
            raise PermissionError("IP upgrade modifies .xci state; pass expect_upgrade=true to confirm")
        running = self._get(session_ref)
        return self._capture_diff_around(
            running=running,
            label=f"ip_upgrade_{name}",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(running, ip_upgrade_tcl(name=name), timeout_seconds=timeout_seconds),
                expect_destructive=True,
            ),
        )

    def ip_generate_outputs(
        self,
        *,
        session_ref: str,
        name: str,
        targets: list[str] | None = None,
        timeout_seconds: int = 600,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .tcl import ip_generate_outputs_tcl

        running = self._get(session_ref)
        return self._capture_diff_around(
            running=running,
            label=f"ip_generate_{name}",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(running, ip_generate_outputs_tcl(name=name, targets=targets), timeout_seconds=timeout_seconds),
                expect_destructive=True,
            ),
        )

    def prepare_simulation(
        self,
        *,
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
        dry_run: bool = False,
    ) -> dict[str, object]:
        from .tcl import simulation_prepare_tcl

        resolved_tb = [
            self.path_policy.require_under_roots(path, label="testbench_file", must_exist=True)
            for path in testbench_files or []
        ]
        include_paths = (
            None
            if include_dirs is None
            else [self.path_policy.require_under_roots(path, label="include_dir", must_exist=False) for path in include_dirs]
        )
        running = self._get(session_ref)
        if dry_run:
            return {
                "ok": True,
                "session_ref": session_ref,
                "dry_run": True,
                "expect_destructive": True,
                "plan": _simulation_prepare_plan(
                    fileset=fileset,
                    testbench_files=resolved_tb,
                    top=top,
                    include_dirs=include_paths,
                    defines=defines,
                    library=library,
                    create_if_missing=create_if_missing,
                ),
            }
        return self._capture_diff_around(
            running=running,
            label=f"prepare_simulation_{fileset}",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=lambda: _result_to_dict(
                self._submit_tcl(
                    running,
                    simulation_prepare_tcl(
                        fileset=fileset,
                        testbench_files=resolved_tb,
                        top=top,
                        include_dirs=include_paths,
                        defines=defines,
                        library=library,
                        create_if_missing=create_if_missing,
                    ),
                    timeout_seconds=timeout_seconds,
                ),
                expect_destructive=True,
            ),
        )

    def launch_simulation(
        self,
        *,
        session_ref: str,
        fileset: str = "sim_1",
        mode: str = "behavioral",
        sim_type: str | None = None,
        run_all: bool = True,
        scripts_only: bool = False,
        timeout_seconds: int = 1200,
        capture_diff: bool = False,
    ) -> dict[str, object]:
        from .simulation_summary import parse_simulation_launch
        from .tcl import simulation_launch_tcl

        running = self._get(session_ref)
        def operation() -> dict[str, object]:
            summaries_dir = running.record.session_dir / "summaries"
            summaries_dir.mkdir(parents=True, exist_ok=True)
            output_path = summaries_dir / f"simulation_launch_{uuid.uuid4().hex[:8]}.tsv"
            raw_result = self._submit_tcl(
                running,
                simulation_launch_tcl(
                    output_path,
                    fileset=fileset,
                    mode=mode,
                    sim_type=sim_type,
                    run_all=run_all,
                    scripts_only=scripts_only,
                ),
                timeout_seconds=timeout_seconds,
            )
            result = _result_to_dict(raw_result, expect_destructive=False)
            result["summary_path"] = str(output_path)
            result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
            if output_path.exists():
                result["simulation"] = parse_simulation_launch(output_path)
            if isinstance(result.get("simulation"), dict):
                log_paths = [
                    str(row.get("path"))
                    for row in result["simulation"].get("log_paths", [])
                    if isinstance(row, dict) and row.get("path")
                ]
                if log_paths:
                    try:
                        result["log_analysis"] = self.analyze_xsim_logs(
                            session_ref=session_ref,
                            log_paths=log_paths,
                            timeout_seconds=timeout_seconds,
                        ).get("analysis")
                    except Exception as exc:
                        result["log_analysis_error"] = str(exc)
            return result

        return self._capture_diff_around(
            running=running,
            label=f"launch_simulation_{fileset}",
            capture_diff=capture_diff,
            timeout_seconds=timeout_seconds,
            operation=operation,
        )

    def simulation_audit(
        self,
        *,
        session_ref: str,
        fileset: str = "sim_1",
        top: str | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .fileset_summary import parse_describe_fileset
        from .simulation_summary import analyze_simulation_audit
        from .tcl import describe_fileset_tcl

        running = self._get(session_ref)
        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        sim_path = summaries_dir / f"sim_fileset_{uuid.uuid4().hex[:8]}.tsv"
        self._submit_tcl(running, describe_fileset_tcl(sim_path, name=fileset), timeout_seconds=timeout_seconds)
        filesets: dict[str, object] = {"filesets": []}
        if sim_path.exists():
            filesets["filesets"] = [parse_describe_fileset(sim_path)]
        ip_summary = self._ip_list_for_running(running, timeout_seconds=timeout_seconds)
        ip_state = ip_summary.get("ips") if isinstance(ip_summary.get("ips"), dict) else {}
        audit = analyze_simulation_audit(filesets=filesets, ip=ip_state, fileset=fileset, top=top)
        audit["session_ref"] = session_ref
        audit["fileset_summary_path"] = str(sim_path)
        audit["fileset_summary_artifact_uri"] = artifact_uri(session_ref, sim_path.relative_to(running.record.session_dir).as_posix())
        if ip_summary.get("summary_path"):
            audit["ip_summary_path"] = ip_summary["summary_path"]
            audit["ip_summary_artifact_uri"] = ip_summary.get("summary_artifact_uri", "")
        return audit

    def analyze_xsim_logs(
        self,
        *,
        session_ref: str,
        log_paths: list[str] | None = None,
        launch_summary_artifact: str | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .simulation_summary import analyze_xsim_logs, parse_simulation_launch

        running = self._get(session_ref)
        paths: list[Path] = []
        if launch_summary_artifact:
            relative = _artifact_relative(session_ref, launch_summary_artifact)
            summary_path = (running.record.session_dir / relative).resolve()
            session_root = running.record.session_dir.resolve()
            if session_root not in [summary_path, *summary_path.parents]:
                raise PermissionError("Simulation launch summary path escapes session directory")
            launch = parse_simulation_launch(summary_path)
            for row in launch.get("log_paths", []) if isinstance(launch.get("log_paths"), list) else []:
                if isinstance(row, dict) and row.get("path"):
                    paths.append(self.path_policy.require_under_roots(str(row["path"]), label="xsim_log", must_exist=True))
        for path in log_paths or []:
            paths.append(self.path_policy.require_under_roots(path, label="xsim_log", must_exist=True))
        if not paths:
            raise ValueError("log_paths or launch_summary_artifact must identify at least one log")

        analyses_dir = running.record.session_dir / "analyses"
        analyses_dir.mkdir(parents=True, exist_ok=True)
        analysis = analyze_xsim_logs(paths)
        output_path = analyses_dir / f"xsim_log_analysis_{uuid.uuid4().hex[:8]}.json"
        output_path.write_text(json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "ok": True,
            "session_ref": session_ref,
            "analysis": analysis,
            "analysis_path": str(output_path),
            "analysis_artifact_uri": artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix()),
            "timeout_seconds": timeout_seconds,
        }

    def project_summary(self, *, session_ref: str, timeout_seconds: int = 60) -> dict[str, object]:
        from .project_summary import parse_project_summary
        from .tcl import project_summary_tcl

        running = self._get(session_ref)
        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"project_summary_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(running, project_summary_tcl(output_path), timeout_seconds=timeout_seconds)
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["project_summary"] = parse_project_summary(output_path)
        return result

    def _collect_state(
        self,
        *,
        running: "_RunningSession",
        include_bd: bool,
        validate_bd: bool,
        timeout_seconds: int,
    ) -> dict[str, object]:
        state: dict[str, object] = {
            "session_ref": running.record.session_ref,
            "workspace_dir": str(running.record.workspace_dir),
            "current_project_path": str(running.record.current_project_path) if running.record.current_project_path else None,
            "project": {},
            "filesets": {},
            "constraints": {},
            "block_design": {},
            "errors": [],
        }

        errors = state["errors"]
        assert isinstance(errors, list)
        try:
            project = self._project_summary_for_running(running, timeout_seconds=timeout_seconds)
            state["project"] = project.get("project_summary", {})
        except Exception as exc:
            errors.append({"section": "project", "error": str(exc)})
        try:
            ip_state = self._ip_list_for_running(running, timeout_seconds=timeout_seconds)
            state["ip"] = ip_state.get("ips", {})
        except Exception as exc:
            errors.append({"section": "ip", "error": str(exc)})
        try:
            filesets = self._list_filesets_for_running(running, timeout_seconds=timeout_seconds)
            state["filesets"] = filesets.get("filesets", {})
        except Exception as exc:
            errors.append({"section": "filesets", "error": str(exc)})
        try:
            constraints = self._constraint_diagnostics_for_running(running, timeout_seconds=timeout_seconds)
            state["constraints"] = constraints.get("diagnostics", {})
        except Exception as exc:
            errors.append({"section": "constraints", "error": str(exc)})
        if include_bd:
            try:
                bd = self._bd_summary_for_running(running, validate=validate_bd, timeout_seconds=timeout_seconds)
                state["block_design"] = bd.get("bd_summary", {})
            except Exception as exc:
                errors.append({"section": "block_design", "error": str(exc)})
        try:
            state["reports"] = self._artifact_index_for_running(running)
        except Exception as exc:
            errors.append({"section": "reports", "error": str(exc)})
        if errors:
            state["errors"] = errors
        return state

    def _read_state_artifact(self, running: "_RunningSession", artifact_id: str | None, *, label: str) -> dict[str, object]:
        if not artifact_id:
            raise ValueError(f"{label} is required when state payload is not provided")
        relative = _artifact_relative(running.record.session_ref, artifact_id)
        path = (running.record.session_dir / relative).resolve()
        session_root = running.record.session_dir.resolve()
        if session_root not in [path, *path.parents]:
            raise PermissionError("State artifact path escapes session directory")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"State artifact not found: {relative}")
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            raise ValueError(f"State artifact is not a JSON object: {relative}")
        return data

    def _read_json_artifact_by_uri(self, running: "_RunningSession", artifact: object) -> dict[str, object] | None:
        if not isinstance(artifact, dict):
            return None
        artifact_uri_value = artifact.get("artifact_uri")
        if not isinstance(artifact_uri_value, str) or not artifact_uri_value:
            return None
        try:
            relative = _artifact_relative(running.record.session_ref, artifact_uri_value)
            path = (running.record.session_dir / relative).resolve()
            session_root = running.record.session_dir.resolve()
            if session_root not in [path, *path.parents] or not path.is_file():
                return None
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _capture_diff_around(
        self,
        *,
        running: "_RunningSession",
        label: str,
        capture_diff: bool,
        timeout_seconds: int,
        operation: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        before = None
        snapshot_timeout = _snapshot_timeout(timeout_seconds)
        if capture_diff:
            before = self.capture_state(
                session_ref=running.record.session_ref,
                label=f"{label}_before",
                timeout_seconds=snapshot_timeout,
            )
        result = operation()
        if capture_diff:
            after = self.capture_state(
                session_ref=running.record.session_ref,
                label=f"{label}_after",
                timeout_seconds=snapshot_timeout,
            )
            result["state_before"] = _snapshot_ref(before)
            result["state_after"] = _snapshot_ref(after)
            result["state_diff"] = self.state_diff(
                session_ref=running.record.session_ref,
                before_state=before["state"],
                after_state=after["state"],
            )
        return result

    def _project_summary_for_running(self, running: "_RunningSession", *, timeout_seconds: int) -> dict[str, object]:
        from .project_summary import parse_project_summary
        from .tcl import project_summary_tcl

        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"project_summary_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(running, project_summary_tcl(output_path), timeout_seconds=timeout_seconds)
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(running.record.session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["project_summary"] = parse_project_summary(output_path)
        return result

    def _list_filesets_for_running(self, running: "_RunningSession", *, timeout_seconds: int) -> dict[str, object]:
        from .fileset_summary import parse_list_filesets
        from .tcl import list_filesets_tcl

        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"filesets_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(running, list_filesets_tcl(output_path), timeout_seconds=timeout_seconds)
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(running.record.session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["filesets"] = parse_list_filesets(output_path)
        return result

    def _ip_list_for_running(self, running: "_RunningSession", *, timeout_seconds: int) -> dict[str, object]:
        from .ip_summary import parse_ip_list
        from .tcl import ip_list_tcl

        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"ips_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(running, ip_list_tcl(output_path), timeout_seconds=timeout_seconds)
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(
            running.record.session_ref,
            output_path.relative_to(running.record.session_dir).as_posix(),
        )
        if output_path.exists():
            result["ips"] = parse_ip_list(output_path)
        return result

    def _nonproject_state_for_running(self, running: "_RunningSession") -> tuple[dict[str, object], list[Path]]:
        from .nonproject_summary import merge_nonproject_summaries, parse_nonproject_summary

        summaries_dir = running.record.session_dir / "summaries"
        if not summaries_dir.exists():
            return merge_nonproject_summaries([]), []
        paths = sorted((path for path in summaries_dir.glob("nonproject*.tsv") if path.is_file()), key=lambda path: path.stat().st_mtime)
        summaries = [parse_nonproject_summary(path) for path in paths]
        return merge_nonproject_summaries(summaries), paths

    def _artifact_index_for_running(self, running: "_RunningSession", *, include_all: bool = False) -> dict[str, object]:
        artifacts = []
        for path in sorted(running.record.session_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(running.record.session_dir).as_posix()
            if not include_all and relative.startswith(("inbox/", "running/")):
                continue
            kind = _artifact_kind(path)
            if not include_all and kind not in {"report", "analysis", "simulation_log", "checkpoint"}:
                continue
            stat = path.stat()
            row: dict[str, object] = {
                "artifact_id": relative,
                "relative_path": relative,
                "kind": kind,
                "path": str(path),
                "artifact_uri": artifact_uri(running.record.session_ref, relative),
                "size_bytes": stat.st_size,
                "size": stat.st_size,
                "created_at": _mtime_iso(stat.st_mtime),
                "modified_at": _mtime_iso(stat.st_mtime),
                "tool_hint": _artifact_tool_hint(path, kind),
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

    def _describe_fileset_for_running(self, running: "_RunningSession", *, name: str, timeout_seconds: int) -> dict[str, object]:
        from .fileset_summary import parse_describe_fileset
        from .tcl import describe_fileset_tcl

        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"fileset_desc_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(
            running,
            describe_fileset_tcl(output_path, name=name),
            timeout_seconds=timeout_seconds,
        )
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(running.record.session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["fileset_summary"] = parse_describe_fileset(output_path)
        return result

    def _constraint_diagnostics_for_running(self, running: "_RunningSession", *, timeout_seconds: int) -> dict[str, object]:
        from .fileset_summary import parse_constraint_diagnostics
        from .tcl import constraint_diagnostics_tcl

        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"constraint_diag_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(running, constraint_diagnostics_tcl(output_path), timeout_seconds=timeout_seconds)
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(running.record.session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["diagnostics"] = parse_constraint_diagnostics(output_path)
        return result

    def _bd_summary_for_running(self, running: "_RunningSession", *, validate: bool, timeout_seconds: int) -> dict[str, object]:
        from .bd_summary import parse_bd_summary
        from .tcl import bd_summary_tcl

        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"bd_summary_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(
            running,
            bd_summary_tcl(output_path, validate=validate),
            timeout_seconds=timeout_seconds,
        )
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(running.record.session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["bd_summary"] = parse_bd_summary(output_path)
        return result

    def _report_context_for_running(self, running: "_RunningSession", *, timeout_seconds: int) -> dict[str, object]:
        from .report_context import parse_report_context
        from .tcl import report_context_tcl

        summaries_dir = running.record.session_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        output_path = summaries_dir / f"report_context_{uuid.uuid4().hex[:8]}.tsv"
        raw_result = self._submit_tcl(running, report_context_tcl(output_path), timeout_seconds=timeout_seconds)
        result = _result_to_dict(raw_result, expect_destructive=False)
        result["summary_path"] = str(output_path)
        result["summary_artifact_uri"] = artifact_uri(running.record.session_ref, output_path.relative_to(running.record.session_dir).as_posix())
        if output_path.exists():
            result["report_context"] = parse_report_context(output_path)
        return result

    def _submit_tcl(self, running: "_RunningSession", tcl: str, *, timeout_seconds: int) -> TclCommandResult:
        if running.process.poll() is not None:
            raise VivadoSessionError(f"Vivado session is stopped with code {running.process.returncode}")
        command_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        command_path = running.record.session_dir / "inbox" / f"{command_id}.tcl"
        result_path = running.record.session_dir / "done" / f"{command_id}.result.txt"
        running_path = running.record.session_dir / "running" / f"{command_id}.tcl"
        command_path.parent.mkdir(parents=True, exist_ok=True)
        command_path.write_text(tcl, encoding="utf-8")

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if result_path.exists():
                final_command_path = running_path if running_path.exists() else command_path
                return _parse_result(command_id, result_path, final_command_path)
            if running.process.poll() is not None:
                raise VivadoSessionError(f"Vivado exited before command result was written; exit code {running.process.returncode}")
            time.sleep(0.1)
        raise TimeoutError(f"Timed out waiting for Tcl command {command_id}")

    def _wait_for_idle(self, running: "_RunningSession", timeout_seconds: int) -> None:
        deadline = time.time() + timeout_seconds
        status_path = running.record.session_dir / "status.txt"
        while time.time() < deadline:
            if running.process.poll() is not None:
                raise VivadoSessionError(f"Vivado exited during startup with code {running.process.returncode}")
            status = _read_status(status_path)
            if status.get("state") == "idle":
                return
            time.sleep(0.1)
        raise TimeoutError("Timed out waiting for Vivado bridge to become idle")

    def _wait_for_gui(self, running: "_RunningSession", *, timeout_seconds: int, activate: bool) -> dict[str, object]:
        if not running.record.open_gui:
            return _gui_not_requested()
        state = wait_for_vivado_gui(
            root_pid=running.process.pid,
            extra_pids=_vivado_process_ids_from_log(running.record.log_path),
            title_hints=_gui_title_hints(running.record),
            timeout_seconds=timeout_seconds,
            activate=activate,
        )
        state["bridge_gui"] = _read_status(running.record.session_dir / "gui_status.txt")
        return state

    def _gui_state(self, running: "_RunningSession", *, activate: bool) -> dict[str, object]:
        if not running.record.open_gui:
            return _gui_not_requested()
        state = probe_vivado_gui(
            root_pid=running.process.pid,
            extra_pids=_vivado_process_ids_from_log(running.record.log_path),
            title_hints=_gui_title_hints(running.record),
            activate=activate,
        )
        state["bridge_gui"] = _read_status(running.record.session_dir / "gui_status.txt")
        return state

    def _get(self, session_ref: str) -> "_RunningSession":
        with self._lock:
            running = self._sessions.get(session_ref)
        if running is None:
            raise KeyError(f"Unknown session_ref {session_ref!r}")
        return running


class _RunningSession:
    def __init__(
        self,
        *,
        record: SessionRecord,
        process: subprocess.Popen[str],
        log_file,
        output_thread: threading.Thread,
    ) -> None:
        self.record = record
        self.process = process
        self.log_file = log_file
        self.output_thread = output_thread


def _pipe_output(process: subprocess.Popen[str], log_file) -> None:
    try:
        assert process.stdout is not None
        for line in process.stdout:
            log_file.write(line)
            log_file.flush()
    finally:
        try:
            log_file.flush()
        except ValueError:
            pass


def _read_status(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"state": "starting"}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    return data


def _gui_not_requested() -> dict[str, object]:
    return {
        "requested": False,
        "platform": os.sys.platform,
        "platform_supported": os.sys.platform == "win32",
        "visible": False,
        "activated": False,
        "windows": [],
        "detail": "Session was started with open_gui=false.",
    }


def _gui_title_hints(record: SessionRecord) -> list[str]:
    if record.current_project_path is None:
        return []
    project_path = record.current_project_path
    return [
        project_path.name,
        project_path.stem,
        project_path.as_posix(),
        str(project_path).replace("\\", "/"),
    ]


def _vivado_process_ids_from_log(path: Path) -> set[int]:
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {int(match) for match in re.findall(r"Process ID:\s*(\d+)", text)}


def _managed_gui_pids(gui_state: dict[str, object]) -> set[int]:
    watched_pids = {int(pid) for pid in gui_state.get("watched_pids", [])}
    pids: set[int] = set()
    for window in gui_state.get("windows", []):
        if not isinstance(window, dict):
            continue
        try:
            pid = int(window["pid"])
        except (KeyError, TypeError, ValueError):
            continue
        if pid in watched_pids:
            pids.add(pid)
    return pids


def _terminate_processes(pids: set[int], timeout_seconds: int = 5) -> dict[str, object]:
    terminated: list[int] = []
    exited: list[int] = []
    skipped: list[int] = []
    errors: list[dict[str, object]] = []
    current_pid = os.getpid()
    candidate_pids = sorted(pid for pid in pids if pid > 0 and pid != current_pid)

    skipped.extend(sorted(pid for pid in pids if pid <= 0 or pid == current_pid))

    deadline = time.time() + timeout_seconds
    while candidate_pids and time.time() < deadline:
        remaining = [pid for pid in candidate_pids if _process_exists(pid)]
        if not remaining:
            break
        candidate_pids = remaining
        time.sleep(0.1)

    for pid in candidate_pids:
        if not _process_exists(pid):
            exited.append(pid)
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            terminated.append(pid)
        except ProcessLookupError:
            exited.append(pid)
        except PermissionError as exc:
            time.sleep(0.5)
            if _process_exists(pid):
                errors.append({"pid": pid, "error": str(exc)})
            else:
                exited.append(pid)
        except OSError as exc:
            time.sleep(0.5)
            if _process_exists(pid):
                errors.append({"pid": pid, "error": str(exc)})
            else:
                exited.append(pid)

    if terminated:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if all(not _process_exists(pid) for pid in terminated):
                break
            time.sleep(0.1)

    return {
        "terminated_pids": terminated,
        "exited_pids": sorted(set(exited)),
        "skipped_pids": skipped,
        "errors": errors,
    }


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _mtime_iso(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _safe_label(label: str | None) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", (label or "snapshot").strip())
    return value.strip("._") or "snapshot"


def _snapshot_timeout(operation_timeout_seconds: int) -> int:
    return min(max(int(operation_timeout_seconds), 30), 120)


def _fileset_category(row: dict[str, object]) -> str:
    category = str(row.get("category") or "")
    if category:
        return category
    fileset_type = str(row.get("type") or "").lower()
    if fileset_type in {"source", "designsrcs", "design_sources"}:
        return "source"
    if fileset_type in {"simulation", "simulationsrcs", "simulation_sources"}:
        return "simulation"
    if fileset_type in {"constrs", "constraint", "constraints"}:
        return "constraint"
    if fileset_type in {"blocksrcs", "block_source", "block_sources"}:
        return "block_source"
    if fileset_type == "utils":
        return "utility"
    return "other"


def _artifact_relative(session_ref: str, artifact_id_or_uri: str) -> str:
    marker = f"vivado://sessions/{session_ref}/artifacts/"
    if artifact_id_or_uri.startswith(marker):
        artifact_id_or_uri = artifact_id_or_uri[len(marker) :]
    return unquote(artifact_id_or_uri)


def _snapshot_ref(snapshot: dict[str, object] | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "snapshot_id": snapshot.get("snapshot_id"),
        "label": snapshot.get("label"),
        "digest": snapshot.get("digest"),
        "snapshot_artifact_uri": snapshot.get("snapshot_artifact_uri"),
        "snapshot_path": snapshot.get("snapshot_path"),
    }


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    parts = set(path.parts)
    if "running" in parts or "inbox" in parts:
        return "command"
    if "done" in parts and path.name.endswith(".result.txt"):
        return "result"
    if suffix == ".rpt" or "reports" in parts:
        return "report"
    if "snapshots" in parts and suffix == ".json":
        return "snapshot"
    if "summaries" in parts and suffix == ".tsv":
        return "summary"
    if "analyses" in parts or path.name.startswith(("report_analysis_", "xsim_log_analysis_")):
        return "analysis"
    if suffix == ".log" and any(name in path.name.lower() for name in ("xsim", "xelab", "xvlog", "xvhdl")):
        return "simulation_log"
    if suffix == ".log":
        return "log"
    if suffix == ".dcp" or "checkpoints" in parts:
        return "checkpoint"
    return "other"


def _report_type_from_artifact(path: Path) -> str:
    if path.suffix.lower() != ".rpt":
        return ""
    name = path.stem.lower()
    for report_type in (
        "timing_summary",
        "timing_paths",
        "utilization",
        "drc",
        "power",
        "methodology",
        "messages",
        "clock_interaction",
    ):
        if report_type in name:
            return report_type
    if "timing" in name:
        return "timing"
    return ""


def _analysis_type_from_artifact(path: Path) -> str:
    name = path.name.lower()
    if name.startswith("report_analysis_"):
        return "report_analysis"
    if name.startswith("xsim_log_analysis_"):
        return "xsim_log_analysis"
    if "analysis" in name and "report" in name:
        return "report_analysis"
    return ""


def _summary_type_from_artifact(path: Path) -> str:
    if path.suffix.lower() != ".tsv":
        return ""
    name = path.stem.lower()
    if name.startswith("nonproject"):
        return "nonproject"
    if name.startswith("bd_"):
        return "block_design"
    if name.startswith("ips"):
        return "ip"
    if name.startswith("fileset"):
        return "fileset"
    if name.startswith("constraint"):
        return "constraint"
    if name.startswith("report_context"):
        return "report_context"
    if name.startswith("simulation") or name.startswith("xsim"):
        return "simulation"
    if name.startswith("project"):
        return "project"
    return "summary"


def _artifact_tool_hint(path: Path, kind: str) -> str:
    name = path.name.lower()
    if kind == "command":
        return "vivado_run_tcl"
    if kind == "result":
        return "vivado_run_tcl"
    if kind == "report":
        return "vivado_report"
    if kind == "checkpoint":
        return "vivado_nonproject_*_design"
    if kind == "snapshot":
        return "vivado_capture_state"
    if kind == "analysis":
        if name.startswith("xsim_log_analysis_"):
            return "vivado_analyze_xsim_logs"
        return "vivado_analyze_reports"
    if kind == "summary":
        summary_type = _summary_type_from_artifact(path)
        hints = {
            "nonproject": "vivado_nonproject_audit",
            "block_design": "vivado_bd_summary",
            "ip": "vivado_list_ips",
            "fileset": "vivado_describe_fileset",
            "constraint": "vivado_constraint_diagnostics",
            "report_context": "vivado_analyze_reports",
            "simulation": "vivado_simulation_audit",
            "project": "vivado_project_summary",
        }
        return hints.get(summary_type, "vivado_project_summary")
    if kind == "simulation_log":
        return "vivado_analyze_xsim_logs"
    return ""


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


def _recovery_next_action_plan(
    *,
    report_analysis_payload: dict[str, object] | None,
    xsim_analysis_payload: dict[str, object] | None,
    latest: dict[str, object],
) -> list[dict[str, object]]:
    report_plan = _nested_list(report_analysis_payload, ["analysis", "next_action_plan"])
    if report_plan:
        return report_plan[:5]
    xsim_plan = _nested_list(xsim_analysis_payload, ["analysis", "next_action_plan"])
    if xsim_plan:
        return xsim_plan[:5]
    if latest.get("report_analysis"):
        return [{"tool": "vivado_analyze_reports", "why": "Refresh report diagnostics and inspect quality gates."}]
    if latest.get("simulation_log"):
        return [{"tool": "vivado_analyze_xsim_logs", "why": "Analyze the latest simulation logs."}]
    if latest.get("state_snapshot"):
        return [{"tool": "vivado_state_diff", "why": "Compare the latest snapshot with a prior known-good state."}]
    return [{"tool": "vivado_project_summary", "why": "No analysis artifact was found; inspect current project state first."}]


def _recovery_quality_gates(report_analysis_payload: dict[str, object] | None) -> dict[str, object]:
    gates = _nested_dict(report_analysis_payload, ["analysis", "quality_gates"])
    return gates if gates is not None else {}


def _recovery_recommendations(latest: dict[str, object], next_action_plan: list[dict[str, object]]) -> list[dict[str, str]]:
    recommendations = [
        {"tool": "vivado_session_timeline", "why": "Review the chronological command/report/analysis/checkpoint history before resuming."},
    ]
    if latest.get("report_analysis"):
        recommendations.append({"tool": "vivado_read_artifact", "why": "Read the latest report analysis JSON if more detail is needed."})
    if next_action_plan:
        first = next_action_plan[0]
        recommendations.append(
            {
                "tool": str(first.get("tool") or "vivado_project_summary"),
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
        "id": snapshot.get("id"),
        "label": snapshot.get("label"),
        "digest": snapshot.get("digest"),
        "created_at": snapshot.get("created_at"),
        "project": project,
    }


def _nested_list(payload: dict[str, object] | None, path: list[str]) -> list[dict[str, object]]:
    value: object = payload
    for key in path:
        if not isinstance(value, dict):
            return []
        value = value.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _nested_dict(payload: dict[str, object] | None, path: list[str]) -> dict[str, object] | None:
    value: object = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, dict) else None


def _bd_apply_plan(
    *,
    actions: list[dict[str, object]],
    design_name: str | None,
    bd_path: Path | None,
    validate: bool,
    save: bool,
) -> dict[str, object]:
    from .tcl import bd_apply_tcl

    planned_actions: list[dict[str, object]] = []
    for index, action in enumerate(actions, start=1):
        planned_actions.append(
            {
                "index": index,
                "action": str(action.get("action") or action.get("type") or ""),
                "input": action,
                "risk_level": _bd_action_risk(action),
            }
        )
    if validate:
        planned_actions.append({"action": "validate_bd_design", "risk_level": "low"})
    if save:
        planned_actions.append({"action": "save_bd_design", "risk_level": "medium"})
    return {
        "operation": "bd_apply",
        "design_name": design_name,
        "bd_path": str(bd_path) if bd_path else "",
        "actions": planned_actions,
        "risk_level": "medium" if save else "low",
        "would_execute_tcl": bool(planned_actions),
        "tcl_preview": bd_apply_tcl(actions=actions, design_name=design_name, bd_path=bd_path, validate=validate, save=save),
        "recommended_docs": [
            {"doc_id": "UG994", "title": "Vivado Design Suite User Guide: Designing IP Subsystems Using IP Integrator"},
            {"doc_id": "UG835", "title": "Vivado Design Suite Tcl Command Reference Guide"},
            {"doc_id": "UG912", "title": "Vivado Design Suite Properties Reference Guide"},
        ],
        "recommendations": [
            {"tool": "vivado_bd_audit", "why": "Audit current BD validation, connectivity, and address state before applying actions."},
            {"tool": "vivado_bd_summary", "why": "Refresh BD cells, ports, nets, interfaces, and validation after applying actions."},
            {"tool": "vivado_bd_validate", "why": "Parse validation diagnostics before generating wrappers or output products."},
        ],
    }


def _bd_action_risk(action: dict[str, object]) -> str:
    action_type = str(action.get("action") or action.get("type") or "")
    if action_type in {"assign_address", "apply_automation", "set_property"}:
        return "medium"
    if action_type in {"validate", "save"}:
        return "low"
    return "medium"


def _fileset_apply_plan(
    *,
    fileset: str,
    include_dirs: list[Path] | None,
    defines: list[str] | None,
    top: str | None,
    properties: dict[str, object] | None,
    update_compile_order: bool,
) -> dict[str, object]:
    actions: list[dict[str, object]] = []
    if include_dirs is not None:
        actions.append({"action": "set_include_dirs", "fileset": fileset, "paths": [str(path) for path in include_dirs]})
    if defines:
        actions.append({"action": "set_defines", "fileset": fileset, "defines": defines})
    if top:
        actions.append({"action": "set_top", "fileset": fileset, "top": top})
    if properties:
        actions.append({"action": "set_properties", "fileset": fileset, "properties": properties})
    if update_compile_order:
        actions.append({"action": "update_compile_order", "fileset": fileset})
    return {
        "operation": "fileset_apply",
        "fileset": fileset,
        "actions": actions,
        "risk_level": "medium" if actions else "low",
        "would_execute_tcl": bool(actions),
        "recommendations": [
            {"tool": "vivado_describe_fileset", "why": "Inspect fileset state before applying the planned changes."},
            {"tool": "vivado_source_audit", "why": "Run source audit after applying fileset changes."},
        ],
    }


def _constraint_set_apply_plan(
    *,
    fileset: str,
    create_if_missing: bool,
    add: list[Path],
    remove: list[Path],
    used_in: list[str] | None,
    reorder: list[Path],
    active: bool | None,
) -> dict[str, object]:
    actions: list[dict[str, object]] = []
    if create_if_missing:
        actions.append({"action": "create_fileset", "fileset": fileset, "kind": "constrs"})
    if add:
        actions.append({"action": "add_xdc", "fileset": fileset, "paths": [str(path) for path in add]})
    if remove:
        actions.append({"action": "remove_xdc", "fileset": fileset, "paths": [str(path) for path in remove]})
    if used_in is not None:
        actions.append({"action": "set_used_in", "fileset": fileset, "used_in": used_in})
    if reorder:
        actions.append({"action": "reorder_xdc", "fileset": fileset, "paths": [str(path) for path in reorder]})
    if active is not None:
        actions.append({"action": "set_active_constraint_set", "fileset": fileset, "active": active})
    return {
        "operation": "constraint_set_apply",
        "fileset": fileset,
        "actions": actions,
        "risk_level": "high" if remove else "medium" if actions else "low",
        "would_execute_tcl": bool(actions),
        "recommendations": [
            {"tool": "vivado_xdc_order_check", "why": "Check XDC order before and after applying constraint changes."},
            {"tool": "vivado_source_audit", "why": "Audit source and constraint placement after applying changes."},
        ],
    }


def _ip_create_plan(
    *,
    vlnv: str,
    module_name: str,
    output_dir: Path,
    properties: dict[str, object] | None,
) -> dict[str, object]:
    from .tcl import ip_create_tcl

    actions: list[dict[str, object]] = [
        {
            "action": "create_ip",
            "vlnv": vlnv,
            "module_name": module_name,
            "output_dir": str(output_dir),
        }
    ]
    if properties:
        actions.append({"action": "set_ip_properties", "module_name": module_name, "properties": properties})
    actions.append({"action": "inspect_ip", "tool": "vivado_describe_ip", "name": module_name})
    return {
        "operation": "ip_create",
        "module_name": module_name,
        "vlnv": vlnv,
        "output_dir": str(output_dir),
        "actions": actions,
        "risk_level": "medium",
        "would_execute_tcl": True,
        "tcl_preview": ip_create_tcl(
            vlnv=vlnv,
            module_name=module_name,
            output_dir=output_dir,
            properties=properties,
        ),
        "recommended_docs": [
            {"doc_id": "UG896", "title": "Vivado Design Suite User Guide: Designing with IP"},
            {"doc_id": "UG835", "title": "Vivado Design Suite Tcl Command Reference Guide"},
            {"doc_id": "IP Product Guide", "title": "Search by IP name or VLNV before setting CONFIG properties."},
        ],
        "recommendations": [
            {"tool": "vivado_ip_catalog_search", "why": "Confirm the exact VLNV before creating the IP."},
            {"tool": "vivado_describe_ip", "why": "Inspect generated IP properties and .xci state after creation."},
            {"tool": "vivado_generate_ip_outputs", "why": "Generate output products after the IP is created."},
        ],
    }


def _simulation_prepare_plan(
    *,
    fileset: str,
    testbench_files: list[Path],
    top: str | None,
    include_dirs: list[Path] | None,
    defines: list[str] | None,
    library: str | None,
    create_if_missing: bool,
) -> dict[str, object]:
    from .tcl import simulation_prepare_tcl

    actions: list[dict[str, object]] = []
    if create_if_missing:
        actions.append({"action": "create_fileset_if_missing", "fileset": fileset, "kind": "simulation"})
    if testbench_files:
        actions.append({"action": "add_testbench_files", "fileset": fileset, "paths": [str(path) for path in testbench_files]})
    if include_dirs is not None:
        actions.append({"action": "set_include_dirs", "fileset": fileset, "paths": [str(path) for path in include_dirs]})
    if defines:
        actions.append({"action": "set_defines", "fileset": fileset, "defines": defines})
    if library:
        actions.append({"action": "set_testbench_library", "fileset": fileset, "library": library})
    if top:
        actions.append({"action": "set_top", "fileset": fileset, "top": top})
    actions.append({"action": "update_compile_order", "fileset": fileset})
    return {
        "operation": "prepare_simulation",
        "fileset": fileset,
        "actions": actions,
        "risk_level": "medium" if actions else "low",
        "would_execute_tcl": bool(actions),
        "tcl_preview": simulation_prepare_tcl(
            fileset=fileset,
            testbench_files=testbench_files,
            top=top,
            include_dirs=include_dirs,
            defines=defines,
            library=library,
            create_if_missing=create_if_missing,
        ),
        "recommended_docs": [
            {"doc_id": "UG900", "title": "Vivado Design Suite User Guide: Logic Simulation"},
            {"doc_id": "UG835", "title": "Vivado Design Suite Tcl Command Reference Guide"},
            {"doc_id": "UG896", "title": "Vivado Design Suite User Guide: Designing with IP"},
        ],
        "recommendations": [
            {"tool": "vivado_simulation_audit", "why": "Audit simulation fileset, testbench, and IP output-product state before launch."},
            {"tool": "vivado_launch_simulation", "why": "Launch simulation after the dry-run plan is accepted."},
            {"tool": "vivado_analyze_xsim_logs", "why": "Parse xsim/xelab/xvlog/xvhdl logs after launch failures."},
        ],
    }


def _nonproject_read_plan(
    *,
    output_path: Path,
    verilog: list[Path],
    systemverilog: list[Path],
    vhdl: list[Path],
    xdc: list[Path],
    include_dirs: list[Path],
    defines: list[str] | None,
    library: str | None,
    tcl_preview: str,
) -> dict[str, object]:
    actions: list[dict[str, object]] = []
    if verilog:
        actions.append({"action": "read_verilog", "paths": [str(path) for path in verilog], "library": library or ""})
    if systemverilog:
        actions.append({"action": "read_verilog", "mode": "systemverilog", "paths": [str(path) for path in systemverilog], "library": library or ""})
    if vhdl:
        actions.append({"action": "read_vhdl", "paths": [str(path) for path in vhdl], "library": library or ""})
    if xdc:
        actions.append({"action": "read_xdc", "paths": [str(path) for path in xdc], "scope": "global"})
    if include_dirs:
        actions.append({"action": "set_include_dirs", "paths": [str(path) for path in include_dirs]})
    if defines:
        actions.append({"action": "set_defines", "defines": defines})
    return {
        "operation": "nonproject_read_sources",
        "actions": actions,
        "summary_path": str(output_path),
        "risk_level": "low",
        "would_execute_tcl": bool(actions),
        "tcl_preview": tcl_preview,
        "recommended_docs": [
            {"doc_id": "UG892", "title": "Vivado Design Suite User Guide: Design Flows Overview"},
            {"doc_id": "UG894", "title": "Vivado Design Suite User Guide: Using Tcl Scripting"},
            {"doc_id": "UG903", "title": "Vivado Design Suite User Guide: Using Constraints"},
        ],
        "recommendations": [
            {"tool": "vivado_nonproject_audit", "why": "Inspect recorded inputs and missing part/top before synthesis."},
            {"tool": "vivado_nonproject_synth_design", "why": "Run synthesis with explicit top and part after sources are loaded."},
        ],
    }


def _nonproject_step_plan(
    *,
    output_path: Path,
    step: str,
    part: str | None,
    top: str | None,
    checkpoint_path: Path | None,
    reports: dict[str, Path],
    extra_args: dict[str, object] | None,
    tcl_preview: str,
) -> dict[str, object]:
    action: dict[str, object] = {
        "action": step,
        "part": part or "",
        "top": top or "",
        "extra_args": extra_args or {},
    }
    checkpoint = {
        "name": checkpoint_path.name if checkpoint_path else "",
        "path": str(checkpoint_path) if checkpoint_path else "",
    }
    report_rows = [
        {"type": report_type, "path": str(report_path)}
        for report_type, report_path in reports.items()
    ]
    return {
        "operation": "nonproject_run_step",
        "step": step,
        "actions": [action],
        "summary_path": str(output_path),
        "checkpoint": checkpoint,
        "reports": report_rows,
        "risk_level": "medium" if step in {"place_design", "route_design"} else "low",
        "would_execute_tcl": True,
        "tcl_preview": tcl_preview,
        "recommended_docs": [
            {"doc_id": "UG892", "title": "Vivado Design Suite User Guide: Design Flows Overview"},
            {"doc_id": "UG901", "title": "Vivado Design Suite User Guide: Synthesis"},
            {"doc_id": "UG904", "title": "Vivado Design Suite User Guide: Implementation"},
            {"doc_id": "UG906", "title": "Vivado Design Suite User Guide: Design Analysis and Closure Techniques"},
        ],
        "recommendations": [
            {"tool": "vivado_nonproject_audit", "why": "Review prerequisites and current Non-project stage before executing."},
            {"tool": "vivado_analyze_reports", "why": "Parse requested reports after the step completes."},
        ],
    }


def _resolve_ip_vlnv(
    *,
    vlnv: str | None,
    vendor: str | None,
    library: str | None,
    ip_name: str | None,
    version: str | None,
) -> str:
    explicit = (vlnv or "").strip()
    components = {
        "vendor": (vendor or "").strip(),
        "library": (library or "").strip(),
        "ip_name": (ip_name or "").strip(),
        "version": (version or "").strip(),
    }
    if explicit:
        if any(components.values()):
            raise ValueError("Provide either vlnv or vendor/library/ip_name/version, not both")
        return explicit
    missing = [key for key, value in components.items() if not value]
    if missing:
        raise ValueError("Provide vlnv or all of vendor, library, ip_name, and version")
    return "{vendor}:{library}:{ip_name}:{version}".format(**components)


def _parse_result(command_id: str, result_path: Path, command_path: Path) -> TclCommandResult:
    fields: dict[str, str] = {}
    current_key: str | None = None
    chunks: dict[str, list[str]] = {}
    for line in result_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.startswith(" "):
            key, value = line.split("=", 1)
            current_key = key
            fields[key] = value
            chunks[key] = [value]
        elif current_key:
            chunks[current_key].append(line)
    for key, values in chunks.items():
        fields[key] = "\n".join(values)
    return TclCommandResult(
        command_id=command_id,
        code=int(fields.get("code", "1")),
        result=fields.get("result", ""),
        started=fields.get("started"),
        finished=fields.get("finished"),
        result_path=result_path,
        command_path=command_path,
        errorinfo=fields.get("errorinfo"),
    )


def _result_to_dict(result: TclCommandResult, *, expect_destructive: bool) -> dict[str, object]:
    return {
        "command_id": result.command_id,
        "ok": result.ok,
        "code": result.code,
        "result": result.result,
        "errorinfo": result.errorinfo,
        "started": result.started,
        "finished": result.finished,
        "result_path": str(result.result_path) if result.result_path else None,
        "command_path": str(result.command_path) if result.command_path else None,
        "result_artifact_uri": _path_artifact_uri(result.result_path),
        "command_artifact_uri": _path_artifact_uri(result.command_path),
        "expect_destructive": expect_destructive,
    }


def artifact_uri(session_ref: str, relative_path: str) -> str:
    return f"vivado://sessions/{session_ref}/artifacts/{quote(relative_path, safe='')}"


def _path_artifact_uri(path: Path | None) -> str | None:
    if path is None:
        return None
    parts = path.parts
    try:
        index = parts.index("sessions")
        session_ref = parts[index + 1]
    except (ValueError, IndexError):
        return None
    relative = Path(*parts[index + 2 :]).as_posix()
    return artifact_uri(session_ref, relative)
