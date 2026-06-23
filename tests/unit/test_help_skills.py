from vivado_mcp.help_skills import get_skill, help_topic, list_skills, skills_index, suggest_next_steps
import vivado_mcp.official_docs as official_docs
from vivado_mcp.official_docs import (
    DEFAULT_LOCAL_DOCS_ROOT,
    get_official_reference,
    list_official_references,
    official_docs_index,
    search_official_docs,
)


def test_lists_builtin_skills() -> None:
    skills = list_skills()
    assert {skill["skill_id"] for skill in skills} == {
        "gui-session",
        "project-build-flow",
        "block-design-flow",
        "fileset-constraint-flow",
        "official-docs-reference",
        "raw-tcl-expert",
    }


def test_reads_skill_body() -> None:
    skill = get_skill("raw-tcl-expert")
    assert skill["resource_uri"] == "vivado://skills/raw-tcl-expert"
    assert "Raw Tcl" in skill["body"]


def test_help_topic_points_to_skill() -> None:
    help_result = help_topic("gui_session")
    assert help_result["related_resources"] == ["vivado://skills/gui-session"]

    bd_help = help_topic("bd")
    assert bd_help["related_resources"] == ["vivado://skills/block-design-flow"]

    ip_help = help_topic("ip")
    assert "vivado_ip_catalog_search" in ip_help["recommended_tools"]
    assert "vivado_create_ip" in ip_help["recommended_tools"]
    assert "vivado_ip_upgrade_check" in ip_help["recommended_tools"]
    assert "vivado_upgrade_ip" in ip_help["recommended_tools"]

    sim_help = help_topic("simulation")
    assert "vivado_simulation_audit" in sim_help["recommended_tools"]
    assert "vivado_prepare_simulation" in sim_help["recommended_tools"]
    assert "vivado_launch_simulation" in sim_help["recommended_tools"]
    assert "vivado_analyze_xsim_logs" in sim_help["recommended_tools"]

    nonproject_help = help_topic("non-project")
    assert "vivado_nonproject_read_sources" in nonproject_help["recommended_tools"]
    assert "vivado_nonproject_synth_design" in nonproject_help["recommended_tools"]
    assert "vivado_nonproject_route_design" in nonproject_help["recommended_tools"]

    hw_help = help_topic("hardware")
    assert "vivado_hw_discover" in hw_help["recommended_tools"]
    assert "vivado_search_official_docs" in hw_help["recommended_tools"]

    docs_help = help_topic("official_docs")
    assert "vivado_list_official_references" in docs_help["recommended_tools"]
    assert "vivado_search_official_docs" in docs_help["recommended_tools"]
    assert "vivado://official-docs/index" in docs_help["related_resources"]

    tcl_help = help_topic("raw-tcl")
    assert "vivado_tcl_command_help" in tcl_help["recommended_tools"]
    assert "vivado_review_tcl" in tcl_help["recommended_tools"]
    assert "vivado_capture_state" in tcl_help["recommended_tools"]
    assert "vivado_state_diff" in tcl_help["recommended_tools"]

    project_help = help_topic("project")
    assert "vivado_capture_state" in project_help["recommended_tools"]
    assert "vivado_source_audit" in project_help["recommended_tools"]
    assert "vivado_analyze_reports" in project_help["recommended_tools"]
    assert "vivado_state_diff" in project_help["recommended_tools"]

    fileset_help = help_topic("xdc")
    assert fileset_help["related_resources"] == ["vivado://skills/fileset-constraint-flow"]
    assert "vivado_source_audit" in fileset_help["recommended_tools"]
    assert "vivado_fileset_apply" in fileset_help["recommended_tools"]
    assert "vivado_constraint_set_apply" in fileset_help["recommended_tools"]
    assert "vivado_xdc_order_check" in fileset_help["recommended_tools"]

    report_help = help_topic("timing")
    assert "vivado_analyze_reports" in report_help["recommended_tools"]
    assert "vivado://official-docs/index" in report_help["related_resources"]


def test_suggest_next_steps_routes_fileset_and_constraint_work() -> None:
    result = suggest_next_steps(goal="fix XDC order and set top/include dirs", has_session=True, has_project=True)
    tools = [row["tool"] for row in result["recommendations"]]

    assert tools[:3] == ["vivado_source_audit", "vivado_list_filesets", "vivado_describe_fileset"]
    assert "vivado_constraint_set_apply" in tools
    assert result["related_resources"] == ["vivado://skills/fileset-constraint-flow"]


