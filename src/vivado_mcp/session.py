from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from importlib import resources
from pathlib import Path
from urllib.parse import quote, unquote

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
            "session_dir": str(running.record.session_dir),
            "workspace_dir": str(running.record.workspace_dir),
            "log_path": str(running.record.log_path),
            "open_gui": running.record.open_gui,
            "capability_profile": running.record.capability_profile,
            "allowed_roots": [str(root) for root in self.path_policy.roots],
        }

    def list_artifacts(self, session_ref: str) -> dict[str, object]:
        running = self._get(session_ref)
        artifacts = []
        for path in sorted(running.record.session_dir.rglob("*")):
            if path.is_file():
                relative = path.relative_to(running.record.session_dir).as_posix()
                artifacts.append(
                    {
                        "path": str(path),
                        "relative_path": relative,
                        "artifact_uri": artifact_uri(session_ref, relative),
                        "size": path.stat().st_size,
                    }
                )
        return {"session_ref": session_ref, "artifacts": artifacts}

    def read_artifact(self, session_ref: str, artifact_id: str, max_chars: int = 20000) -> dict[str, object]:
        running = self._get(session_ref)
        relative = unquote(artifact_id)
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

    def run_tcl(
        self,
        *,
        session_ref: str,
        tcl: str,
        timeout_seconds: int = 60,
        expect_destructive: bool = False,
    ) -> dict[str, object]:
        running = self._get(session_ref)
        if running.record.capability_profile == "safe":
            raise PermissionError("Raw Tcl is disabled for safe capability profile")
        result = self._submit_tcl(running, tcl, timeout_seconds=timeout_seconds)
        return _result_to_dict(result, expect_destructive=expect_destructive)

    def source_tcl(
        self,
        *,
        session_ref: str,
        script_path: str,
        tclargs: list[str] | None = None,
        timeout_seconds: int = 120,
        expect_destructive: bool = False,
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
        result = self._submit_tcl(
            running,
            tcl=body,
            timeout_seconds=timeout_seconds,
        )
        return _result_to_dict(result, expect_destructive=expect_destructive)

    def stop_session(self, session_ref: str, *, force: bool = False, timeout_seconds: int = 20) -> dict[str, object]:
        running = self._get(session_ref)
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
        with self._lock:
            self._sessions.pop(session_ref, None)

        return {
            "session_ref": session_ref,
            "process_exit_code": running.process.returncode,
            "stop_result": stop_result,
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

    def open_project(self, *, session_ref: str, project_path: str, timeout_seconds: int = 120) -> dict[str, object]:
        from .tcl import open_project_tcl

        running = self._get(session_ref)
        path = self.path_policy.require_under_roots(project_path, label="project_path", must_exist=True)
        result = self._submit_tcl(running, open_project_tcl(path), timeout_seconds=timeout_seconds)
        return _result_to_dict(result, expect_destructive=False)

    def add_sources(
        self,
        *,
        session_ref: str,
        sources: list[str] | None = None,
        constraints: list[str] | None = None,
        top: str | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        from .tcl import add_sources_tcl

        source_paths = [self.path_policy.require_under_roots(path, label="source", must_exist=True) for path in sources or []]
        constraint_paths = [
            self.path_policy.require_under_roots(path, label="constraint", must_exist=True) for path in constraints or []
        ]
        running = self._get(session_ref)
        result = self._submit_tcl(
            running,
            add_sources_tcl(sources=source_paths, constraints=constraint_paths, top=top),
            timeout_seconds=timeout_seconds,
        )
        return _result_to_dict(result, expect_destructive=False)

    def launch_run(
        self,
        *,
        session_ref: str,
        run_name: str,
        jobs: int | None = None,
        to_step: str | None = None,
        timeout_seconds: int = 3600,
    ) -> dict[str, object]:
        from .tcl import launch_run_tcl

        running = self._get(session_ref)
        result = self._submit_tcl(
            running,
            launch_run_tcl(run_name=run_name, jobs=jobs, to_step=to_step),
            timeout_seconds=timeout_seconds,
        )
        return _result_to_dict(result, expect_destructive=False)

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
