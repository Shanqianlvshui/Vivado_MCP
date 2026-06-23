from __future__ import annotations

from pathlib import Path


DESIGN_REPORT_TYPES = {
    "timing_summary",
    "timing_paths",
    "utilization",
    "drc",
    "power",
    "methodology",
    "clock_interaction",
}


def parse_report_context(path: Path) -> dict[str, object]:
    context: dict[str, object] = {
        "has_project": False,
        "current_design": "",
        "runs": [],
        "open_runs": [],
        "warnings": [],
    }
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        key = parts[0]
        values = parts[1:]
        if key == "has_project":
            context["has_project"] = values[:1] == ["1"]
        elif key == "current_design":
            context["current_design"] = values[0] if values else ""
        elif key == "run":
            run_name = values[0] if values else ""
            context["runs"].append(
                {
                    "name": run_name,
                    "status": values[1] if len(values) > 1 else "",
                    "progress": values[2] if len(values) > 2 else "",
                    "type": _run_type(run_name),
                    "scope": _run_scope(run_name),
                    "complete": _run_complete(values[1] if len(values) > 1 else "", values[2] if len(values) > 2 else ""),
                }
            )
        elif key == "open_run":
            run_name = values[0] if values else ""
            context["open_runs"].append({"name": run_name, "type": _run_type(run_name), "scope": _run_scope(run_name)})
        elif key == "warning" and values:
            context["warnings"].append(values[0])
    context["stage"] = _stage(context)
    context["available_report_types"] = available_report_types(context)
    context["recommended_actions"] = recommended_actions(context)
    return context


def available_report_types(context: dict[str, object]) -> list[str]:
    if str(context.get("current_design") or ""):
        return sorted(DESIGN_REPORT_TYPES)
    return []


def unavailable_report_reasons(context: dict[str, object], report_types: list[str]) -> list[dict[str, object]]:
    available = set(available_report_types(context))
    reasons: list[dict[str, object]] = []
    for report_type in report_types:
        if report_type in available:
            continue
        if report_type == "messages":
            reasons.append(
                {
                    "report_type": report_type,
                    "reason": "unsupported_report_command",
                    "severity": "low",
                    "next_step": "Use command/result artifacts or Vivado logs; report_messages is not available in the tested Vivado 2023.1 install.",
                    "suggested_tools": ["vivado_session_timeline", "vivado_read_artifact"],
                }
            )
            continue
        reasons.append(
            {
                "report_type": report_type,
                "reason": "no_open_design",
                "severity": "medium",
                "next_step": _open_design_next_step(context, report_type),
                "suggested_tools": _suggested_tools(context, report_type),
            }
        )
    return reasons


def recommended_actions(context: dict[str, object]) -> list[dict[str, object]]:
    if str(context.get("current_design") or ""):
        return [{"tool": "vivado_analyze_reports", "why": "A design is open; requested reports can be generated."}]
    synth = _first_complete_run(context, "synth")
    impl = _first_complete_run(context, "impl")
    actions: list[dict[str, object]] = []
    if impl:
        actions.append({"tool": "vivado_run_tcl", "why": f"Open completed implementation run {impl} before implementation reports.", "tcl": f"open_run {impl}"})
    if synth:
        actions.append({"tool": "vivado_run_tcl", "why": f"Open completed synthesis run {synth} before timing/utilization reports.", "tcl": f"open_run {synth}"})
    if not actions:
        actions.append({"tool": "vivado_run_synthesis", "why": "No open design or completed run was detected; run synthesis before design-stage reports."})
    return actions


def _stage(context: dict[str, object]) -> str:
    current_design = str(context.get("current_design") or "")
    if current_design:
        open_types = {
            str(row.get("type") or "")
            for row in context.get("open_runs", [])
            if isinstance(row, dict) and row.get("scope") == "top"
        }
        if "impl" in open_types:
            return "implementation_open"
        if "synth" in open_types:
            return "synthesis_open"
        return "design_open"
    if _first_complete_run(context, "impl"):
        return "implementation_complete_not_open"
    if _first_complete_run(context, "synth"):
        return "synthesis_complete_not_open"
    return "project_only"


def _run_type(name: str) -> str:
    lowered = str(name or "").lower()
    if lowered == "impl_1" or lowered.endswith("_impl_1"):
        return "impl"
    if lowered == "synth_1" or lowered.endswith("_synth_1"):
        return "synth"
    return "other"


def _run_scope(name: str) -> str:
    lowered = str(name or "").lower()
    if lowered in {"synth_1", "impl_1"}:
        return "top"
    if lowered.endswith("_synth_1") or lowered.endswith("_impl_1"):
        return "ooc"
    return "other"


def _run_complete(status: str, progress: str) -> bool:
    text = f"{status} {progress}".lower()
    return "complete" in text or "100%" in text


def _first_complete_run(context: dict[str, object], run_type: str) -> str:
    for row in context.get("runs", []) if isinstance(context.get("runs"), list) else []:
        if isinstance(row, dict) and row.get("type") == run_type and row.get("scope") == "top" and row.get("complete"):
            return str(row.get("name") or "")
    return ""


def _open_design_next_step(context: dict[str, object], report_type: str) -> str:
    if report_type in {"drc", "power", "methodology"} and _first_complete_run(context, "impl"):
        return f"Open completed implementation run {_first_complete_run(context, 'impl')} before generating {report_type}."
    if _first_complete_run(context, "synth"):
        return f"Open completed synthesis run {_first_complete_run(context, 'synth')} before generating {report_type}."
    return "Run synthesis or open an existing completed run before generating design-stage reports."


def _suggested_tools(context: dict[str, object], report_type: str) -> list[str]:
    if report_type in {"drc", "power", "methodology"} and _first_complete_run(context, "impl"):
        return ["vivado_run_tcl", "vivado_analyze_reports"]
    if _first_complete_run(context, "synth"):
        return ["vivado_run_tcl", "vivado_analyze_reports"]
    return ["vivado_run_synthesis", "vivado_project_summary"]
