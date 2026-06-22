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
            command.rename(target)
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
    if "version -short" in body:
        return "version=2023.1"
    if "create_project" in body:
        return "project_created=fake"
    if "open_project" in body:
        return "project_opened=fake"
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
    report_match = re.search(r"-file \{([^}]+)\}", body)
    if report_match:
        path = Path(report_match.group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("FAKE REPORT\nWNS 0.000\n", encoding="utf-8")
        return f"report={path}"
    if "vivado_mcp_bridge_forever" in body:
        return "stopping"
    return "ok"


if __name__ == "__main__":
    raise SystemExit(main())