def test_suggest_next_steps_routes_report_diagnostics() -> None:
    result = suggest_next_steps(goal="timing failed with negative WNS and DRC errors", has_session=True, has_project=True)
    tools = [row["tool"] for row in result["recommendations"]]

    assert tools[0] == "vivado_analyze_reports"
    assert "vivado_search_official_docs" in tools
    assert "vivado://official-docs/index" in result["related_resources"]


def test_suggest_next_steps_routes_ip_work() -> None:
    result = suggest_next_steps(goal="create_ip axi_gpio and generate IP output products", has_session=True, has_project=True)
    tools = [row["tool"] for row in result["recommendations"]]

    assert tools[0] == "vivado_ip_catalog_search"
    assert "vivado_create_ip" in tools
    assert "vivado_ip_upgrade_check" in tools
    assert "vivado_generate_ip_outputs" in tools


def test_suggest_next_steps_routes_simulation_work() -> None:
    result = suggest_next_steps(goal="launch_simulation fails in xelab for testbench sim_1", has_session=True, has_project=True)
    tools = [row["tool"] for row in result["recommendations"]]

    assert tools[:4] == ["vivado_simulation_audit", "vivado_prepare_simulation", "vivado_launch_simulation", "vivado_analyze_xsim_logs"]
    assert "vivado_search_official_docs" in tools


def test_suggest_next_steps_routes_nonproject_work() -> None:
    result = suggest_next_steps(goal="non-project read_verilog synth_design route_design", has_session=True, has_project=False)
    tools = [row["tool"] for row in result["recommendations"]]

    assert tools[:2] == ["vivado_nonproject_read_sources", "vivado_nonproject_synth_design"]
    assert "vivado_nonproject_route_design" in tools


def test_suggest_next_steps_routes_hardware_readonly_work() -> None:
    result = suggest_next_steps(goal="connect_hw_server and get_hw_devices", has_session=True, has_project=False)
    tools = [row["tool"] for row in result["recommendations"]]

    assert tools[0] == "vivado_hw_discover"
    assert "vivado_review_tcl" in tools
    assert "vivado_search_official_docs" in tools


def test_suggest_next_steps_routes_hardware_programming_to_review() -> None:
    result = suggest_next_steps(goal="program_hw_devices with a bitstream", has_session=True, has_project=True)
    tools = [row["tool"] for row in result["recommendations"]]

    assert tools[0] == "vivado_review_tcl"
    assert "vivado_hw_discover" in tools


def test_skills_index_contains_resource_uris() -> None:
    index = skills_index()
    assert "vivado://skills/project-build-flow" in index
    assert "vivado://skills/block-design-flow" in index


def test_official_references_cover_core_tcl_and_bd_docs() -> None:
    tcl_docs = {doc["doc_id"] for doc in list_official_references(topic="tcl")}
    bd_docs = {doc["doc_id"] for doc in list_official_references(topic="bd")}
    all_docs = {doc["doc_id"] for doc in list_official_references()}

    assert {"UG835", "UG894", "UG893"}.issubset(tcl_docs)
    assert {"UG835", "UG994", "UG912"}.issubset(bd_docs)
    assert {"UG899", "UG949", "UG1292", "UG973", "UG911", "UG953", "UG974", "UG1046"}.issubset(all_docs)

    ug835 = get_official_reference("ug835")
    assert ug835["resource_uri"] == "vivado://official-docs/ug835"
    assert ug835["url"].startswith("https://docs.amd.com/")
    assert ug835["local_docs_root"] == DEFAULT_LOCAL_DOCS_ROOT
    assert rf"{DEFAULT_LOCAL_DOCS_ROOT}\ug835.pdf" in ug835["local_path_candidates"]

    index = official_docs_index()
    assert "Vivado Official References" in index
    assert "UG835" in index
    assert DEFAULT_LOCAL_DOCS_ROOT in index


def test_search_official_docs_returns_local_snippets(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIVADO_MCP_DOCS_ROOT", str(tmp_path))
    (tmp_path / "ug835.pdf").write_bytes(b"%PDF fake")
    monkeypatch.setattr(
        official_docs,
        "_read_document_text",
        lambda path, timeout_seconds=120: "The create_bd_cell command creates block design cells. Use the -type ip option.",
    )

    result = search_official_docs("create_bd_cell", doc_id="ug835")

    assert result["ok"] is True
    assert result["query"] == "create_bd_cell"
    assert result["results"][0]["doc_id"] == "UG835"
    assert "create_bd_cell" in result["results"][0]["snippets"][0]["text"]
