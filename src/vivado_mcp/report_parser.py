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

    status = "unknown"
    wns = values.get("wns")
    whs = values.get("whs")
    if wns is not None or whs is not None:
        status = "fail" if (wns is not None and wns < 0) or (whs is not None and whs < 0) else "pass"

    setup = {key: values[key] for key in ("wns", "tns") if key in values}
    hold = {key: values[key] for key in ("whs", "ths") if key in values}
    pulse_width = {key: values[key] for key in ("wpws", "tpws") if key in values}
    coverage = {key: ints[key] for key in ("unconstrained_paths", "unconstrained_clocks", "clock_interaction_warnings") if key in ints}

    return {
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
        "messages": messages[:25],
    }


def parse_power(text: str) -> dict[str, object]:
    fields: dict[str, float] = {}
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
        "suggested_next_tools": ["vivado_report", "vivado_search_official_docs", "vivado_tcl_command_help"],
        "official_references": _official_references_for_issues(issues),
    }


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
        severity = "high" if pct >= 95 else "medium" if pct >= 80 else None
        if severity:
            used = _int_value(row.get("used"))
            available = _int_value(row.get("available"))
            issues.append(
                _issue(
                    "utilization.resource_pressure",
                    severity,
                    report_type,
                    f"{name} utilization is {pct}%"
                    + (f" ({used}/{available})" if used is not None and available is not None else ""),
                    "Inspect hierarchical utilization and consider resource sharing, retiming, or device/strategy changes.",
                    "utilization",
                    ["UG906", "UG949"],
                    ["Vivado report_utilization resource pressure", "UG949 utilization timing closure resource sharing"],
                    resource=name,
                    resource_class=row.get("resource_class"),
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
        ("clocking", "methodology.clocking_issue", "medium", "Review clock definitions, generated clocks, clock groups, and clock-domain crossings.", ["UG906", "UG903", "UG949", "UG1292"], ["Vivado methodology TIMING clocking issue"]),
        ("timing", "methodology.timing_issue", "medium", "Review methodology timing rules before changing implementation strategy.", ["UG906", "UG949", "UG1292"], ["Vivado methodology timing rule report"]),
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
        "drc.error": 0,
        "report.error": 0,
        "timing.unconstrained_paths": 1,
        "timing.setup_failed": 2,
        "timing.hold_failed": 3,
        "timing.clock_interaction_issue": 4,
        "methodology.clocking_issue": 5,
        "methodology.timing_issue": 6,
        "methodology.critical_warning": 7,
        "utilization.resource_pressure": 8,
        "power.thermal_risk": 9,
        "power.high_total": 10,
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


def _rule_category(rule: str, message: str) -> str:
    text = f"{rule} {message}".lower()
    if "nstd" in text or "iostandard" in text or "i/o standard" in text:
        return "io_standard_missing"
    if "ucio" in text or "unconstrained logical port" in text or "package_pin" in text:
        return "io_pin_unconstrained"
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


def _float_value(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _int_value(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None
