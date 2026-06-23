from __future__ import annotations

from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class Skill:
    skill_id: str
    title: str
    summary: str
    filename: str

    @property
    def resource_uri(self) -> str:
        return f"vivado://skills/{self.skill_id}"


SKILLS: tuple[Skill, ...] = (
    Skill(
        skill_id="gui-session",
        title="GUI Session",
        summary="Start Vivado through MCP, open the GUI, and keep AI actions in the same session.",
        filename="gui-session.md",
    ),
    Skill(
        skill_id="project-build-flow",
        title="Project Build Flow",
        summary="Create/open a project, add files, run synthesis/implementation, and inspect reports.",
        filename="project-build-flow.md",
    ),
    Skill(
        skill_id="block-design-flow",
        title="Block Design Flow",
        summary="Create, inspect, validate, and generate generic Vivado IP Integrator block designs.",
        filename="block-design-flow.md",
    ),
    Skill(
        skill_id="fileset-constraint-flow",
        title="Fileset, Source, and Constraint Workflow",
        summary="Manage Vivado filesets, source properties, top module, and XDC loading order before complex builds.",
        filename="fileset-constraint-flow.md",
    ),
    Skill(
        skill_id="official-docs-reference",
        title="Official Docs Reference",
        summary="Use packaged AMD official Vivado documentation metadata as the authority layer for AI guidance.",
        filename="official-docs-reference.md",
    ),
    Skill(
        skill_id="raw-tcl-expert",
        title="Raw Tcl Expert Mode",
        summary="Use trusted-local raw Tcl for full Vivado freedom with command/result artifacts.",
        filename="raw-tcl-expert.md",
    ),
)


def list_skills(query: str | None = None) -> list[dict[str, str]]:
    needle = (query or "").strip().lower()
    rows = []
    for skill in SKILLS:
        haystack = f"{skill.skill_id} {skill.title} {skill.summary}".lower()
        if needle and needle not in haystack:
            continue
        rows.append(
            {
                "skill_id": skill.skill_id,
                "title": skill.title,
                "summary": skill.summary,
                "resource_uri": skill.resource_uri,
            }
        )
    return rows


def get_skill(skill_id: str) -> dict[str, str]:
    skill = _find_skill(skill_id)
    body = _read_skill_file(skill.filename)
    return {
        "skill_id": skill.skill_id,
        "title": skill.title,
        "summary": skill.summary,
        "resource_uri": skill.resource_uri,
        "body": body,
    }


def skills_index() -> str:
    lines = ["# Vivado MCP Skills", ""]
    for skill in SKILLS:
        lines.append(f"- `{skill.skill_id}`: {skill.summary} ({skill.resource_uri})")
    return "\n".join(lines) + "\n"


