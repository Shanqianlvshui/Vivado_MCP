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

    launch_simulation = tcl_command_coverage("launch_simulation")
    assert launch_simulation["coverage_status"] == "covered"
    assert launch_simulation["recommended_tools"] == [
        "vivado_prepare_simulation",
        "vivado_launch_simulation",
        "vivado_analyze_xsim_logs",
    ]
    assert tcl_command_doc_topic("launch_simulation") == "simulation"

    read_verilog = tcl_command_coverage("read_verilog")
    assert read_verilog["coverage_status"] == "covered"
    assert read_verilog["recommended_tools"] == ["vivado_nonproject_read_sources"]
    assert tcl_command_doc_topic("read_xdc") == "build"

    synth_design = tcl_command_coverage("synth_design")
    assert synth_design["coverage_status"] == "covered"
    assert synth_design["recommended_tools"] == ["vivado_nonproject_synth_design"]

    route_design = tcl_command_coverage("route_design")
    assert route_design["coverage_status"] == "covered"
    assert route_design["recommended_tools"] == ["vivado_nonproject_route_design"]

    write_checkpoint = tcl_command_coverage("write_checkpoint")
    assert "vivado_nonproject_route_design" in write_checkpoint["recommended_tools"]

    create_ip = tcl_command_coverage("create_ip")
    assert create_ip["coverage_status"] == "covered"
    assert create_ip["recommended_tools"] == ["vivado_create_ip", "vivado_ip_catalog_search"]
    assert tcl_command_doc_topic("create_ip") == "ip"

    upgrade_ip = tcl_command_coverage("upgrade_ip")
    assert upgrade_ip["coverage_status"] == "covered"
    assert upgrade_ip["recommended_tools"] == ["vivado_upgrade_ip", "vivado_describe_ip"]

    generate_target = tcl_command_coverage("generate_target")
    assert "vivado_generate_ip_outputs" in generate_target["recommended_tools"]

    open_hw = tcl_command_coverage("open_hw_manager")
    assert open_hw["coverage_status"] == "covered"
    assert open_hw["recommended_tools"] == ["vivado_hw_discover"]
    assert tcl_command_doc_topic("get_hw_devices") == "hardware"

    refresh_hw = tcl_command_coverage("refresh_hw_device")
    assert refresh_hw["coverage_status"] == "partial"
    assert refresh_hw["recommended_tools"] == ["vivado_hw_discover", "vivado_review_tcl"]

    program = tcl_command_coverage("program_hw_devices")
    assert program["coverage_status"] == "raw_tcl"
    assert "vivado_review_tcl" in program["recommended_tools"]


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
