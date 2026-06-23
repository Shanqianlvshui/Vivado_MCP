from vivado_mcp.tcl_assist import build_tcl_command_help, review_tcl, tcl_command_coverage, tcl_command_doc_topic


def test_server_tcl_command_help_routes_official_search_by_command_topic(monkeypatch) -> None:
    from vivado_mcp import server

    calls = []

    def fake_search_official_docs(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "topic": kwargs["topic"], "results": []}

    monkeypatch.setattr(server, "search_official_docs", fake_search_official_docs)

    result = server.vivado_tcl_command_help(command="create_clock")

    assert result["ok"] is True
    assert result["official_doc_topic"] == "constraints"
    assert result["coverage"]["recommended_tools"] == ["vivado_constraint_diagnostics", "vivado_review_tcl", "vivado_run_tcl"]
    assert calls[0]["topic"] == "constraints"
    assert "doc_id" not in calls[0]


def test_review_tcl_flags_high_risk_commands() -> None:
    result = review_tcl(
        """
        create_project demo ./demo -force
        file delete -force ./old_runs
        program_hw_devices [current_hw_device]
        exit
        """
    )

    assert result["risk_level"] == "critical"
    assert result["requires_expect_destructive"] is True
    assert {"file.delete", "hardware.program", "session.exit"}.issubset({risk["risk_id"] for risk in result["risks"]})
    assert "UG908" in result["recommended_docs"]


def test_review_tcl_flags_nested_and_semicolon_commands() -> None:
    result = review_tcl(
        """
        if {$do_cleanup} { file delete -force ./old_runs }; open_hw_manager
        set fp [open |notepad.exe r]
        reset_project
        delete_bd_objs [get_bd_cells axi_gpio_0]
        """
    )

    risk_ids = {risk["risk_id"] for risk in result["risks"]}
    assert result["risk_level"] == "critical"
    assert result["requires_expect_destructive"] is True
    assert {"file.delete", "external.exec", "project.reset", "delete.objects", "hardware.session"}.issubset(risk_ids)
    assert "UG908" in result["recommended_docs"]


def test_tcl_command_coverage_prefers_structured_tool_for_bd_cell() -> None:
    coverage = tcl_command_coverage("create_bd_cell")

    assert coverage["coverage_status"] == "partial"
    assert "vivado_bd_apply" in coverage["recommended_tools"]
    assert coverage["recommendation"] == "prefer_structured_tool_when_possible"


def test_command_coverage_for_priority_cross_flow_commands() -> None:
    create_clock = tcl_command_coverage("create_clock")
    assert create_clock["coverage_status"] == "raw_tcl"
    assert create_clock["recommended_tools"] == ["vivado_constraint_diagnostics", "vivado_review_tcl", "vivado_run_tcl"]
    assert create_clock["recommendation"] == "use_expert_tcl_with_review"
    assert tcl_command_doc_topic("create_clock") == "constraints"

    launch_runs = tcl_command_coverage("launch_runs")
    assert launch_runs["coverage_status"] == "partial"
    assert "vivado_run_synthesis" in launch_runs["recommended_tools"]
    assert tcl_command_doc_topic("launch_runs") == "build"

    create_ip = tcl_command_coverage("create_ip")
    assert create_ip["coverage_status"] == "raw_tcl"
    assert create_ip["recommended_tools"] == ["vivado_search_official_docs", "vivado_review_tcl", "vivado_run_tcl"]
    assert "No structured MCP IP creation tool" in create_ip["notes"]
    assert tcl_command_doc_topic("create_ip") == "ip"


def test_build_tcl_command_help_combines_docs_vivado_and_coverage() -> None:
    result = build_tcl_command_help(
        command="create_project",
        official_search={
            "ok": True,
            "results": [{"doc_id": "UG835", "snippets": [{"text": "create_project creates a Vivado project."}]}],
        },
        installed_help={"ok": True, "result": "Usage: create_project name dir"},
    )

    assert result["command"] == "create_project"
    assert result["coverage"]["coverage_status"] == "partial"
    assert result["official_doc_topic"] == "project"
    assert result["installed_vivado_help"]["available"] is True
    assert result["official_search"]["results"][0]["doc_id"] == "UG835"


def test_build_tcl_command_help_rejects_empty_command() -> None:
    result = build_tcl_command_help(command="")

    assert result["ok"] is False
    assert result["coverage"]["coverage_status"] == "invalid"
    assert result["recommended_sequence"][0]["step"] == "provide_command"
