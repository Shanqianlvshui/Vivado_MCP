# Vivado MCP

Vivado MCP is planned as a Model Context Protocol server that lets AI clients operate AMD Vivado through safe, workflow-level tools while the user can watch and interact with the Vivado GUI.

The first design target is not GUI click automation. The preferred mode is a managed Vivado Tcl session that can open the GUI with `start_gui`, load a small Tcl bridge, and let the MCP server submit validated workflow commands into that same Vivado process. Batch mode remains useful for CI and fallback automation.

Current design documents:

- [Vivado MCP Design](docs/design/vivado-mcp-design.md)
- [ADR 0001: Control Vivado through Tcl batch mode](docs/adr/0001-control-vivado-through-tcl-batch-mode.md)
- [ADR 0002: Support managed GUI Tcl sessions](docs/adr/0002-support-managed-gui-tcl-sessions.md)
- [ADR 0003: Support trusted-local raw Tcl](docs/adr/0003-support-trusted-local-raw-tcl.md)
- [ADR 0004: Provide built-in help and skills](docs/adr/0004-provide-built-in-help-and-skills.md)
- [Built-in Skills](docs/skills/README.md)

## Initial scope

- Discover a local Vivado installation and report its version.
- Start and stop a managed Vivado Tcl/GUI session.
- Verify whether a requested GUI session has a visible Vivado window without stealing focus, and bring that window forward only when explicitly requested.
- Submit raw Tcl to a managed session when trusted-local expert mode is enabled.
- Create or open project-mode Vivado projects.
- Add RTL/source/constraint files with path validation.
- Run synthesis, implementation, and bitstream generation.
- Generate timing, utilization, DRC, and message reports.
- Parse common report outputs into compact structured summaries.
- Expose logs and generated reports as MCP resources.
- Provide built-in help/skills so AI clients can learn the intended Vivado workflows before acting.

## Capability profiles

- `safe`: workflow tools only; no raw Tcl.
- `trusted-local`: workflow tools plus raw Tcl/source-file execution inside the managed Vivado session.
- `unrestricted`: raw Tcl with minimal policy checks for personal local use.

The prototype bridge in [experiments/mcp_bridge.tcl](experiments/mcp_bridge.tcl) proves the core control path: an external process can submit Tcl files to a live Vivado Tcl/GUI session and receive result files back.

## Built-in help

The MCP should expose tutorial content through both tools and resources:

- `vivado_help`
- `vivado_list_skills`
- `vivado_get_skill`
- `vivado_suggest_next_steps`
- `vivado://skills/index`

Seed skill docs live in [docs/skills](docs/skills).

## Install For Local Use

From this repo:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

This machine has been tested with:

```text
C:\Xilinx\Vivado\2023.1\bin\vivado.bat
```

## MCP Client Configuration

Use the installed console script as the MCP server command:

```json
{
  "mcpServers": {
    "vivado": {
      "command": "C:\\Workspace\\Vivado_mcp\\.venv\\Scripts\\vivado-mcp.exe",
      "env": {
        "VIVADO_BIN": "C:\\Xilinx\\Vivado\\2023.1\\bin\\vivado.bat",
        "VIVADO_MCP_WORKSPACE": "C:\\Workspace\\Vivado_mcp",
        "VIVADO_MCP_ALLOWED_ROOTS": "C:\\Workspace\\Vivado_mcp"
      }
    }
  }
}
```

`VIVADO_MCP_WORKSPACE` is the default working directory for managed sessions. `VIVADO_MCP_ALLOWED_ROOTS` is a semicolon-separated list on Windows; workflow paths such as projects, sources, constraints, and Tcl files in `trusted-local` mode must stay under one of these roots. Use `unrestricted` capability profile only for personal experiments that need to source Tcl outside the allowed roots.

## First Manual Test

After connecting the MCP client, use this sequence:

1. `vivado_help` with `topic="gui_session"`.
2. `vivado_check_installation`.
3. `vivado_start_session` with `open_gui=true`, then confirm `gui.visible=true`.
4. `vivado_focus_gui` only if the user asks to bring the Vivado window forward.
5. `vivado_run_tcl` with `tcl="return \"version=[version -short]\""`.
6. `vivado_project_summary` after opening or creating a project.
7. `vivado_list_artifacts` to inspect command/result files.
8. `vivado_stop_session`.

## Implemented Tools

- `vivado_check_installation`
- `vivado_start_session`
- `vivado_list_sessions`
- `vivado_session_state`
- `vivado_focus_gui`
- `vivado_stop_session`
- `vivado_run_tcl`
- `vivado_source_tcl`
- `vivado_create_project`
- `vivado_open_project`
- `vivado_add_sources`
- `vivado_run_synthesis`
- `vivado_run_implementation`
- `vivado_generate_bitstream`
- `vivado_report`
- `vivado_project_summary`
- `vivado_list_artifacts`
- `vivado_read_artifact`
- `vivado_help`
- `vivado_list_skills`
- `vivado_get_skill`
- `vivado_suggest_next_steps`

## Development Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall src
```

The test suite includes a fake Vivado process and an MCP protocol smoke test that starts the stdio server and lists tools/resources.

## Artifact Resources

Command files, result files, logs, and reports are stored under the managed session directory and exposed through artifact URIs:

```text
vivado://sessions/{session_ref}/artifacts/{artifact_id}
```

Use `vivado_list_artifacts` to discover artifact URIs and `vivado_read_artifact` to read text artifacts. `vivado_report` also returns a best-effort `report_summary` for timing, utilization, DRC, and message reports. `vivado_project_summary` returns the current project, source files, runs, IP, and block designs as structured data.

## Explicitly out of scope for the first version

- GUI click automation.
- Attaching to an arbitrary already-open Vivado process that did not load the MCP bridge.
- Hardware programming and live hardware manager operations.
- Full IP Integrator automation.