def help_topic(topic: str | None = None) -> dict[str, object]:
    normalized = (topic or "index").strip().lower().replace("_", "-")
    if normalized in {"index", "help"}:
        return {
            "topic": "index",
            "summary": "Vivado MCP exposes GUI sessions, project workflow tools, raw Tcl expert mode, and built-in skills.",
            "recommended_tools": ["vivado_list_skills", "vivado_get_skill", "vivado_check_installation"],
            "related_resources": ["vivado://skills/index"],
        }
    if normalized in {"gui", "gui-session", "session"}:
        return {
            "topic": "gui_session",
            "summary": "Start a managed Vivado Tcl session with `open_gui=true`, verify `gui.visible` without stealing focus, and focus the window only when requested.",
            "recommended_tools": ["vivado_check_installation", "vivado_start_session", "vivado_session_state", "vivado_focus_gui"],
            "related_resources": ["vivado://skills/gui-session"],
        }
    if normalized in {"project", "project-flow", "project-build-flow", "build"}:
        return {
            "topic": "project_flow",
            "summary": "Use project workflow tools for repeatable Vivado operations before falling back to raw Tcl.",
            "recommended_tools": [
                "vivado_create_project",
                "vivado_capture_state",
                "vivado_source_audit",
                "vivado_add_sources",
                "vivado_fileset_apply",
                "vivado_constraint_set_apply",
                "vivado_xdc_order_check",
                "vivado_state_diff",
                "vivado_run_synthesis",
                "vivado_analyze_reports",
                "vivado_report",
            ],
            "related_resources": ["vivado://skills/project-build-flow"],
        }
    if normalized in {"bd", "block-design", "block-design-flow", "ip-integrator", "ipi"}:
        return {
            "topic": "block_design_flow",
            "summary": "Use generic IP Integrator tools to create/open BD designs, apply actions, validate, summarize, and generate wrapper outputs.",
            "recommended_tools": [
                "vivado_bd_open_or_create",
                "vivado_bd_apply",
                "vivado_bd_summary",
                "vivado_bd_validate",
                "vivado_bd_generate",
            ],
            "related_resources": ["vivado://skills/block-design-flow"],
        }
    if normalized in {"ip", "ips", "ip-catalog", "xci", "create-ip", "upgrade-ip", "output-products"}:
        return {
            "topic": "ip_flow",
            "summary": "Search the Vivado IP catalog, create project IP, inspect .xci state, upgrade IP explicitly, and generate output products with structured tools.",
            "recommended_tools": [
                "vivado_ip_catalog_search",
                "vivado_create_ip",
                "vivado_list_ips",
                "vivado_describe_ip",
                "vivado_upgrade_ip",
                "vivado_generate_ip_outputs",
                "vivado_search_official_docs",
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if normalized in {"simulation", "sim", "xsim", "launch-simulation", "testbench", "testbench-fileset"}:
        return {
            "topic": "simulation_flow",
            "summary": "Prepare simulation filesets, launch Vivado simulation, and parse xsim/xelab/xvlog logs for actionable compile/elaboration/runtime diagnostics.",
            "recommended_tools": [
                "vivado_prepare_simulation",
                "vivado_launch_simulation",
                "vivado_analyze_xsim_logs",
                "vivado_describe_fileset",
                "vivado_search_official_docs",
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if normalized in {"non-project", "nonproject", "non-project-flow", "read-verilog", "synth-design", "opt-design", "place-design", "route-design"}:
        return {
            "topic": "nonproject_flow",
            "summary": "Run Vivado Non-project Mode flows by reading RTL/XDC, executing synth/opt/place/route steps, and writing checkpoints and reports as session artifacts.",
            "recommended_tools": [
                "vivado_nonproject_read_sources",
                "vivado_nonproject_synth_design",
                "vivado_nonproject_opt_design",
                "vivado_nonproject_place_design",
                "vivado_nonproject_route_design",
                "vivado_analyze_reports",
                "vivado_search_official_docs",
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if normalized in {"hardware", "hw", "hw-manager", "hardware-manager", "hw-server", "device", "devices"}:
        return {
            "topic": "hardware_discovery",
            "summary": "Use read-only hardware discovery to connect to hw_server, enumerate hardware targets/devices, and capture summary artifacts. Device programming is not covered by a structured tool.",
            "recommended_tools": [
                "vivado_hw_discover",
                "vivado_review_tcl",
                "vivado_tcl_command_help",
                "vivado_search_official_docs",
            ],
            "related_resources": ["vivado://official-docs/index", "vivado://skills/raw-tcl-expert"],
        }
    if normalized in {
        "fileset",
        "filesets",
        "source",
        "sources",
        "constraint",
        "constraints",
        "xdc",
        "fileset-constraint",
        "fileset-constraint-flow",
        "constraint-flow",
        "source-flow",
    }:
        return {
            "topic": "fileset_constraint_flow",
            "summary": "Audit and manage Vivado filesets, source settings, top module, constraint sets, and XDC loading order with structured tools before expert Tcl.",
            "recommended_tools": [
                "vivado_source_audit",
                "vivado_list_filesets",
                "vivado_describe_fileset",
                "vivado_fileset_apply",
                "vivado_constraint_set_apply",
                "vivado_xdc_order_check",
                "vivado_constraint_diagnostics",
            ],
            "related_resources": ["vivado://skills/fileset-constraint-flow"],
        }
    if normalized in {"report", "reports", "timing", "timing-closure", "utilization", "drc", "power", "methodology"}:
        return {
            "topic": "report_diagnostics",
            "summary": "Generate common Vivado reports and analyze timing, utilization, DRC, power, and methodology findings before choosing the next closure action.",
            "recommended_tools": [
                "vivado_analyze_reports",
                "vivado_report",
                "vivado_search_official_docs",
                "vivado_tcl_command_help",
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if normalized in {"raw-tcl", "tcl", "expert"}:
        return {
            "topic": "raw_tcl",
            "summary": "Raw Tcl is available in trusted-local/unrestricted profiles and can do anything Vivado Tcl can do.",
            "recommended_tools": [
                "vivado_tcl_command_help",
                "vivado_review_tcl",
                "vivado_capture_state",
                "vivado_session_state",
                "vivado_run_tcl",
                "vivado_source_tcl",
                "vivado_state_diff",
            ],
            "related_resources": ["vivado://skills/raw-tcl-expert"],
        }
    if normalized in {"official-docs", "official-docs-reference", "official-docs-index", "official-docs-guide", "official-docs-catalog", "official-docs-catalogue", "official", "reference", "docs", "manuals"}:
        return {
            "topic": "official_docs",
            "summary": "Use the packaged AMD official Vivado documentation catalog and topic guides before designing Tcl or workflow-level MCP actions.",
            "recommended_tools": [
                "vivado_official_reference_guide",
                "vivado_search_official_docs",
                "vivado_sync_official_docs",
                "vivado_download_xilinx_pdf",
                "vivado_list_official_references",
                "vivado_get_official_reference",
            ],
            "related_resources": ["vivado://official-docs/index", "vivado://skills/official-docs-reference"],
        }
    return {
        "topic": normalized,
        "summary": "Unknown help topic. Use `vivado_list_skills` to discover available tutorials.",
        "recommended_tools": ["vivado_list_skills"],
        "related_resources": ["vivado://skills/index"],
    }


def suggest_next_steps(
    *,
    goal: str | None = None,
    last_error: str | None = None,
    has_session: bool = False,
    has_project: bool = False,
) -> dict[str, object]:
    text = f"{goal or ''} {last_error or ''}".lower()
    if any(word in text for word in ("official", "manual", "docs", "documentation", "ug835", "ug894", "reference")):
        return {
            "recommendations": [
                {"tool": "vivado_official_reference_guide", "why": "Choose the official AMD documents that apply to the requested Vivado task."},
                {"tool": "vivado_search_official_docs", "why": "Search local official PDFs for exact commands, options, and short supporting snippets."},
                {"tool": "vivado_sync_official_docs", "why": "Populate or refresh the local official Vivado PDF library when files are missing."},
                {"tool": "vivado_list_official_references", "why": "Search the packaged official-document catalog by topic or keyword."},
            ],
            "related_resources": ["vivado://official-docs/index", "vivado://skills/official-docs-reference"],
        }
    if any(
        word in text
        for word in (
            "create_ip",
            "upgrade_ip",
            "get_ips",
            "xci",
            "ip catalog",
            "ip output",
            "output product",
            "output products",
            "vlnv",
            "axi_gpio",
        )
    ):
        return {
            "recommendations": [
                {"tool": "vivado_ip_catalog_search", "why": "Find the exact VLNV and IP catalog metadata before creating IP."},
                {"tool": "vivado_create_ip", "why": "Create project IP with path validation, CONFIG properties, and optional state diff."},
                {"tool": "vivado_list_ips", "why": "Inspect project IP instances, .xci paths, lock state, upgrade state, and generation state."},
                {"tool": "vivado_describe_ip", "why": "Inspect one IP instance's VLNV, CONFIG properties, and generated targets."},
                {"tool": "vivado_generate_ip_outputs", "why": "Generate IP output products through a structured auditable tool."},
                {"tool": "vivado_upgrade_ip", "why": "Upgrade IP only when .xci mutation is explicitly confirmed with expect_upgrade=true."},
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if any(
        word in text
        for word in (
            "simulation",
            "simulate",
            "launch_simulation",
            "xsim",
            "xelab",
            "xvlog",
            "xvhdl",
            "testbench",
            "test bench",
            "sim_1",
        )
    ):
        return {
            "recommendations": [
                {"tool": "vivado_prepare_simulation", "why": "Create or update the simulation fileset with testbench files, top, include directories, defines, and library."},
                {"tool": "vivado_launch_simulation", "why": "Launch Vivado simulation and collect structured log paths for xsim/xelab/xvlog/xvhdl outputs."},
                {"tool": "vivado_analyze_xsim_logs", "why": "Parse simulation logs into severity counts, categories, and first actionable diagnostics."},
                {"tool": "vivado_describe_fileset", "why": "Inspect the simulation fileset when compile order, library, or top selection looks wrong."},
                {"tool": "vivado_search_official_docs", "why": "Use UG900/UG835/UG896 guidance for simulation modes, scripts, and IP simulation models."},
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if any(
        word in text
        for word in (
            "non-project",
            "nonproject",
            "read_verilog",
            "read_vhdl",
            "read_xdc",
            "synth_design",
            "opt_design",
            "place_design",
            "route_design",
            "write_checkpoint",
        )
    ):
        return {
            "recommendations": [
                {"tool": "vivado_nonproject_read_sources", "why": "Read RTL and XDC files under path policy before running Non-project Mode steps."},
                {"tool": "vivado_nonproject_synth_design", "why": "Run synth_design with explicit top/part and optional checkpoint/reports."},
                {"tool": "vivado_nonproject_opt_design", "why": "Run opt_design and save an intermediate checkpoint when implementation continues."},
                {"tool": "vivado_nonproject_place_design", "why": "Run place_design with timing/utilization/DRC reports for placement diagnostics."},
                {"tool": "vivado_nonproject_route_design", "why": "Run route_design and collect final timing, utilization, DRC, power, and methodology reports."},
                {"tool": "vivado_search_official_docs", "why": "Use UG892/UG894/UG901/UG904/UG906 guidance for Non-project Mode scripts and reports."},
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if any(
        word in text
        for word in (
            "hardware",
            "hw_server",
            "hw server",
            "open_hw_manager",
            "connect_hw_server",
            "open_hw_target",
            "refresh_hw_device",
            "get_hw_devices",
            "get_hw_targets",
            "program_hw_devices",
            "write_cfgmem",
            "boot_hw_device",
            "device programming",
            "ila",
            "vio",
        )
    ):
        programming = any(word in text for word in ("program_hw_devices", "write_cfgmem", "boot_hw_device", "device programming"))
        if programming:
            recommendations = [
                {"tool": "vivado_review_tcl", "why": "Review programming or boot Tcl before any expert execution; these operations require expect_destructive=true."},
                {"tool": "vivado_search_official_docs", "why": "Use UG908/UG835 for hardware programming syntax, sequence, and risk checks."},
                {"tool": "vivado_tcl_command_help", "why": "Check command coverage and installed Vivado help for the exact hardware command."},
                {"tool": "vivado_hw_discover", "why": "Use only for read-only target/device discovery before deciding whether expert Tcl is needed."},
            ]
        else:
            recommendations = [
                {"tool": "vivado_hw_discover", "why": "Connect to hw_server and list targets/devices through the read-only structured tool with expect_hardware_access=true."},
                {"tool": "vivado_review_tcl", "why": "Review any custom Hardware Manager Tcl before expert execution."},
                {"tool": "vivado_tcl_command_help", "why": "Check coverage, current Vivado help, and official-doc routing for hardware Tcl commands."},
                {"tool": "vivado_search_official_docs", "why": "Use UG908/UG835 when discovery requires custom target or debug Tcl."},
            ]
        return {
            "recommendations": recommendations,
            "related_resources": ["vivado://official-docs/index", "vivado://skills/raw-tcl-expert"],
        }
    if any(
        word in text
        for word in (
            "fileset",
            "filesets",
            "constraint",
            "constraints",
            "xdc",
            "top",
            "include dir",
            "include_dirs",
            "define",
            "defines",
            "library",
            "used_in",
            "used in",
        )
    ):
        return {
            "recommendations": [
                {"tool": "vivado_source_audit", "why": "Audit top module, duplicate files, source/constraint scope, and missing clock markers before changing project state."},
                {"tool": "vivado_list_filesets", "why": "List source, simulation, and constraint sets with file counts, top values, and USED_IN flags."},
                {"tool": "vivado_describe_fileset", "why": "Inspect the specific fileset files, libraries, properties, and processing order."},
                {"tool": "vivado_fileset_apply", "why": "Set include directories, defines, top module, and fileset properties through a structured tool."},
                {"tool": "vivado_constraint_set_apply", "why": "Create/update constraint sets, add/remove/reorder XDC files, and set USED_IN scopes through a structured tool."},
                {"tool": "vivado_xdc_order_check", "why": "Check XDC order and flag exception/input/output constraints that appear before clock definitions."},
                {"tool": "vivado_constraint_diagnostics", "why": "Collect raw constraint fileset diagnostics and XDC command markers for deeper review."},
            ],
            "related_resources": ["vivado://skills/fileset-constraint-flow"],
        }
    if any(
        word in text
        for word in (
            "report",
            "timing",
            "wns",
            "tns",
            "utilization",
            "drc",
            "methodology",
            "power",
            "closure",
            "critical warning",
        )
    ):
        return {
            "recommendations": [
                {"tool": "vivado_analyze_reports", "why": "Generate common reports and rank timing, utilization, DRC, power, and methodology findings."},
                {"tool": "vivado_report", "why": "Generate a specific report when the analysis points at one area."},
                {"tool": "vivado_search_official_docs", "why": "Use UG906/UG949/UG1292/UG907 guidance for the reported failure mode."},
                {"tool": "vivado_tcl_command_help", "why": "Check exact report command syntax before custom report Tcl."},
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if "tcl" in text:
        return {
            "recommendations": [
                {"tool": "vivado_tcl_command_help", "why": "Check official docs, current Vivado help, and MCP structured-tool coverage before writing Tcl."},
                {"tool": "vivado_review_tcl", "why": "Review high-risk Tcl before expert execution."},
                {"tool": "vivado_capture_state", "why": "Capture state before risky Tcl, or pass capture_diff=true when executing."},
                {"tool": "vivado_session_state", "why": "Confirm the managed session is idle before raw Tcl."},
                {"tool": "vivado_run_tcl", "why": "Run a small Tcl probe or mutation through the bridge."},
                {"tool": "vivado_state_diff", "why": "Compare before/after snapshots after project-mutating Tcl."},
            ],
            "related_resources": ["vivado://skills/raw-tcl-expert"],
        }
    if not has_session:
        return {
            "recommendations": [
                {"tool": "vivado_check_installation", "why": "Find Vivado and confirm the version."},
                {"tool": "vivado_start_session", "why": "Start a managed Tcl session, open the GUI, and report whether a visible window was found."},
            ],
            "related_resources": ["vivado://skills/gui-session"],
        }
    if not has_project:
        return {
            "recommendations": [
                {"tool": "vivado_create_project or vivado_open_project", "why": "Establish the active project before build operations."},
            ],
            "related_resources": ["vivado://skills/project-build-flow"],
        }
    return {
        "recommendations": [
            {"tool": "vivado_capture_state", "why": "Capture a baseline before mutating project state."},
            {"tool": "vivado_run_synthesis", "why": "Run synthesis before implementation."},
            {"tool": "vivado_state_diff", "why": "Compare before/after state when a build or setup step changed the project."},
            {"tool": "vivado_analyze_reports", "why": "Inspect timing/utilization/DRC/power/methodology after each build step."},
            {"tool": "vivado_report", "why": "Generate a targeted report after the aggregate analysis points at a failure area."},
        ],
        "related_resources": ["vivado://skills/project-build-flow"],
    }


def _find_skill(skill_id: str) -> Skill:
    for skill in SKILLS:
        if skill.skill_id == skill_id:
            return skill
    raise KeyError(f"Unknown skill_id {skill_id!r}")


def _read_skill_file(filename: str) -> str:
    return resources.files("vivado_mcp.skills").joinpath(filename).read_text(encoding="utf-8")
