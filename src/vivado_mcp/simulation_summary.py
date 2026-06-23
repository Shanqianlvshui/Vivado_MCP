from __future__ import annotations

import re
from pathlib import Path


SEVERITY_ORDER = {"info": 0, "warning": 1, "critical_warning": 2, "error": 3, "fatal": 4}


def parse_simulation_launch(path: Path) -> dict[str, object]:
    detail: dict[str, object] = {
        "simset": "",
        "mode": "",
        "type": "",
        "scripts_only": False,
        "log_paths": [],
        "warnings": [],
    }
    for parts in _read_tsv(path):
        if not parts:
            continue
        key = parts[0]
        if key == "simulation":
            detail["simset"] = parts[1] if len(parts) > 1 else ""
            detail["mode"] = parts[2] if len(parts) > 2 else ""
            if len(parts) == 4 and _looks_bool(parts[3]):
                detail["type"] = ""
                detail["scripts_only"] = _bool(parts[3])
            else:
                detail["type"] = parts[3] if len(parts) > 3 else ""
                detail["scripts_only"] = _bool(parts[4] if len(parts) > 4 else "0")
        elif key == "log" and len(parts) >= 3:
            _list(detail, "log_paths").append({"kind": parts[1], "path": parts[2]})
        elif key == "warning" and len(parts) >= 2:
            _list(detail, "warnings").append(parts[1])
        elif key == "error" and len(parts) >= 2:
            detail["error"] = parts[1]
    return detail


