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
        summary="Start Vivado through the CLI, open the GUI, and keep automation actions in the same session.",
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
        skill_id="hardware-debug-flow",
        title="Hardware Debug Flow",
        summary="Use generic hardware access, debug core discovery, ILA capture, and VIO read/write without project-specific Tcl scripts.",
        filename="hardware-debug-flow.md",
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
    lines = ["# Vivado CLI Skills", ""]
    for skill in SKILLS:
        lines.append(f"- `{skill.skill_id}`: {skill.summary} ({skill.resource_uri})")
    return "\n".join(lines) + "\n"


def help_topic(topic: str | None = None) -> dict[str, object]:
    normalized = (topic or "index").strip().lower().replace("_", "-")
    if normalized in {"index", "help"}:
        return {
            "topic": "index",
            "summary": "Vivado CLI exposes GUI sessions, project workflow commands, raw Tcl expert mode, and built-in skills.",
            "recommended_tools": ["vivado-cli assist next", "vivado-cli skills list", "vivado-cli tools list", "vivado-cli check-installation"],
            "related_resources": ["vivado://skills/index"],
        }
    if normalized in {"gui", "gui-session", "session"}:
        return {
            "topic": "gui_session",
            "summary": "Start a managed Vivado Tcl session with `open_gui=true`, verify `gui.visible` without stealing focus, and focus the window only when requested.",
            "recommended_tools": ["vivado-cli check-installation", "vivado-cli session start", "vivado-cli session state"],
            "related_resources": ["vivado://skills/gui-session"],
        }
    if normalized in {"project", "project-flow", "project-build", "project-build-flow", "build"}:
        return {
            "topic": "project_flow",
            "summary": "Use project workflow tools for repeatable Vivado operations before falling back to raw Tcl.",
            "recommended_tools": [
                "vivado-cli session open-project",
                "vivado-cli project summary",
                "vivado-cli run status",
                "vivado-cli run diagnose",
                "vivado-cli run launch",
                "vivado-cli run launch-local",
                "vivado-cli run logs",
                "vivado-cli report",
            ],
            "related_resources": ["vivado://skills/project-build-flow"],
        }
    if normalized in {"bd", "block-design", "block-design-flow", "ip-integrator", "ipi"}:
        return {
            "topic": "block_design_flow",
            "summary": "Use generic IP Integrator tools to create/open BD designs, audit validation/connectivity, dry-run/apply actions, and generate wrapper outputs.",
            "recommended_tools": [
                "vivado-cli bd summary",
                "vivado-cli bd validate",
                "vivado-cli tcl help <command>",
                "vivado-cli tcl review",
                "vivado-cli session run-tcl",
            ],
            "related_resources": ["vivado://skills/block-design-flow"],
        }
    if normalized in {"ip", "ips", "ip-catalog", "xci", "create-ip", "upgrade-ip", "output-products"}:
        return {
            "topic": "ip_flow",
            "summary": "Structured IP commands are not exposed in the current CLI surface yet. Use command help, Tcl review, and expert Tcl for create_ip/upgrade_ip/output products.",
            "recommended_tools": [
                "vivado-cli tcl help create_ip",
                "vivado-cli tcl help upgrade_ip",
                "vivado-cli tcl review",
                "vivado-cli session run-tcl",
                "vivado-cli project summary",
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if normalized in {"simulation", "sim", "xsim", "launch-simulation", "testbench", "testbench-fileset"}:
        return {
            "topic": "simulation_flow",
            "summary": "Structured simulation commands are not exposed in the current CLI surface yet. Use command help, Tcl review, and expert Tcl for launch_simulation/xsim flows.",
            "recommended_tools": [
                "vivado-cli tcl help launch_simulation",
                "vivado-cli tcl review",
                "vivado-cli session run-tcl",
                "vivado-cli project summary",
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if normalized in {"non-project", "nonproject", "non-project-flow", "read-verilog", "synth-design", "opt-design", "place-design", "route-design"}:
        return {
            "topic": "nonproject_flow",
            "summary": "Structured Non-project Mode commands are not exposed in the current CLI surface yet. Use command help, Tcl review, and expert Tcl for read/synth/opt/place/route flows.",
            "recommended_tools": [
                "vivado-cli tcl help read_verilog",
                "vivado-cli tcl help synth_design",
                "vivado-cli tcl help route_design",
                "vivado-cli tcl review",
                "vivado-cli session run-tcl",
                "vivado-cli report",
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if normalized in {"hardware", "hw", "hw-manager", "hardware-manager", "hw-server", "device", "devices"}:
        return {
            "topic": "hardware_debug",
            "summary": "Use structured hardware commands for debug-core discovery, VIO probe read/write, generic ILA capture, VIO-backed SPI readback, and artifact analysis. Programming remains expert Tcl after review.",
            "recommended_tools": [
                "vivado-cli hw list-debug-cores",
                "vivado-cli hw vio-read",
                "vivado-cli hw vio-write",
                "vivado-cli hw capture-ila",
                "vivado-cli hw spi-read",
                "vivado-cli tcl help open_hw_manager",
                "vivado-cli tcl help program_hw_devices",
                "vivado-cli tcl review",
                "vivado-cli session run-tcl",
            ],
            "related_resources": ["vivado://skills/hardware-debug-flow", "vivado://official-docs/index", "vivado://skills/raw-tcl-expert"],
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
            "summary": "Use structured fileset and constraint commands for source membership, top/include/define properties, XDC set management, and XDC order checks before falling back to expert Tcl.",
            "recommended_tools": [
                "vivado-cli project summary",
                "vivado-cli fileset list",
                "vivado-cli fileset describe",
                "vivado-cli fileset add-files",
                "vivado-cli fileset apply",
                "vivado-cli constraint diagnostics",
                "vivado-cli constraint check-order",
                "vivado-cli constraint apply",
                "vivado-cli tcl review",
                "vivado-cli tcl help add_files",
            ],
            "related_resources": ["vivado://skills/fileset-constraint-flow"],
        }
    if normalized in {"report", "reports", "timing", "timing-closure", "utilization", "drc", "power", "methodology"}:
        return {
            "topic": "report_diagnostics",
            "summary": "Generate Vivado reports and classify timing, clock interaction, utilization, DRC, power, and methodology findings into issue IDs with quality gates, root-cause hints, next-action plans, and official-doc queries.",
            "recommended_tools": [
                "vivado-cli report",
                "vivado-cli tools describe report",
                "vivado-cli tcl help <command>",
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if normalized in {"recovery", "resume", "timeline", "artifacts", "artifact", "session-recovery"}:
        return {
            "topic": "session_recovery",
            "summary": "Recover long-running Vivado work by reading the session timeline, latest analyses, snapshots, summaries, reports, checkpoints, and next-action plan.",
            "recommended_tools": [
                "vivado-cli assist next",
                "vivado-cli session recovery",
                "vivado-cli session timeline",
                "vivado-cli session artifacts",
                "vivado-cli session read-artifact",
                "vivado-cli session list",
                "vivado-cli session state",
                "vivado-cli project summary",
                "vivado-cli run status",
                "vivado-cli run diagnose",
                "vivado-cli run logs",
            ],
            "related_resources": ["vivado://skills/project-build-flow"],
        }
    if normalized in {"raw-tcl", "tcl", "expert"}:
        return {
            "topic": "raw_tcl",
            "summary": "Raw Tcl is available in trusted-local/unrestricted profiles and can do anything Vivado Tcl can do.",
            "recommended_tools": [
                "vivado-cli assist next --tcl <script>",
                "vivado-cli tcl help <command>",
                "vivado-cli tcl review",
                "vivado-cli session state",
                "vivado-cli session run-tcl",
                "vivado-cli session source-tcl",
            ],
            "related_resources": ["vivado://skills/raw-tcl-expert"],
        }
    if normalized in {"official-docs", "official-docs-reference", "official-docs-index", "official-docs-guide", "official-docs-catalog", "official-docs-catalogue", "official", "reference", "docs", "manuals"}:
        return {
            "topic": "official_docs",
            "summary": "Use packaged official-doc skill guidance plus installed Vivado Tcl help before designing Tcl or workflow-level CLI actions.",
            "recommended_tools": [
                "vivado-cli skills get official-docs-reference",
                "vivado-cli tcl help <command>",
                "vivado-cli tools list",
            ],
            "related_resources": ["vivado://official-docs/index", "vivado://skills/official-docs-reference"],
        }
    return {
        "topic": normalized,
        "summary": "Unknown help topic. Use `vivado-cli skills list` to discover available tutorials.",
        "recommended_tools": ["vivado-cli skills list", "vivado-cli tools list"],
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
                {"tool": "vivado-cli help topic official-docs", "why": "Choose the packaged official-document guidance for unfamiliar Vivado work."},
                {"tool": "vivado-cli skills get official-docs-reference", "why": "Read the authority-layer workflow and local PDF expectations."},
                {"tool": "vivado-cli tcl help <command>", "why": "Check the command-specific official-doc topic, CLI coverage, and optional installed Vivado help."},
                {"tool": "vivado-cli tools list", "why": "Confirm whether a structured CLI command exists before falling back to expert Tcl."},
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
                {"tool": "vivado-cli tcl help create_ip", "why": "Check IP creation syntax, official-doc routing, and current CLI coverage."},
                {"tool": "vivado-cli tcl help upgrade_ip", "why": "Check upgrade semantics before any .xci mutation."},
                {"tool": "vivado-cli tcl review", "why": "Review create/upgrade/generate Tcl before expert execution."},
                {"tool": "vivado-cli session run-tcl", "why": "Use expert Tcl for IP work until dedicated IP commands are exposed."},
                {"tool": "vivado-cli project summary", "why": "Inspect project IP and generated-output state after the Tcl action."},
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
                {"tool": "vivado-cli tcl help launch_simulation", "why": "Check launch_simulation syntax and current CLI coverage."},
                {"tool": "vivado-cli project summary", "why": "Inspect project filesets, top, IP, and generated outputs before simulation."},
                {"tool": "vivado-cli tcl review", "why": "Review simulation setup Tcl before mutating filesets or launch state."},
                {"tool": "vivado-cli session run-tcl", "why": "Use expert Tcl for simulation until dedicated simulation commands are exposed."},
                {"tool": "vivado-cli run logs", "why": "Read Vivado run logs when simulation failures are reflected through generated logs."},
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
                {"tool": "vivado-cli tcl help read_verilog", "why": "Check source-loading syntax and official-doc routing."},
                {"tool": "vivado-cli tcl help synth_design", "why": "Check synthesis options before building a Non-project script."},
                {"tool": "vivado-cli tcl help route_design", "why": "Check implementation options before routing."},
                {"tool": "vivado-cli tcl review", "why": "Review the assembled Non-project Tcl script before execution."},
                {"tool": "vivado-cli session run-tcl", "why": "Run Non-project Tcl directly until dedicated Non-project commands are exposed."},
                {"tool": "vivado-cli report", "why": "Generate structured reports after synthesis or implementation checkpoints exist."},
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
        vio_write = any(word in text for word in ("vio-write", "vio write", "commit_hw_vio", "set_hw_probe", "set vio", "toggle vio"))
        if programming:
            recommendations = [
                {"tool": "vivado-cli tcl help program_hw_devices", "why": "Check hardware programming syntax and official UG908/UG835 routing."},
                {"tool": "vivado-cli tcl review", "why": "Programming, cfgmem, and boot Tcl require explicit destructive review."},
                {"tool": "vivado-cli session run-tcl --expect-destructive", "why": "Only execute after the user explicitly accepts the hardware mutation."},
                {"tool": "vivado-cli session state", "why": "Confirm the target session before touching hardware state."},
            ]
        elif vio_write:
            recommendations = [
                {"tool": "vivado-cli hw list-debug-cores", "why": "Confirm the exact VIO and output probe names before writing."},
                {"tool": "vivado-cli hw vio-read", "why": "Capture current VIO values before changing outputs."},
                {"tool": "vivado-cli hw vio-write", "why": "Write selected VIO output probes with explicit hardware-access and VIO-write acknowledgement."},
                {"tool": "vivado-cli tcl help commit_hw_vio", "why": "Check the underlying Hardware Manager command semantics when reviewing unusual VIO flows."},
                {"tool": "vivado-cli session state", "why": "Confirm the target session before touching hardware state."},
            ]
        else:
            recommendations = [
                {"tool": "vivado-cli hw list-debug-cores", "why": "Discover ILA/VIO core names, CELL_NAME values, and probe names before capture or VIO readback."},
                {"tool": "vivado-cli hw vio-read", "why": "Read current VIO probe values without changing output probes."},
                {"tool": "vivado-cli hw capture-ila", "why": "Capture a generic ILA to a session artifact and analyze numeric probes without writing one-off Tcl."},
                {"tool": "vivado-cli hw spi-read", "why": "Read VIO-backed SPI status/register values with configurable probe names and bit layout."},
                {"tool": "vivado-cli tcl help open_hw_manager", "why": "Check Hardware Manager command syntax and risk routing."},
                {"tool": "vivado-cli tcl help get_hw_devices", "why": "Check read-only device enumeration syntax."},
                {"tool": "vivado-cli tcl review", "why": "Review custom Hardware Manager Tcl before execution."},
                {"tool": "vivado-cli session run-tcl", "why": "Use expert Tcl only for hardware actions not yet exposed as structured CLI commands."},
            ]
        return {
            "recommendations": recommendations,
            "related_resources": ["vivado://skills/hardware-debug-flow", "vivado://official-docs/index", "vivado://skills/raw-tcl-expert"],
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
                {"tool": "vivado-cli project summary", "why": "Inspect filesets, top, source files, constraints, IP, BD, and runs before changing project state."},
                {"tool": "vivado-cli fileset list", "why": "Inspect fileset names, types, enabled scopes, top values, and file counts."},
                {"tool": "vivado-cli fileset describe", "why": "Inspect source membership, libraries, processing order, USED_IN, and fileset properties."},
                {"tool": "vivado-cli fileset apply", "why": "Set TOP, INCLUDE_DIRS, DEFINE.*, and fileset-level properties without raw Tcl."},
                {"tool": "vivado-cli fileset add-files", "why": "Add source files with library, file type, USED_IN, include dir, define, and top options."},
                {"tool": "vivado-cli constraint diagnostics", "why": "Inspect constraint sets, XDC files, enabled scopes, and high-signal XDC markers."},
                {"tool": "vivado-cli constraint check-order", "why": "Check that XDC clock definitions load before dependent exceptions and I/O delays."},
                {"tool": "vivado-cli constraint apply", "why": "Add/remove/reorder XDC files and set constraint-set scopes through a structured command."},
                {"tool": "vivado-cli tcl review", "why": "Review expert Tcl only for uncommon fileset or constraint operations not covered by structured commands."},
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
                {"tool": "vivado-cli report", "why": "Generate one structured timing/utilization/DRC/power/methodology/message report artifact."},
                {"tool": "vivado-cli tools describe report", "why": "Check supported report types and safety metadata."},
                {"tool": "vivado-cli tcl help report_timing_summary", "why": "Check exact report Tcl syntax before custom reports."},
                {"tool": "vivado-cli tcl review", "why": "Review custom report Tcl when built-in report types are insufficient."},
            ],
            "related_resources": ["vivado://skills/project-build-flow", "vivado://official-docs/index"],
        }
    if "tcl" in text:
        return {
            "recommendations": [
                {"tool": "vivado-cli tcl help <command>", "why": "Check official-doc routing, installed Vivado help, and CLI command coverage before writing Tcl."},
                {"tool": "vivado-cli tcl review", "why": "Review high-risk Tcl before expert execution."},
                {"tool": "vivado-cli session state", "why": "Confirm the managed session is idle before raw Tcl."},
                {"tool": "vivado-cli session run-tcl", "why": "Run a small inline Tcl probe or mutation through the CLI bridge."},
                {"tool": "vivado-cli session source-tcl", "why": "Source a reviewed Tcl file when inline Tcl is too large."},
            ],
            "related_resources": ["vivado://skills/raw-tcl-expert"],
        }
    if not has_session:
        return {
            "recommendations": [
                {"tool": "vivado-cli check-installation", "why": "Find Vivado and confirm the version."},
                {"tool": "vivado-cli session start", "why": "Start a managed Tcl session, open the GUI, and report whether a visible window was found."},
            ],
            "related_resources": ["vivado://skills/gui-session"],
        }
    if not has_project:
        return {
            "recommendations": [
                {"tool": "vivado-cli session open-project", "why": "Open an existing .xpr before project-mode build operations."},
                {"tool": "vivado-cli tcl help create_project", "why": "Use reviewed expert Tcl if the project must be created rather than opened."},
            ],
            "related_resources": ["vivado://skills/project-build-flow"],
        }
    return {
        "recommendations": [
            {"tool": "vivado-cli session state", "why": "Confirm the live session, project, GUI visibility, and capability profile."},
            {"tool": "vivado-cli project summary", "why": "Refresh the current project/source/run/IP/BD summary."},
            {"tool": "vivado-cli run status", "why": "Inspect synthesis or implementation run status before launching more work."},
            {"tool": "vivado-cli run diagnose", "why": "Classify stale, failed, queued, and missing-output run states."},
            {"tool": "vivado-cli report", "why": "Generate a targeted report after build or validation work."},
        ],
        "related_resources": ["vivado://skills/project-build-flow"],
    }


def _find_skill(skill_id: str) -> Skill:
    for skill in SKILLS:
        if skill.skill_id == skill_id:
            return skill
    raise KeyError(f"Unknown skill_id {skill_id!r}")


def _read_skill_file(filename: str) -> str:
    return resources.files("vivado_cli.skills").joinpath(filename).read_text(encoding="utf-8")
