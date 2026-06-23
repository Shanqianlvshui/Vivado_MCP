from __future__ import annotations

from pathlib import Path


def parse_hardware_summary(path: Path) -> dict[str, object]:
    summary: dict[str, object] = {
        "servers": [],
        "targets": [],
        "devices": [],
        "properties": [],
        "warnings": [],
    }
    for parts in _read_tsv(path):
        if not parts:
            continue
        key = parts[0]
        if key == "server":
            _list(summary, "servers").append(
                {
                    "url": parts[1] if len(parts) > 1 else "",
                    "status": parts[2] if len(parts) > 2 else "",
                }
            )
        elif key == "target":
            _list(summary, "targets").append(
                {
                    "name": parts[1] if len(parts) > 1 else "",
                    "status": parts[2] if len(parts) > 2 else "",
                }
            )
        elif key == "device":
            _list(summary, "devices").append(
                {
                    "name": parts[1] if len(parts) > 1 else "",
                    "part": parts[2] if len(parts) > 2 else "",
                    "dna": parts[3] if len(parts) > 3 else "",
                    "programmed": _bool(parts[4] if len(parts) > 4 else "0"),
                    "status": parts[5] if len(parts) > 5 else "",
                }
            )
        elif key == "property":
            _list(summary, "properties").append(
                {
                    "object": parts[1] if len(parts) > 1 else "",
                    "name": parts[2] if len(parts) > 2 else "",
                    "value": parts[3] if len(parts) > 3 else "",
                }
            )
        elif key == "warning" and len(parts) >= 2:
            _list(summary, "warnings").append(parts[1])
        elif key == "error" and len(parts) >= 2:
            summary["error"] = parts[1]
    summary["server_count"] = len(summary["servers"]) if isinstance(summary["servers"], list) else 0
    summary["target_count"] = len(summary["targets"]) if isinstance(summary["targets"], list) else 0
    summary["device_count"] = len(summary["devices"]) if isinstance(summary["devices"], list) else 0
    return summary


def _read_tsv(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(line.split("\t"))
    return rows


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _list(container: dict[str, object], key: str) -> list[object]:
    value = container.setdefault(key, [])
    assert isinstance(value, list)
    return value