def analyze_xsim_logs(paths: list[Path]) -> dict[str, object]:
    logs: list[dict[str, object]] = []
    aggregate: dict[str, int] = {"fatal": 0, "error": 0, "critical_warning": 0, "warning": 0, "info": 0}
    issues: list[dict[str, object]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        parsed = _analyze_one_log(path, text)
        logs.append(parsed)
        for key in aggregate:
            aggregate[key] += int(parsed.get("counts", {}).get(key, 0)) if isinstance(parsed.get("counts"), dict) else 0
        issues.extend(parsed["issues"] if isinstance(parsed.get("issues"), list) else [])

    worst = "info"
    for issue in issues:
        severity = str(issue.get("severity") or "info")
        if SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER.get(worst, 0):
            worst = severity
    return {
        "ok": aggregate["fatal"] == 0 and aggregate["error"] == 0,
        "worst_severity": worst,
        "counts": aggregate,
        "logs": logs,
        "issues": issues,
        "suggested_next_tools": [
            "vivado_simulation_audit",
            "vivado_prepare_simulation",
            "vivado_launch_simulation",
            "vivado_search_official_docs",
        ],
        "official_doc_queries": _official_doc_queries(issues),
    }


def analyze_simulation_audit(
    *,
    filesets: dict[str, object],
    ip: dict[str, object] | None = None,
    fileset: str = "sim_1",
    top: str | None = None,
) -> dict[str, object]:
    described = _list_dicts(filesets.get("filesets"))
    selected = next((row for row in described if str(row.get("name") or "") == fileset), None)
    issues: list[dict[str, object]] = []
    if selected is None:
        issues.append({"issue_id": "sim.fileset_missing", "severity": "high", "fileset": fileset})
    else:
        sim_top = str(selected.get("top") or "")
        expected_top = str(top or "")
        if not sim_top:
            issues.append({"issue_id": "sim.top_not_set", "severity": "high", "fileset": fileset, "expected_top": expected_top})
        elif expected_top and sim_top != expected_top:
            issues.append({"issue_id": "sim.top_mismatch", "severity": "high", "fileset": fileset, "top": sim_top, "expected_top": expected_top})

        files = _list_dicts(selected.get("files"))
        tb_files = [row for row in files if _looks_testbench(row)]
        if not tb_files:
            issues.append({"issue_id": "sim.testbench_missing", "severity": "high", "fileset": fileset})

        disabled = [row for row in tb_files if row.get("is_enabled_simulation") is False]
        if disabled:
            issues.append({"issue_id": "sim.testbench_disabled", "severity": "high", "fileset": fileset, "files": disabled})

    ip_rows = _list_dicts((ip or {}).get("ips"))
    stale_ip = [row for row in ip_rows if row.get("generated") is False]
    upgrade_ip = [row for row in ip_rows if row.get("upgrade_available") is True]
    if stale_ip:
        issues.append({"issue_id": "sim.ip_outputs_not_generated", "severity": "medium", "ips": stale_ip})
    if upgrade_ip:
        issues.append({"issue_id": "sim.ip_upgrade_available", "severity": "medium", "ips": upgrade_ip})

    return {
        "ok": not issues,
        "fileset": fileset,
        "summary": {
            "fileset_found": selected is not None,
            "top": str(selected.get("top") or "") if selected else "",
            "ip_count": len(ip_rows),
            "issue_count": len(issues),
        },
        "issues": issues,
        "recommendations": _simulation_audit_recommendations(issues),
        "suggested_next_tools": [
            "vivado_prepare_simulation",
            "vivado_describe_fileset",
            "vivado_ip_upgrade_check",
            "vivado_generate_ip_outputs",
            "vivado_launch_simulation",
            "vivado_analyze_xsim_logs",
        ],
    }


def _analyze_one_log(path: Path, text: str) -> dict[str, object]:
    counts: dict[str, int] = {"fatal": 0, "error": 0, "critical_warning": 0, "warning": 0, "info": 0}
    issues: list[dict[str, object]] = []
    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        severity = _line_severity(line)
        if severity is None:
            continue
        counts[severity] += 1
        if severity == "info":
            continue
        issue = {
            "issue_id": _issue_id_for_message(line),
            "severity": severity,
            "path": str(path),
            "line": index,
            "message": line.strip(),
            "category": _classify_message(line),
        }
        code = _message_code(line)
        if code:
            issue["code"] = code
        issues.append(issue)
    return {
        "path": str(path),
        "line_count": len(lines),
        "counts": counts,
        "issues": issues[:50],
    }


def _line_severity(line: str) -> str | None:
    lowered = line.lower()
    prefix = re.match(r"^\s*(?:#\s*)?(?:\*\*\s*)?(critical warning|fatal|error|warning|info)\s*:", lowered)
    if not prefix:
        return None
    label = prefix.group(1)
    if label == "fatal":
        return "fatal"
    if label == "critical warning":
        return "critical_warning"
    if label == "error":
        return "error"
    if label == "warning":
        return "warning"
    if label == "info":
        return "info"
    return None


def _classify_message(line: str) -> str:
    lowered = line.lower()
    if any(term in lowered for term in ("syntax error", "parse error", "near")):
        return "syntax"
    if any(term in lowered for term in ("timescale", "timeunit", "timeprecision")):
        return "timescale"
    if any(term in lowered for term in ("unresolved", "undefined", "unknown module", "module not found")) or re.search(
        r"\bmodule\b.*\bnot found\b", lowered
    ):
        return "unresolved_design_unit"
    if any(term in lowered for term in ("cannot find", "not found", "no such file", "cannot open")):
        return "missing_file_or_library"
    if any(term in lowered for term in ("elaborat", "xelab")):
        return "elaboration"
    if any(term in lowered for term in ("xvlog", "xvhdl", "compile")):
        return "compile"
    return "general"


def _issue_id_for_message(line: str) -> str:
    lowered = line.lower()
    if any(term in lowered for term in ("include file", "`include", "cannot open include")):
        return "sim.include_file_missing"
    if any(term in lowered for term in ("ip simulation model", "compile_simlib", "ip static simulation", "simulation model is missing")):
        return "sim.ip_model_missing"
    if any(term in lowered for term in ("timescale", "timeunit", "timeprecision")):
        return "sim.timescale_missing"
    if any(term in lowered for term in ("unknown module", "module not found")) or re.search(r"\bmodule\b.*\bnot found\b", lowered):
        return "sim.module_not_found"
    if any(term in lowered for term in ("unresolved", "undefined")):
        return "sim.unresolved_design_unit"
    if any(term in lowered for term in ("elaborat", "xelab", "static elaboration")):
        return "sim.elaboration_failed"
    if any(term in lowered for term in ("xvlog", "xvhdl", "syntax error", "parse error")):
        return "sim.compile_failed"
    if "fatal" in lowered or "simulation aborted" in lowered:
        return "sim.runtime_failed"
    return "sim.log_issue"


def _official_doc_queries(issues: list[dict[str, object]]) -> list[dict[str, str]]:
    queries: list[dict[str, str]] = []
    issue_ids = {str(issue.get("issue_id") or "") for issue in issues}
    if issue_ids:
        queries.append({"topic": "simulation", "doc_id": "UG900", "query": "launch_simulation xelab xsim simulation troubleshooting"})
    if {"sim.ip_model_missing", "sim.ip_outputs_not_generated"} & issue_ids:
        queries.append({"topic": "ip", "doc_id": "UG896", "query": "IP simulation models generate output products"})
    if {"sim.include_file_missing", "sim.module_not_found", "sim.unresolved_design_unit"} & issue_ids:
        queries.append({"topic": "simulation", "doc_id": "UG900", "query": "simulation fileset include directories libraries top module"})
    return queries


def _simulation_audit_recommendations(issues: list[dict[str, object]]) -> list[dict[str, str]]:
    if not issues:
        return [{"tool": "vivado_launch_simulation", "why": "Simulation fileset audit did not find blocking setup issues."}]
    recommendations: list[dict[str, str]] = []

    def add(tool: str, why: str) -> None:
        if not any(row["tool"] == tool for row in recommendations):
            recommendations.append({"tool": tool, "why": why})

    issue_ids = {str(issue.get("issue_id") or "") for issue in issues}
    if {"sim.fileset_missing", "sim.top_not_set", "sim.top_mismatch", "sim.testbench_missing", "sim.testbench_disabled"} & issue_ids:
        add("vivado_prepare_simulation", "Create or repair the simulation fileset, top, testbench files, include dirs, defines, and library.")
        add("vivado_describe_fileset", "Inspect simulation fileset files, top, properties, and USED_IN simulation flags.")
    if {"sim.ip_outputs_not_generated", "sim.ip_upgrade_available"} & issue_ids:
        add("vivado_ip_upgrade_check", "Inspect IP lock, upgrade, and output-generation state before simulation.")
        add("vivado_generate_ip_outputs", "Generate IP simulation/output products when generated state is stale.")
    add("vivado_search_official_docs", "Use UG900 and UG896 when simulation setup or IP simulation model state is unclear.")
    return recommendations


def _looks_testbench(row: dict[str, object]) -> bool:
    path = str(row.get("path") or "").lower()
    file_type = str(row.get("file_type") or "").lower()
    return any(term in path for term in ("tb", "testbench")) or "simulation" in file_type


def _list_dicts(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _message_code(line: str) -> str:
    match = re.search(r"\[([A-Za-z0-9_ -]+-[0-9]+)\]", line)
    return match.group(1).strip() if match else ""


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


def _looks_bool(value: str) -> bool:
    return str(value).strip().lower() in {"0", "1", "true", "false", "yes", "no"}


def _list(container: dict[str, object], key: str) -> list[object]:
    value = container.setdefault(key, [])
    assert isinstance(value, list)
    return value
