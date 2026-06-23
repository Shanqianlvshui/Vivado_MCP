from __future__ import annotations

from pathlib import Path


def parse_ip_catalog(path: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for parts in _read_tsv(path):
        if not parts or parts[0] != "catalog_ip":
            continue
        rows.append(
            {
                "vlnv": parts[1] if len(parts) > 1 else "",
                "name": parts[2] if len(parts) > 2 else "",
                "display_name": parts[3] if len(parts) > 3 else "",
                "version": parts[4] if len(parts) > 4 else "",
                "vendor": parts[5] if len(parts) > 5 else "",
                "library": parts[6] if len(parts) > 6 else "",
                "taxonomy": parts[7] if len(parts) > 7 else "",
                "supported": _bool(parts[8] if len(parts) > 8 else "1"),
                "recommended_docs": _recommended_docs(parts[1] if len(parts) > 1 else ""),
            }
        )
    return {"ips": rows, "count": len(rows)}


def parse_ip_list(path: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    has_project = False
    current_project = ""
    for parts in _read_tsv(path):
        if not parts:
            continue
        key = parts[0]
        if key == "has_project":
            has_project = parts[1:2] == ["1"]
        elif key == "current_project":
            current_project = parts[1] if len(parts) > 1 else ""
        elif key == "ip":
            rows.append(_ip_row(parts))
    summary: dict[str, object] = {"has_project": has_project, "current_project": current_project, "ips": rows, "count": len(rows)}
    summary["upgrade_check"] = analyze_ip_upgrade(summary)
    return summary


def parse_ip_detail(path: Path) -> dict[str, object]:
    detail: dict[str, object] = {"name": "", "properties": {}, "targets": []}
    for parts in _read_tsv(path):
        if not parts:
            continue
        key = parts[0]
        if key == "ip":
            detail.update(_ip_row(parts))
        elif key == "property" and len(parts) >= 3:
            props = detail.setdefault("properties", {})
            assert isinstance(props, dict)
            props[parts[1]] = parts[2]
        elif key == "target" and len(parts) >= 2:
            targets = detail.setdefault("targets", [])
            assert isinstance(targets, list)
            targets.append(parts[1])
        elif key == "error" and len(parts) >= 2:
            detail["error"] = parts[1]
    if detail.get("name"):
        detail["status"] = _ip_status(detail)
        detail["recommended_docs"] = _recommended_docs(str(detail.get("vlnv") or ""))
    return detail


def analyze_ip_upgrade(summary: dict[str, object]) -> dict[str, object]:
    rows = _list_dicts(summary.get("ips"))
    issues: list[dict[str, object]] = []
    upgrade_needed: list[dict[str, object]] = []
    locked: list[dict[str, object]] = []
    stale_outputs: list[dict[str, object]] = []

    for row in rows:
        status = row.get("status") if isinstance(row.get("status"), dict) else _ip_status(row)
        item = {
            "name": row.get("name", ""),
            "vlnv": row.get("vlnv", ""),
            "xci_path": row.get("xci_path", ""),
            "status": status,
        }
        if status.get("needs_upgrade"):
            upgrade_needed.append(item)
        if status.get("locked"):
            locked.append(item)
        if not status.get("generated"):
            stale_outputs.append(item)

    if locked:
        issues.append({"issue_id": "ip.locked", "severity": "high", "ips": locked})
    if upgrade_needed:
        issues.append({"issue_id": "ip.upgrade_available", "severity": "medium", "ips": upgrade_needed})
    if stale_outputs:
        issues.append({"issue_id": "ip.outputs_not_generated", "severity": "medium", "ips": stale_outputs})

    return {
        "ok": not issues,
        "ip_count": len(rows),
        "upgrade_needed_count": len(upgrade_needed),
        "locked_count": len(locked),
        "outputs_not_generated_count": len(stale_outputs),
        "issues": issues,
        "recommendations": _upgrade_recommendations(issues),
        "suggested_next_tools": ["vivado_ip_upgrade_check", "vivado_describe_ip", "vivado_upgrade_ip", "vivado_generate_ip_outputs"],
    }


def _ip_row(parts: list[str]) -> dict[str, object]:
    row = {
        "name": parts[1] if len(parts) > 1 else "",
        "vlnv": parts[2] if len(parts) > 2 else "",
        "xci_path": parts[3] if len(parts) > 3 else "",
        "locked": _bool(parts[4] if len(parts) > 4 else "0"),
        "upgrade_available": _bool(parts[5] if len(parts) > 5 else "0"),
        "generated": _bool(parts[6] if len(parts) > 6 else "0"),
        "synthesis_status": parts[7] if len(parts) > 7 else "",
    }
    row["status"] = _ip_status(row)
    row["recommended_docs"] = _recommended_docs(str(row.get("vlnv") or ""))
    return row


def _ip_status(row: dict[str, object]) -> dict[str, object]:
    locked = bool(row.get("locked"))
    upgrade_available = bool(row.get("upgrade_available"))
    generated = bool(row.get("generated"))
    synthesis_status = str(row.get("synthesis_status") or "")
    return {
        "locked": locked,
        "needs_upgrade": upgrade_available,
        "generated": generated,
        "synthesis_status": synthesis_status,
        "output_products_stale": not generated,
        "risk_level": "high" if locked else "medium" if upgrade_available or not generated else "low",
    }


def _recommended_docs(vlnv: str) -> list[dict[str, str]]:
    docs = [
        {"doc_id": "UG896", "title": "Vivado Design Suite User Guide: Designing with IP"},
        {"doc_id": "UG835", "title": "Vivado Design Suite Tcl Command Reference Guide"},
    ]
    if ":ip:" in vlnv:
        docs.append({"doc_id": "IP Product Guide", "title": "Search by IP name or VLNV for the product guide."})
    return docs


def _upgrade_recommendations(issues: list[dict[str, object]]) -> list[dict[str, str]]:
    if not issues:
        return [{"tool": "vivado_list_ips", "why": "No IP upgrade or generated-output issue was detected."}]
    return [
        {"tool": "vivado_describe_ip", "why": "Inspect affected IP properties, VLNV, generated targets, and .xci path before mutation."},
        {"tool": "vivado_upgrade_ip", "why": "Run only with expect_upgrade=true when the .xci mutation is intended."},
        {"tool": "vivado_generate_ip_outputs", "why": "Regenerate output products after create or upgrade when generated state is stale."},
        {"tool": "vivado_search_official_docs", "why": "Use UG896 plus the IP product guide before changing CONFIG properties or upgrading IP."},
    ]


def _list_dicts(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _read_tsv(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(line.split("\t"))
    return rows


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}
