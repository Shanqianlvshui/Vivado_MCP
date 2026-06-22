from __future__ import annotations

from pathlib import Path


def parse_project_summary(path: Path) -> dict[str, object]:
    summary: dict[str, object] = {
        "has_project": False,
        "files": [],
        "runs": [],
        "ips": [],
        "block_designs": [],
    }
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        key = parts[0]
        values = parts[1:]
        if key == "has_project":
            summary["has_project"] = values[:1] == ["1"]
        elif key in {"current_project", "project_file", "part", "board_part", "top"}:
            summary[key] = values[0] if values else ""
        elif key == "file":
            summary["files"].append({"path": values[0] if values else "", "file_type": values[1] if len(values) > 1 else ""})
        elif key == "run":
            summary["runs"].append(
                {
                    "name": values[0] if values else "",
                    "status": values[1] if len(values) > 1 else "",
                    "progress": values[2] if len(values) > 2 else "",
                }
            )
        elif key == "ip":
            summary["ips"].append(values[0] if values else "")
        elif key == "block_design":
            summary["block_designs"].append(values[0] if values else "")
    return summary

