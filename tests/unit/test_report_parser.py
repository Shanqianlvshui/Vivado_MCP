from vivado_mcp.report_parser import analyze_report_summaries, parse_messages, parse_power, parse_timing, parse_utilization


def test_parse_timing_extracts_wns_and_status() -> None:
    summary = parse_timing(
        "\n".join(
            [
                "WNS(ns) -0.125",
                "TNS(ns) -1.250",
                "WHS(ns) -0.030",
                "THS(ns) -0.090",
                "Failing Endpoints: 4",
                "Unconstrained Paths: 3",
                "Unconstrained Clocks: 1",
                "Clock Interaction Warnings: 2",
            ]
        )
    )
    assert summary["parsed"] is True
    assert summary["status"] == "fail"
    assert summary["wns"] == -0.125
    assert summary["tns"] == -1.25
    assert summary["whs"] == -0.03
    assert summary["setup"]["wns"] == -0.125
    assert summary["hold"]["whs"] == -0.03
    assert summary["failing_endpoints"] == 4
    assert summary["unconstrained_paths"] == 3
    assert summary["unconstrained_clocks"] == 1
    assert summary["clock_interaction_warnings"] == 2


def test_parse_utilization_extracts_table_row() -> None:
    summary = parse_utilization("| CLB LUTs | 1,234 | 10,000 | 12.34 |\n| DSPs | 95 | 0 | 0 | 100 | 95.0 |")
    assert summary["parsed"] is True
    assert summary["resources"]["clb_luts"]["used"] == 1234
    assert summary["resources"]["clb_luts"]["utilization_percent"] == 12.34
    assert summary["resources"]["dsps"]["available"] == 100
    assert summary["resources"]["dsps"]["resource_class"] == "dsp"


def test_parse_messages_counts_vivado_messages() -> None:
    summary = parse_messages(
        "ERROR: [DRC NSTD-1] Unspecified I/O Standard\n"
        "ERROR: [DRC UCIO-1] Unconstrained Logical Port\n"
        "CRITICAL WARNING: [METHODOLOGY TIMING-1] Review clocks\n"
        "WARNING: [C 3] generic warning\n"
    )
    assert summary["errors"] == 2
    assert summary["critical_warnings"] == 1
    assert summary["warnings"] == 1
    assert summary["rules"]["DRC NSTD-1"]["errors"] == 1
    assert summary["rules"]["DRC UCIO-1"]["errors"] == 1
    assert summary["rules"]["METHODOLOGY TIMING-1"]["critical_warnings"] == 1
    assert summary["rules"]["METHODOLOGY TIMING-1"]["warnings"] == 0
    assert summary["rules"]["C 3"]["warnings"] == 1
    assert summary["rule_categories"]["io_standard_missing"] == 1
    assert summary["rule_categories"]["io_pin_unconstrained"] == 1
    assert summary["rule_categories"]["clocking"] == 1
    assert summary["messages"][0]["rule_id"] == "DRC NSTD-1"


def test_parse_power_extracts_totals() -> None:
    summary = parse_power(
        "Total On-Chip Power (W) 3.210\n"
        "Dynamic (W) 2.100\n"
        "Device Static (W) 1.110\n"
        "Junction Temperature (C) 76.5\n"
        "Thermal Margin (C) 8.0\n"
    )

    assert summary["parsed"] is True
    assert summary["total_on_chip_power_w"] == 3.21
    assert summary["dynamic_power_w"] == 2.1
    assert summary["static_power_w"] == 1.11
    assert summary["junction_temperature_c"] == 76.5
    assert summary["thermal_margin_c"] == 8.0


def test_analyze_report_summaries_emits_structured_issue_taxonomy() -> None:
    analysis = analyze_report_summaries(
        {
            "timing_summary": parse_timing(
                "WNS(ns) -0.500\nTNS(ns) -10.0\nWHS(ns) -0.050\nTHS(ns) -0.5\n"
                "Failing Endpoints: 12\nUnconstrained Paths: 2\nClock Interaction Warnings: 1\n"
            ),
            "utilization": parse_utilization("| DSPs | 95 | 100 | 95.0 |"),
            "drc": parse_messages("ERROR: [DRC NSTD-1] Unspecified I/O Standard\n"),
            "methodology": parse_messages(
                "CRITICAL WARNING: [METHODOLOGY TIMING-1] Review generated clocks\n",
                report_type="methodology",
            ),
            "power": parse_power(
                "Total On-Chip Power (W) 7.500\nDynamic (W) 6.000\nDevice Static (W) 1.500\n"
                "Junction Temperature (C) 86.0\nThermal Margin (C) 4.0\n"
            ),
        }
    )

    issue_ids = [issue["issue_id"] for issue in analysis["issues"]]
    assert analysis["ok"] is False
    assert issue_ids[:3] == ["drc.io_standard_missing", "timing.unconstrained_paths", "timing.setup_failed"]
    assert "timing.hold_failed" in issue_ids
    assert "timing.clock_interaction_issue" in issue_ids
    assert "utilization.resource_pressure" in issue_ids
    assert "methodology.clocking_issue" in issue_ids
    assert "power.thermal_risk" in issue_ids
    assert "power.high_total" in issue_ids
    assert analysis["issues"][0]["official_doc_queries"]
    assert "vivado_report" in analysis["suggested_next_tools"]
    assert "UG906" in analysis["official_references"]
    assert "UG907" in analysis["official_references"]


def test_analyze_report_summaries_prioritizes_actionable_findings() -> None:
    analysis = analyze_report_summaries(
        {
            "timing_summary": parse_timing("WNS(ns) -0.500\nTNS(ns) -10.0\nFailing Endpoints: 12\n"),
            "utilization": parse_utilization("| DSPs | 95 | 100 | 95.0 |"),
            "drc": parse_messages("ERROR: [DRC UCIO-1] Unconstrained Logical Port\n"),
            "power": parse_power("Total On-Chip Power (W) 7.500\nDynamic (W) 6.000\nDevice Static (W) 1.500\n"),
        }
    )

    issue_ids = [issue["issue_id"] for issue in analysis["issues"]]
    assert analysis["ok"] is False
    assert issue_ids[:2] == ["drc.io_pin_unconstrained", "timing.setup_failed"]
    assert "utilization.resource_pressure" in issue_ids
    assert "power.high_total" in issue_ids
    assert "vivado_report" in analysis["suggested_next_tools"]
    assert "UG906" in analysis["official_references"]
