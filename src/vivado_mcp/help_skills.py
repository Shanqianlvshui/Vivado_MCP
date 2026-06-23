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
            "recommended_tools": ["vivado_create_project", "vivado_add_sources", "vivado_run_synthesis", "vivado_report"],
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
    if normalized in {"raw-tcl", "tcl", "expert"}:
        return {
            "topic": "raw_tcl",
            "summary": "Raw Tcl is available in trusted-local/unrestricted profiles and can do anything Vivado Tcl can do.",
            "recommended_tools": ["vivado_session_state", "vivado_run_tcl", "vivado_source_tcl"],
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
    if "tcl" in text:
        return {
            "recommendations": [
                {"tool": "vivado_session_state", "why": "Confirm the managed session is idle before raw Tcl."},
                {"tool": "vivado_run_tcl", "why": "Run a small Tcl probe or mutation through the bridge."},
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
            {"tool": "vivado_run_synthesis", "why": "Run synthesis before implementation."},
            {"tool": "vivado_report", "why": "Inspect timing/utilization/messages after each build step."},
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
