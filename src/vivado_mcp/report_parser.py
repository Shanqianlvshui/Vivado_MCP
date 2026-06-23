from __future__ import annotations

import re
from collections import Counter


def parse_report(report_type: str, text: str) -> dict[str, object]:
    if report_type in {"timing_summary", "timing_paths"}:
        return parse_timing(text)
    if report_type == "utilization":
        return parse_utilization(text)
    if report_type in {"drc", "methodology", "messages"}:
        return parse_messages(text, report_type=report_type)
    if report_type == "power":
        return parse_power(text)
    if report_type == "clock_interaction":
        return parse_clock_interaction(text)
    return {"report_type": report_type, "parsed": False}


def parse_timing(text: str) -> dict[str, object]:
    values: dict[str, float] = {}
    for key in ["WNS", "TNS", "WHS", "THS", "WPWS", "TPWS"]:
        match = re.search(rf"\b{key}\b\s*(?:\([^)]+\))?\s*[:=]?\s*(-?\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if match:
            values[key.lower()] = float(match.group(1))

    ints: dict[str, int] = {}
    for label, field in (
        ("Failing Endpoints", "failing_endpoints"),
        ("Total Endpoints", "total_endpoints"),
        ("Timing Errors", "timing_errors"),
        ("Unconstrained Paths", "unconstrained_paths"),
        ("Unconstrained Clocks", "unconstrained_clocks"),
        ("Clock Interaction Warnings", "clock_interaction_warnings"),
    ):
        value = _extract_int_label(text, label)
        if value is not None:
            ints[field] = value

    if "unconstrained_paths" not in ints and re.search(r"\bunconstrained\s+path", text, re.IGNORECASE):
        ints["unconstrained_paths"] = _count_phrase(text, "unconstrained path")
    if "unconstrained_clocks" not in ints and re.search(r"\bunconstrained\s+clock", text, re.IGNORECASE):
        ints["unconstrained_clocks"] = _count_phrase(text, "unconstrained clock")
    if "clock_interaction_warnings" not in ints and re.search(r"\b(clock interaction|unsafe clock)", text, re.IGNORECASE):
        ints["clock_interaction_warnings"] = max(1, len(re.findall(r"\b(clock interaction|unsafe clock)", text, re.IGNORECASE)))

    slacks = [float(match.group(1)) for match in re.finditer(r"Slack\s*\((?:VIOLATED|MET)\)\s*:\s*(-?\d+(?:\.\d+)?)\s*ns?", text, re.IGNORECASE)]
    violated_slacks = [value for value in slacks if value < 0]
    if slacks:
        values["worst_slack_ns"] = min(slacks)
        ints["violated_path_count"] = len(violated_slacks)

    status = "unknown"
    wns = values.get("wns")
    whs = values.get("whs")
    worst_slack = values.get("worst_slack_ns")
    pulse_width_failed = any(values.get(key, 0.0) < 0 for key in ("wpws", "tpws"))
    if wns is not None or whs is not None or worst_slack is not None or pulse_width_failed:
        status = "fail" if (wns is not None and wns < 0) or (whs is not None and whs < 0) or (worst_slack is not None and worst_slack < 0) or pulse_width_failed else "pass"

    setup = {key: values[key] for key in ("wns", "tns") if key in values}
    hold = {key: values[key] for key in ("whs", "ths") if key in values}
    pulse_width = {key: values[key] for key in ("wpws", "tpws") if key in values}
    coverage = {key: ints[key] for key in ("unconstrained_paths", "unconstrained_clocks", "clock_interaction_warnings") if key in ints}
    path_sample = _timing_path_sample(text)

    summary = {
        "report_type": "timing",
        "parsed": bool(values or ints),
        "status": status,
        "setup": setup,
        "hold": hold,
        "pulse_width": pulse_width,
        "constraint_coverage": coverage,
        **values,
        **ints,
    }
    if path_sample:
        summary["timing_path_sample"] = path_sample
    return summary


def parse_utilization(text: str) -> dict[str, object]:
    resources: dict[str, dict[str, int | float | str]] = {}
    aliases = {
        "CLB LUTs": ("clb_luts", "lut"),
        "LUT": ("lut", "lut"),
        "CLB Registers": ("clb_registers", "ff"),
        "FF": ("ff", "ff"),
        "Block RAM Tile": ("block_ram_tile", "bram"),
        "BRAM": ("bram", "bram"),
        "DSPs": ("dsps", "dsp"),
        "DSP": ("dsp", "dsp"),
        "URAM": ("uram", "uram"),
        "Bonded IOB": ("bonded_iob", "io"),
        "IOB": ("iob", "io"),
        "BUFG": ("bufg", "clocking"),
        "BUFGCE": ("bufgce", "clocking"),
        "MMCM": ("mmcm", "clocking"),
        "PLL": ("pll", "clocking"),
    }
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        name = cells[0]
        if name not in aliases:
            continue
        numbers = [_parse_number(cell) for cell in cells[1:]]
        numeric = [value for value in numbers if value is not None]
        if len(numeric) < 3:
            continue
        used = int(numeric[0])
        utilization = float(numeric[-1])
        available = _infer_available(numeric)
        key, resource_class = aliases[name]
        resources[key] = {
            "used": used,
            "available": available,
            "utilization_percent": utilization,
            "resource_class": resource_class,
        }
    return {"report_type": "utilization", "parsed": bool(resources), "resources": resources}


def parse_messages(text: str, report_type: str = "messages") -> dict[str, object]:
    rules: dict[str, dict[str, int]] = {}
    messages: list[dict[str, str]] = []
    categories: Counter[str] = Counter()
    category_rules: dict[str, Counter[str]] = {}
    pattern = re.compile(r"\b(ERROR|CRITICAL WARNING|WARNING):\s*\[([^\]]+)\]\s*(.*)", re.IGNORECASE)
    for match in pattern.finditer(text):
        severity = match.group(1).upper()
        rule = match.group(2).strip()
        message = match.group(3).strip()
        field = _severity_field(severity)
        row = rules.setdefault(rule, {"errors": 0, "critical_warnings": 0, "warnings": 0})
        row[field] += 1
        category = _rule_category(rule, message)
        categories[category] += 1
        category_rules.setdefault(category, Counter())[rule] += 1
        messages.append(
            {
                "severity": severity.lower().replace(" ", "_"),
                "rule_id": rule,
                "category": category,
                "message": message,
            }
        )
    return {
        "report_type": report_type,
        "parsed": True,
        "errors": sum(row["errors"] for row in rules.values()),
        "critical_warnings": sum(row["critical_warnings"] for row in rules.values()),
        "warnings": sum(row["warnings"] for row in rules.values()),
        "rules": rules,
        "rule_categories": dict(categories),
        "category_rules": {category: dict(counts) for category, counts in category_rules.items()},
        "messages": messages[:25],
    }


def parse_clock_interaction(text: str) -> dict[str, object]:
    unsafe = len(re.findall(r"\bunsafe\b", text, re.IGNORECASE))
    no_common = len(re.findall(r"\bno\s+common\s+(?:primary\s+)?clock\b", text, re.IGNORECASE))
    partial = len(re.findall(r"\bpartial\b", text, re.IGNORECASE))
    ignored = len(re.findall(r"\bignored\b", text, re.IGNORECASE))
    return {
        "report_type": "clock_interaction",
        "parsed": any((unsafe, no_common, partial, ignored)),
        "unsafe_count": unsafe,
        "no_common_clock_count": no_common,
        "partial_count": partial,
        "ignored_count": ignored,
    }


def parse_power(text: str) -> dict[str, object]:
    fields: dict[str, object] = {}
    patterns = {
        "total_on_chip_power_w": r"Total\s+(?:On-Chip\s+)?Power\s*(?:\(W\))?\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
        "dynamic_power_w": r"Dynamic(?:\s+Power)?\s*(?:\(W\))?\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
        "static_power_w": r"(?:Device\s+)?Static(?:\s+Power)?\s*(?:\(W\))?\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
        "junction_temperature_c": r"Junction\s+Temperature\s*(?:\(\s*(?:C|degC)\s*\))?\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
        "thermal_margin_c": r"Thermal\s+Margin\s*(?:\(\s*(?:C|degC)\s*\))?\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            fields[field] = float(match.group(1))
    confidence = re.search(r"Confidence\s+Level\s*[:=]?\s*([A-Za-z]+)", text, re.IGNORECASE)
    if confidence:
        fields["confidence_level"] = confidence.group(1).lower()
    return {"report_type": "power", "parsed": bool(fields), **fields}


def analyze_report_summaries(summaries: dict[str, dict[str, object]]) -> dict[str, object]:
    issues: list[dict[str, object]] = []
    for report_type, summary in summaries.items():
        if not summary or summary.get("parsed") is False:
            issues.append(
                _issue(
                    "report.unparsed",
                    "low",
                    report_type,
                    "Report parser did not find a known summary structure.",
                    "Read the report artifact or run a more specific Vivado report.",
                    "reports",
                    ["UG906"],
                    ["Vivado report interpretation unparsed report"],
                )
            )
            continue
        if summary.get("report_type") == "timing":
            issues.extend(_analyze_timing(report_type, summary))
        elif summary.get("report_type") == "utilization":
            issues.extend(_analyze_utilization(report_type, summary))
        elif summary.get("report_type") in {"drc", "methodology", "messages"}:
            issues.extend(_analyze_messages(report_type, summary))
        elif summary.get("report_type") == "power":
            issues.extend(_analyze_power(report_type, summary))
        elif summary.get("report_type") == "clock_interaction":
            issues.extend(_analyze_clock_interaction(report_type, summary))

    issues = [_enrich_issue(issue) for issue in issues]
    issues.sort(key=_issue_sort_key)
    return {
        "ok": not any(issue.get("severity") == "high" for issue in issues),
        "summary": {
            "report_count": len(summaries),
            "issue_count": len(issues),
            "high_count": sum(1 for issue in issues if issue.get("severity") == "high"),
            "medium_count": sum(1 for issue in issues if issue.get("severity") == "medium"),
            "low_count": sum(1 for issue in issues if issue.get("severity") == "low"),
        },
        "issues": issues,
        "quality_gates": _quality_gates(issues),
        "next_action_plan": _next_action_plan(issues),
        "suggested_next_tools": _suggested_next_tools(issues),
        "official_references": _official_references_for_issues(issues),
    }


def append_report_generation_issues(analysis: dict[str, object], failed_reports: list[dict[str, object]]) -> dict[str, object]:
    issues = analysis.setdefault("issues", [])
    if not isinstance(issues, list):
        issues = []
        analysis["issues"] = issues
    for report in failed_reports:
        issues.append(
            _enrich_issue(
                _issue(
                    "report.generation_failed",
                    "medium",
                    str(report.get("report_type") or "unknown"),
                    str(report.get("error") or "Vivado report command returned a non-zero result."),
                    "Inspect command/result artifacts and confirm the current design stage supports this report.",
                    "reports",
                    ["UG906"],
                    ["Vivado report command failed current design stage"],
                    result_artifact_uri=report.get("result_artifact_uri"),
                    command_artifact_uri=report.get("command_artifact_uri"),
                    report_artifact_uri=report.get("report_artifact_uri"),
                    report_path=report.get("report_path"),
                )
            )
        )
    issues.sort(key=_issue_sort_key)
    _refresh_analysis_rollups(analysis)
    return analysis


def append_report_unavailable_issues(analysis: dict[str, object], unavailable_reports: list[dict[str, object]]) -> dict[str, object]:
    issues = analysis.setdefault("issues", [])
    if not isinstance(issues, list):
        issues = []
        analysis["issues"] = issues
    for report in unavailable_reports:
        issues.append(
            _enrich_issue(
                _issue(
                    "report.unavailable",
                    str(report.get("severity") or "medium"),
                    str(report.get("report_type") or "unknown"),
                    str(report.get("reason") or "Report is not available in the current design stage."),
                    str(report.get("next_step") or "Open or create a design stage that supports this report."),
                    "reports",
                    ["UG906", "UG904"],
                    ["Vivado report current design open_run"],
                    suggested_tools=report.get("suggested_tools"),
                )
            )
        )
    issues.sort(key=_issue_sort_key)
    _refresh_analysis_rollups(analysis)
    return analysis


def _analyze_timing(report_type: str, summary: dict[str, object]) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    wns = _float_value(summary.get("wns"))
    tns = _float_value(summary.get("tns"))
    whs = _float_value(summary.get("whs"))
    ths = _float_value(summary.get("ths"))
    failing = _int_value(summary.get("failing_endpoints"))
    unconstrained_paths = _int_value(summary.get("unconstrained_paths")) or 0
    unconstrained_clocks = _int_value(summary.get("unconstrained_clocks")) or 0
    clock_interaction = _int_value(summary.get("clock_interaction_warnings")) or 0
    worst_slack = _float_value(summary.get("worst_slack_ns"))
    violated_paths = _int_value(summary.get("violated_path_count")) or 0
    wpws = _float_value(summary.get("wpws"))
    tpws = _float_value(summary.get("tpws"))

    if unconstrained_paths or unconstrained_clocks:
        issues.append(
            _issue(
                "timing.unconstrained_paths",
                "high",
                report_type,
                f"unconstrained_paths={unconstrained_paths}, unconstrained_clocks={unconstrained_clocks}",
                "Audit clock definitions, XDC order, and unconstrained path coverage before tuning implementation.",
                "constraints",
                ["UG906", "UG903", "UG949"],
                ["Vivado unconstrained paths timing summary", "UG903 clock constraints unconstrained paths"],
            )
        )
    if wns is not None and wns < 0:
        issues.append(
            _issue(
                "timing.setup_failed",
                "high",
                report_type,
                f"WNS={wns} ns, TNS={tns if tns is not None else 'unknown'}, failing_endpoints={failing if failing is not None else 'unknown'}",
                "Run timing paths and inspect the worst setup paths before changing constraints or implementation strategy.",
                "timing",
                ["UG906", "UG949", "UG1292"],
                ["Vivado WNS TNS setup timing closure", "UG1292 setup timing closure checklist"],
            )
        )
    if worst_slack is not None and worst_slack < 0 and wns is None:
        issues.append(
            _issue(
                "timing.path_slack_failed",
                "high",
                report_type,
                f"worst_slack={worst_slack} ns, violated_path_count={violated_paths}",
                "Inspect the worst timing paths and classify whether the failure is logic depth, routing, clocking, or constraints.",
                "timing",
                ["UG906", "UG949", "UG1292"],
                ["Vivado report_timing slack violated path timing closure"],
                timing_path_sample=summary.get("timing_path_sample"),
            )
        )
    if whs is not None and whs < 0:
        issues.append(
            _issue(
                "timing.hold_failed",
                "high",
                report_type,
                f"WHS={whs} ns, THS={ths if ths is not None else 'unknown'}",
                "Inspect hold timing paths and confirm clocks/IO delays before rerunning implementation.",
                "timing",
                ["UG906", "UG949", "UG1292"],
                ["Vivado WHS THS hold timing closure", "UG1292 hold timing closure"],
            )
        )
    if (wpws is not None and wpws < 0) or (tpws is not None and tpws < 0):
        issues.append(
            _issue(
                "timing.pulse_width_failed",
                "high",
                report_type,
                f"WPWS={wpws if wpws is not None else 'unknown'} ns, TPWS={tpws if tpws is not None else 'unknown'} ns",
                "Inspect pulse-width checks, generated clocks, waveform definitions, and clock-modifying logic.",
                "timing",
                ["UG906", "UG903", "UG949"],
                ["Vivado pulse width timing WPWS TPWS generated clock"],
            )
        )
    if clock_interaction:
        issues.append(
            _issue(
                "timing.clock_interaction_issue",
                "medium",
                report_type,
                f"clock_interaction_warnings={clock_interaction}",
                "Run or inspect clock interaction details and verify asynchronous/logically exclusive clock relationships.",
                "timing",
                ["UG906", "UG903", "UG949"],
                ["Vivado clock interaction report unsafe clocks", "UG903 set_clock_groups clock interaction"],
            )
        )
    if summary.get("status") == "pass":
        issues.append(
            _issue(
                "timing.pass",
                "low",
                report_type,
                f"WNS={wns} ns",
                "Continue with utilization, DRC, power, and methodology checks.",
                "reports",
                ["UG906"],
                ["Vivado timing summary report interpretation"],
            )
        )
    return issues


def _analyze_utilization(report_type: str, summary: dict[str, object]) -> list[dict[str, object]]:
    resources = summary.get("resources")
    if not isinstance(resources, dict):
        return []
    issues: list[dict[str, object]] = []
    for name, row in resources.items():
        if not isinstance(row, dict):
            continue
        pct = _float_value(row.get("utilization_percent"))
        if pct is None:
            continue
        resource_class = str(row.get("resource_class") or "")
        severity = "high" if pct >= 95 else "medium" if pct >= 80 else None
        if severity:
            used = _int_value(row.get("used"))
            available = _int_value(row.get("available"))
            issue_id = _utilization_issue_id(resource_class)
            next_step = _utilization_next_step(resource_class)
            refs = ["UG906", "UG949"]
            if resource_class == "io":
                refs.append("UG899")
            issues.append(
                _issue(
                    issue_id,
                    severity,
                    report_type,
                    f"{name} utilization is {pct}%"
                    + (f" ({used}/{available})" if used is not None and available is not None else ""),
                    next_step,
                    "utilization",
                    refs,
                    ["Vivado report_utilization resource pressure", "UG949 utilization timing closure resource sharing"],
                    resource=name,
                    resource_class=resource_class,
                )
            )
    return issues


def _analyze_messages(report_type: str, summary: dict[str, object]) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    errors = _int_value(summary.get("errors")) or 0
    critical = _int_value(summary.get("critical_warnings")) or 0
    categories = summary.get("rule_categories") if isinstance(summary.get("rule_categories"), dict) else {}

    category_specs = [
        ("io_standard_missing", "drc.io_standard_missing", "high", "Set explicit IOSTANDARD constraints for affected ports before bitstream generation.", ["UG903", "UG899", "UG906"], ["DRC NSTD-1 Unspecified I/O Standard Vivado"]),
        ("io_pin_unconstrained", "drc.io_pin_unconstrained", "high", "Set PACKAGE_PIN/LOC constraints or remove unused top-level ports.", ["UG903", "UG899", "UG906"], ["DRC UCIO-1 Unconstrained Logical Port Vivado"]),
        ("bitstream_blocker", "drc.bitstream_blocker", "high", "Fix DRC blockers before attempting bitstream generation.", ["UG906", "UG904"], ["Vivado DRC bitstream blocker write_bitstream"]),
        ("clocking", "methodology.clocking_issue", "medium", "Review clock definitions, generated clocks, clock groups, and clock-domain crossings.", ["UG906", "UG903", "UG949", "UG1292"], ["Vivado methodology TIMING clocking issue"]),
        ("timing", "methodology.timing_issue", "medium", "Review methodology timing rules before changing implementation strategy.", ["UG906", "UG949", "UG1292"], ["Vivado methodology timing rule report"]),
        ("cdc", "methodology.cdc_issue", "medium", "Review CDC synchronizers, asynchronous crossings, and clock grouping before timing closure iterations.", ["UG906", "UG949", "UG1292"], ["Vivado methodology CDC unsafe crossing"]),
        ("reset", "methodology.reset_issue", "medium", "Review reset topology, synchronizers, fanout, and timing impact before implementation tuning.", ["UG906", "UG949", "UG1292"], ["Vivado methodology reset synchronization fanout"]),
    ]
    emitted_categories: set[str] = set()
    for category, issue_id, default_severity, next_step, refs, queries in category_specs:
        count = _int_value(categories.get(category)) if isinstance(categories, dict) else None
        if not count:
            continue
        emitted_categories.add(category)
        severity = "high" if report_type == "drc" and category.startswith("io_") else default_severity
        issues.append(
            _issue(
                issue_id,
                severity,
                report_type,
                f"{count} {category} rule message(s)",
                next_step,
                "methodology" if issue_id.startswith("methodology") else "constraints",
                refs,
                queries,
                rules=_top_rules_by_category(summary, category),
            )
        )

    if errors and not emitted_categories.intersection({"io_standard_missing", "io_pin_unconstrained"}):
        issues.append(
            _issue(
                "drc.error" if report_type == "drc" else "report.error",
                "high",
                report_type,
                f"{errors} errors reported",
                "Fix error rules before rerunning implementation or timing closure.",
                "reports",
                ["UG906", "UG949"],
                ["Vivado DRC error report interpretation"],
                rules=_top_rules(summary, "errors"),
            )
        )
    if critical and not emitted_categories.intersection({"clocking", "timing"}):
        issues.append(
            _issue(
                "methodology.critical_warning" if report_type == "methodology" else "report.critical_warning",
                "medium",
                report_type,
                f"{critical} critical warnings reported",
                "Group warnings by rule ID and resolve methodology or constraint issues before closure attempts.",
                "methodology",
                ["UG906", "UG949", "UG1292"],
                ["Vivado methodology critical warning report"],
                rules=_top_rules(summary, "critical_warnings"),
            )
        )
    return issues


def _analyze_power(report_type: str, summary: dict[str, object]) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    total = _float_value(summary.get("total_on_chip_power_w"))
    dynamic = _float_value(summary.get("dynamic_power_w"))
    junction = _float_value(summary.get("junction_temperature_c"))
    margin = _float_value(summary.get("thermal_margin_c"))
    confidence = str(summary.get("confidence_level") or "").lower()
    if margin is not None and margin < 5.0:
        issues.append(
            _issue(
                "power.thermal_risk",
                "high",
                report_type,
                f"thermal_margin={margin} C" + (f", junction_temperature={junction} C" if junction is not None else ""),
                "Check activity assumptions, cooling, device power constraints, and power optimization before continuing closure.",
                "power",
                ["UG907", "UG906"],
                ["Vivado power thermal margin junction temperature"],
            )
        )
    elif junction is not None and junction >= 85.0:
        issues.append(
            _issue(
                "power.thermal_risk",
                "medium",
                report_type,
                f"junction_temperature={junction} C",
                "Check activity assumptions and thermal model before relying on power results.",
                "power",
                ["UG907", "UG906"],
                ["Vivado power junction temperature thermal analysis"],
            )
        )

    if total is not None:
        severity = "high" if total >= 7.0 else "medium" if total >= 5.0 else None
        if severity:
            issues.append(
                _issue(
                    "power.high_total",
                    severity,
                    report_type,
                    f"Total on-chip power is {total} W" + (f", dynamic={dynamic} W" if dynamic is not None else ""),
                    "Check activity assumptions and run power optimization or hierarchical power analysis.",
                    "power",
                    ["UG907", "UG906"],
                    ["Vivado report_power total on-chip power optimization"],
                )
            )
    if confidence in {"low", "medium"}:
        issues.append(
            _issue(
                "power.low_confidence",
                "medium" if confidence == "low" else "low",
                report_type,
                f"report_power confidence level is {confidence}",
                "Improve switching activity inputs with SAIF/VCD or representative simulation before acting on power totals.",
                "power",
                ["UG907", "UG906"],
                ["Vivado report_power confidence level SAIF VCD activity"],
            )
        )
    return issues


def _analyze_clock_interaction(report_type: str, summary: dict[str, object]) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    unsafe = _int_value(summary.get("unsafe_count")) or 0
    no_common = _int_value(summary.get("no_common_clock_count")) or 0
    partial = _int_value(summary.get("partial_count")) or 0
    ignored = _int_value(summary.get("ignored_count")) or 0
    if unsafe or no_common:
        issues.append(
            _issue(
                "clock_interaction.unsafe",
                "high",
                report_type,
                f"unsafe={unsafe}, no_common_clock={no_common}",
                "Classify each clock pair and add valid generated clocks, clock groups, or timing exceptions.",
                "timing",
                ["UG906", "UG903", "UG949"],
                ["Vivado report_clock_interaction unsafe no common clock"],
            )
        )
    if partial or ignored:
        issues.append(
            _issue(
                "clock_interaction.partial",
                "medium",
                report_type,
                f"partial={partial}, ignored={ignored}",
                "Inspect partial or ignored clock interaction coverage before assuming CDC paths are intentional.",
                "timing",
                ["UG906", "UG903", "UG949"],
                ["Vivado report_clock_interaction partial ignored constraints"],
            )
        )
    return issues


def _issue(
    issue_id: str,
    severity: str,
    report_type: str,
    evidence: str,
    next_step: str,
    official_doc_topic: str,
    official_references: list[str],
    official_doc_queries: list[str],
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "issue_id": issue_id,
        "severity": severity,
        "report_type": report_type,
        "evidence": evidence,
        "next_step": next_step,
        "official_doc_topic": official_doc_topic,
        "official_references": official_references,
        "official_doc_queries": official_doc_queries,
    }
    row.update({key: value for key, value in extra.items() if value is not None})
    return row


def _issue_sort_key(issue: dict[str, object]) -> tuple[int, int, str]:
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    priority_rank = {
        "drc.io_standard_missing": 0,
        "drc.io_pin_unconstrained": 0,
        "drc.bitstream_blocker": 0,
        "drc.error": 0,
        "report.error": 0,
        "report.unavailable": 0,
        "report.generation_failed": 0,
        "timing.unconstrained_paths": 1,
        "timing.setup_failed": 2,
        "timing.path_slack_failed": 2,
        "timing.hold_failed": 3,
        "timing.pulse_width_failed": 3,
        "clock_interaction.unsafe": 4,
        "timing.clock_interaction_issue": 4,
        "clock_interaction.partial": 4,
        "methodology.clocking_issue": 5,
        "methodology.cdc_issue": 5,
        "methodology.reset_issue": 6,
        "methodology.timing_issue": 6,
        "methodology.critical_warning": 7,
        "utilization.io_pressure": 8,
        "utilization.clock_buffer_pressure": 8,
        "utilization.resource_pressure": 8,
        "power.thermal_risk": 9,
        "power.high_total": 10,
        "power.low_confidence": 11,
    }
    return (
        severity_rank.get(str(issue.get("severity")), 99),
        priority_rank.get(str(issue.get("issue_id")), 50),
        str(issue.get("issue_id")),
    )


def _top_rules(summary: dict[str, object], field: str) -> list[dict[str, object]]:
    rules = summary.get("rules")
    if not isinstance(rules, dict):
        return []
    rows = []
    for rule, counts in rules.items():
        if isinstance(counts, dict) and _int_value(counts.get(field)):
            rows.append({"rule": rule, "count": _int_value(counts.get(field)) or 0})
    rows.sort(key=lambda row: row["count"], reverse=True)
    return rows[:5]


def _top_rules_by_category(summary: dict[str, object], category: str) -> list[dict[str, object]]:
    messages = summary.get("messages")
    if not isinstance(messages, list):
        return []
    counts: Counter[str] = Counter()
    for message in messages:
        if isinstance(message, dict) and message.get("category") == category and isinstance(message.get("rule_id"), str):
            counts[str(message["rule_id"])] += 1
    return [{"rule": rule, "count": count} for rule, count in counts.most_common(5)]


def _official_references_for_issues(issues: list[dict[str, object]]) -> list[str]:
    docs: list[str] = []
    for issue in issues:
        refs = issue.get("official_references")
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, str) and ref not in docs:
                    docs.append(ref)
    return docs


def _enrich_issue(issue: dict[str, object]) -> dict[str, object]:
    issue_id = str(issue.get("issue_id") or "")
    issue.setdefault("root_cause_hint", _root_cause_hint(issue_id))
    issue.setdefault("next_tools", _next_tools_for_issue(issue_id))
    issue.setdefault("blocked_flow_stages", _blocked_flow_stages(issue_id))
    return issue


def _root_cause_hint(issue_id: str) -> str:
    hints = {
        "drc.io_standard_missing": "Top-level ports are missing explicit IOSTANDARD constraints.",
        "drc.io_pin_unconstrained": "Top-level ports are missing package pin/LOC constraints or include unused ports.",
        "drc.bitstream_blocker": "Implementation reached a rule that blocks write_bitstream until fixed.",
        "timing.unconstrained_paths": "Clock, generated-clock, IO-delay, XDC order, or exception coverage is incomplete.",
        "clock_interaction.unsafe": "One or more clock pairs have unsafe or undefined timing relationships.",
        "clock_interaction.partial": "Some clock-pair coverage is partial or ignored, so CDC intent may be ambiguous.",
        "timing.setup_failed": "Worst setup paths violate required arrival time; inspect path composition before strategy changes.",
        "timing.path_slack_failed": "A detailed timing path has negative slack; classify logic, routing, clock skew, or constraint cause.",
        "timing.hold_failed": "Hold slack is negative; confirm clocking and IO delays before relying on implementation repair.",
        "timing.pulse_width_failed": "Clock waveform or generated-clock definitions may violate pulse-width requirements.",
        "timing.clock_interaction_issue": "Clock interaction warnings indicate missing or unsafe clock-domain relationships.",
        "methodology.clocking_issue": "Methodology rules point at clock constraints, generated clocks, or CDC structure.",
        "methodology.cdc_issue": "CDC structure or constraints need review before closure attempts.",
        "methodology.reset_issue": "Reset topology, synchronization, or fanout may be harming timing or reliability.",
        "methodology.timing_issue": "Methodology timing rules should be resolved before changing implementation strategy.",
        "utilization.io_pressure": "The design is close to IO capacity; pinout or device/package selection may be the limit.",
        "utilization.clock_buffer_pressure": "Clocking resources are close to capacity; clock topology may need consolidation.",
        "utilization.resource_pressure": "A device resource is close to capacity and can limit placement/timing closure.",
        "power.thermal_risk": "Thermal margin or junction temperature is risky under current activity assumptions.",
        "power.high_total": "Total on-chip power is high enough to affect thermal and implementation decisions.",
        "power.low_confidence": "Power estimates are based on weak activity data and need better simulation/activity input.",
    }
    return hints.get(issue_id, "Inspect the report artifact and related official documentation before rerunning.")


def _next_tools_for_issue(issue_id: str) -> list[str]:
    if issue_id.startswith("drc.io_") or issue_id in {"timing.unconstrained_paths", "timing.pulse_width_failed"}:
        return ["vivado_constraint_diagnostics", "vivado_xdc_order_check", "vivado_report", "vivado_search_official_docs"]
    if issue_id.startswith("clock_interaction") or issue_id == "timing.clock_interaction_issue":
        return ["vivado_report", "vivado_constraint_diagnostics", "vivado_search_official_docs"]
    if issue_id.startswith("timing."):
        return ["vivado_report", "vivado_analyze_reports", "vivado_search_official_docs"]
    if issue_id.startswith("utilization."):
        return ["vivado_report", "vivado_project_summary", "vivado_search_official_docs"]
    if issue_id.startswith("methodology."):
        return ["vivado_report", "vivado_constraint_diagnostics", "vivado_search_official_docs"]
    if issue_id.startswith("power."):
        return ["vivado_report", "vivado_search_official_docs"]
    return ["vivado_report", "vivado_search_official_docs", "vivado_tcl_command_help"]


def _blocked_flow_stages(issue_id: str) -> list[str]:
    if issue_id.startswith("drc.") and issue_id not in {"drc.error"}:
        return ["bitstream"]
    if issue_id.startswith(("timing.", "clock_interaction.", "methodology.")):
        return ["timing_closure", "implementation_signoff"]
    if issue_id.startswith("power.") and issue_id != "power.low_confidence":
        return ["implementation_signoff"]
    if issue_id.startswith("utilization."):
        return ["placement", "implementation_signoff"]
    return []


def _quality_gates(issues: list[dict[str, object]]) -> dict[str, object]:
    issue_ids = {str(issue.get("issue_id") or "") for issue in issues}
    high_ids = {str(issue.get("issue_id") or "") for issue in issues if issue.get("severity") == "high"}
    report_failed = bool({"report.generation_failed", "report.unavailable"} & issue_ids)
    return {
        "constraints_clean": not report_failed
        and not any(issue_id in issue_ids for issue_id in ("timing.unconstrained_paths", "drc.io_standard_missing", "drc.io_pin_unconstrained")),
        "timing_clean": not report_failed and not any(issue_id.startswith(("timing.", "clock_interaction.")) for issue_id in high_ids),
        "drc_clean": not report_failed and not any(issue_id.startswith("drc.") for issue_id in high_ids),
        "power_clean": not report_failed and not any(issue_id.startswith("power.") for issue_id in high_ids),
        "bitstream_ready": not report_failed
        and not any(issue_id.startswith("drc.") or issue_id.startswith("timing.") or issue_id.startswith("clock_interaction.") for issue_id in high_ids),
    }


def _refresh_analysis_rollups(analysis: dict[str, object]) -> None:
    issues = [issue for issue in analysis.get("issues", []) if isinstance(issue, dict)]
    report_failed = any(issue.get("issue_id") in {"report.generation_failed", "report.unavailable"} for issue in issues)
    analysis["ok"] = not report_failed and not any(issue.get("severity") == "high" for issue in issues)
    analysis["summary"] = {
        **(analysis.get("summary") if isinstance(analysis.get("summary"), dict) else {}),
        "issue_count": len(issues),
        "high_count": sum(1 for issue in issues if issue.get("severity") == "high"),
        "medium_count": sum(1 for issue in issues if issue.get("severity") == "medium"),
        "low_count": sum(1 for issue in issues if issue.get("severity") == "low"),
    }
    analysis["quality_gates"] = _quality_gates(issues)
    analysis["next_action_plan"] = _next_action_plan(issues)
    analysis["suggested_next_tools"] = _suggested_next_tools(issues)
    analysis["official_references"] = _official_references_for_issues(issues)


def _next_action_plan(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    plan: list[dict[str, object]] = []
    seen: set[str] = set()
    for issue in issues:
        tools = issue.get("next_tools") if isinstance(issue.get("next_tools"), list) else []
        tool = next((str(tool) for tool in tools if isinstance(tool, str)), "vivado_report")
        if tool in seen:
            continue
        seen.add(tool)
        plan.append(
            {
                "tool": tool,
                "why": issue.get("next_step") or issue.get("root_cause_hint") or "Investigate the highest-priority report issue.",
                "issue_id": issue.get("issue_id"),
                "severity": issue.get("severity"),
            }
        )
        if len(plan) >= 5:
            break
    if not any(row["tool"] == "vivado_search_official_docs" for row in plan):
        plan.append({"tool": "vivado_search_official_docs", "why": "Open the official guidance linked by the highest-priority issues."})
    return plan


def _suggested_next_tools(issues: list[dict[str, object]]) -> list[str]:
    tools: list[str] = []
    for issue in issues:
        for tool in issue.get("next_tools", []) if isinstance(issue.get("next_tools"), list) else []:
            if isinstance(tool, str) and tool not in tools:
                tools.append(tool)
    for tool in ("vivado_report", "vivado_search_official_docs", "vivado_tcl_command_help"):
        if tool not in tools:
            tools.append(tool)
    return tools[:8]


def _utilization_issue_id(resource_class: str) -> str:
    if resource_class == "io":
        return "utilization.io_pressure"
    if resource_class == "clocking":
        return "utilization.clock_buffer_pressure"
    return "utilization.resource_pressure"


def _utilization_next_step(resource_class: str) -> str:
    if resource_class == "io":
        return "Inspect IO utilization, package pinout, unused ports, and whether the selected package has enough IO."
    if resource_class == "clocking":
        return "Inspect clock buffer/MMCM/PLL usage and consolidate generated or regional clocks where possible."
    return "Inspect hierarchical utilization and consider resource sharing, retiming, or device/strategy changes."


def _rule_category(rule: str, message: str) -> str:
    text = f"{rule} {message}".lower()
    if "nstd" in text or "iostandard" in text or "i/o standard" in text:
        return "io_standard_missing"
    if "ucio" in text or "unconstrained logical port" in text or "package_pin" in text:
        return "io_pin_unconstrained"
    if "bitstream" in text or "write_bitstream" in text:
        return "bitstream_blocker"
    if "cdc" in text or "crossing" in text:
        return "cdc"
    if "reset" in text:
        return "reset"
    if "clock" in text or "timing-1" in text or "cdc" in text:
        return "clocking"
    if "timing" in text or "wns" in text or "tns" in text:
        return "timing"
    if "power" in text:
        return "power"
    return "other"


def _severity_field(severity: str) -> str:
    if severity == "ERROR":
        return "errors"
    if severity == "CRITICAL WARNING":
        return "critical_warnings"
    return "warnings"


def _extract_int_label(text: str, label: str) -> int | None:
    match = re.search(rf"\b{re.escape(label)}\b\s*[:=]?\s*([0-9,]+)", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _count_phrase(text: str, phrase: str) -> int:
    return len(re.findall(re.escape(phrase), text, re.IGNORECASE))


def _parse_number(value: str) -> float | None:
    cleaned = value.strip().replace(",", "")
    if not cleaned or cleaned in {"-", "N/A", "n/a"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _infer_available(values: list[float]) -> int:
    if len(values) == 3:
        return int(values[1])
    if len(values) >= 5:
        return int(values[-2])
    return int(values[1])


def _timing_path_sample(text: str) -> dict[str, object]:
    fields: dict[str, object] = {}
    patterns = {
        "startpoint": r"Startpoint\s*:\s*([^\r\n]+)",
        "endpoint": r"Endpoint\s*:\s*([^\r\n]+)",
        "startpoint_clock": r"Startpoint\s+Clock\s*:\s*([^\r\n]+)",
        "endpoint_clock": r"Endpoint\s+Clock\s*:\s*([^\r\n]+)",
        "path_group": r"Path\s+Group\s*:\s*([^\r\n]+)",
        "path_type": r"Path\s+Type\s*:\s*([^\r\n]+)",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            fields[field] = match.group(1).strip()
    return fields


def _float_value(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _int_value(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None
