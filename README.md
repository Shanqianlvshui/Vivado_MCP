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
- Audit and manage Vivado filesets (sources / simulation / constraint sets) including include directories, defines, libraries, file properties, top module, USED_IN scopes, dry-run plans, and XDC reorder suggestions.
- Apply structured source-fileset and constraint-set changes with optional before/after state diffs.
- Audit XDC constraint filesets: loading order, per-file command markers, USED_IN scopes, methodology markers, and basic UG903/UG949 sanity warnings.
- Search, dry-run/create, inspect, check upgrade state, upgrade, and generate output products for Vivado project IP.
- Audit simulation setup, dry-run/prepare simulation filesets, launch Vivado simulation, and parse xsim/xelab/xvlog/xvhdl logs into issue IDs.
- Create, inspect, mutate, validate, and generate generic IP Integrator block designs.
- Run synthesis, implementation, and bitstream generation.
- Run basic Non-project Mode flows: read RTL/XDC, execute synth/opt/place/route, write checkpoints, and collect reports.
- Generate timing, utilization, DRC, methodology, power, and message reports.
- Parse common report outputs into compact structured summaries and aggregate report diagnostics with issue IDs, evidence, next-step guidance, and official-document queries.
- Perform explicit, read-only hardware discovery for hw_server targets/devices; hardware programming remains out of scope.
- Capture JSON state snapshots and diff project/fileset/constraint/IP/BD/run/report state before and after risky or long-running operations.
- Expose logs and generated reports as MCP resources.
- Provide built-in help/skills so AI clients can learn the intended Vivado workflows before acting.
- Package AMD official Vivado documentation metadata and topic guidance as the authority layer for help and expert Tcl planning.

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
- `vivado_official_reference_guide`
- `vivado_search_official_docs`
- `vivado_tcl_command_help`
- `vivado_review_tcl`
- `vivado_capture_state`
- `vivado_state_diff`
- `vivado_sync_official_docs`
- `vivado_download_xilinx_pdf`
- `vivado_search_xilinx_docs`
- `vivado_list_official_references`
- `vivado_get_official_reference`
- `vivado://skills/index`
- `vivado://official-docs/index`

Seed skill docs live in [docs/skills](docs/skills).

The official reference layer stores document IDs, AMD URLs, scope summaries, topic routing, and local filename candidates. It does not copy the full AMD document text into this repository.

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
        "VIVADO_MCP_ALLOWED_ROOTS": "C:\\Workspace\\Vivado_mcp",
        "VIVADO_MCP_DOCS_ROOT": "C:\\Database\\FPGA\\Vivado_docs"
      }
    }
  }
}
```

`VIVADO_MCP_WORKSPACE` is the default working directory for managed sessions. `VIVADO_MCP_ALLOWED_ROOTS` is a semicolon-separated list on Windows; workflow paths such as projects, sources, constraints, and Tcl files in `trusted-local` mode must stay under one of these roots. `VIVADO_MCP_DOCS_ROOT` points to the local AMD Vivado documentation library used by the official-reference index; it defaults to `C:\Database\FPGA\Vivado_docs`. Use `unrestricted` capability profile only for personal experiments that need to source Tcl outside the allowed roots.

## AI Operating Flow

AI clients should use the MCP in this order:

1. Call `vivado_help(topic="official_docs")` or read `vivado://skills/official-docs-reference` before planning unfamiliar Vivado actions.
2. Call `vivado_official_reference_guide(topic=...)` to select the authoritative AMD manuals for the task.
3. Call `vivado_get_official_reference(doc_id=...)` for the exact official URL and local PDF candidates under `C:\Database\FPGA\Vivado_docs`.
4. If local PDFs are missing, call `vivado_sync_official_docs` for the packaged Vivado catalog or `vivado_download_xilinx_pdf` for a specific AMD/Xilinx PDF.
5. Call `vivado_search_official_docs(query=..., doc_id=... or topic=...)` for exact command names, options, and short local PDF snippets.
6. Prefer structured workflow tools such as project, source/fileset/constraint, report, and BD tools when they cover the task.
7. For complex source or XDC work, call `vivado_source_audit` first, then use `vivado_fileset_apply`, `vivado_constraint_set_apply`, and `vivado_xdc_order_check` before falling back to expert Tcl.
8. For IP work, call `vivado_ip_catalog_search`, then use `vivado_create_ip(dry_run=true)`, `vivado_describe_ip`, `vivado_ip_upgrade_check`, and `vivado_generate_ip_outputs`; use `vivado_upgrade_ip(expect_upgrade=true)` only when the `.xci` mutation is intended.
9. For simulation work, call `vivado_simulation_audit`, then `vivado_prepare_simulation(dry_run=true)` for non-trivial fileset changes, then `vivado_launch_simulation` and `vivado_analyze_xsim_logs`; pass `capture_diff=true` when launch artifacts/log changes should be audited.
10. For Non-project Mode work, call `vivado_nonproject_read_sources`, then run `vivado_nonproject_synth_design`, `vivado_nonproject_opt_design`, `vivado_nonproject_place_design`, and `vivado_nonproject_route_design` as needed.
11. For hardware discovery, call `vivado_hw_discover(expect_hardware_access=true)` only for read-only hw_server/target/device enumeration; programming remains expert Tcl after review. Use `capture_diff=true` only when you need the surrounding project/report state audit trail.
12. Call `vivado_tcl_command_help(command=...)` before unfamiliar Tcl commands; it combines official search, MCP tool coverage, and optional installed Vivado help.
13. Call `vivado_review_tcl(tcl=...)` before expert-mode execution.
14. Use `vivado_run_tcl` or `vivado_source_tcl` only for commands that are not yet modeled as workflow tools; set `expect_destructive=true` when the review requires it.
15. For risky or long-running changes, call `vivado_capture_state` before/after and `vivado_state_diff`, or pass `capture_diff=true` to supported mutating tools.
16. After every mutating action, call `vivado_project_summary`, `vivado_bd_summary`, `vivado_analyze_reports`, or `vivado_list_artifacts` to inspect the resulting state.
17. Call `vivado_focus_gui` only when the user explicitly wants Vivado brought to the foreground.

## First Manual Test

After connecting the MCP client, use this sequence:

1. `vivado_help` with `topic="gui_session"`.
2. `vivado_check_installation`.
3. `vivado_start_session` with `open_gui=true`, then confirm `gui.visible=true`.
4. `vivado_focus_gui` only if the user asks to bring the Vivado window forward.
5. `vivado_official_reference_guide` with `topic="tcl"` or the relevant task topic before expert Tcl work.
6. `vivado_tcl_command_help` with `command="create_project"` or another command being planned.
7. `vivado_review_tcl` with `tcl="return \"version=[version -short]\""`.
8. `vivado_run_tcl` with `tcl="return \"version=[version -short]\""`.
9. `vivado_project_summary` after opening or creating a project.
10. `vivado_list_artifacts` to inspect command/result files.
11. `vivado_stop_session`.

## Implemented Tools

- `vivado_check_installation`
- `vivado_start_session`
- `vivado_list_sessions`
- `vivado_session_state`
- `vivado_focus_gui`
- `vivado_stop_session`
- `vivado_run_tcl`
- `vivado_source_tcl`
- `vivado_review_tcl`
- `vivado_tcl_command_help`
- `vivado_capture_state`
- `vivado_state_diff`
- `vivado_create_project`
- `vivado_open_project`
- `vivado_add_sources`
- `vivado_remove_sources`
- `vivado_set_file_properties`
- `vivado_set_top`
- `vivado_list_filesets`
- `vivado_create_fileset`
- `vivado_describe_fileset`
- `vivado_constraint_diagnostics`
- `vivado_source_audit`
- `vivado_xdc_order_check`
- `vivado_fileset_apply`
- `vivado_constraint_set_apply`
- `vivado_ip_catalog_search`
- `vivado_create_ip`
- `vivado_list_ips`
- `vivado_describe_ip`
- `vivado_ip_upgrade_check`
- `vivado_upgrade_ip`
- `vivado_generate_ip_outputs`
- `vivado_simulation_audit`
- `vivado_prepare_simulation`
- `vivado_launch_simulation`
- `vivado_analyze_xsim_logs`
- `vivado_nonproject_read_sources`
- `vivado_nonproject_synth_design`
- `vivado_nonproject_opt_design`
- `vivado_nonproject_place_design`
- `vivado_nonproject_route_design`
- `vivado_bd_open_or_create`
- `vivado_bd_summary`
- `vivado_bd_apply`
- `vivado_bd_validate`
- `vivado_bd_generate`
- `vivado_run_synthesis`
- `vivado_run_implementation`
- `vivado_generate_bitstream`
- `vivado_report`
- `vivado_analyze_reports`
- `vivado_hw_discover`
- `vivado_project_summary`
- `vivado_list_artifacts`
- `vivado_read_artifact`
- `vivado_help`
- `vivado_list_skills`
- `vivado_get_skill`
- `vivado_suggest_next_steps`
- `vivado_list_official_references`
- `vivado_get_official_reference`
- `vivado_official_reference_guide`
- `vivado_search_official_docs`
- `vivado_search_xilinx_docs`
- `vivado_download_xilinx_pdf`
- `vivado_sync_official_docs`
- `vivado_clean_bad_pdfs`

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

Use `vivado_list_artifacts` to discover artifact URIs and `vivado_read_artifact` to read text artifacts. `vivado_report` also returns a best-effort `report_summary` for timing, utilization, DRC, methodology, power, and message reports. `vivado_analyze_reports` generates selected reports, ranks timing/utilization/DRC/power/methodology issues, and writes a JSON analysis artifact with issue IDs such as `timing.setup_failed`, `timing.unconstrained_paths`, `drc.io_standard_missing`, `utilization.resource_pressure`, and `power.thermal_risk`. `vivado_list_ips`, `vivado_describe_ip`, and `vivado_ip_upgrade_check` return structured project IP state, upgrade risk, output-generation state, and recommended next tools. `vivado_simulation_audit` checks simulation fileset/top/testbench/IP output-product state before launch, `vivado_launch_simulation` returns simulation log artifact paths when Vivado reports them, and `vivado_analyze_xsim_logs` writes a JSON diagnostic artifact with simulation issue IDs and official-doc queries. Non-project step tools write checkpoints under session artifacts and parse requested reports. `vivado_hw_discover` returns structured read-only hardware target/device summaries and a TSV artifact. `vivado_project_summary` returns the current project, source files, runs, IP, and block designs as structured data.

`vivado_capture_state` writes a JSON snapshot of project, fileset, constraint, IP, report-artifact, run, and optional block-design state. `vivado_state_diff` compares two snapshot artifacts and returns v2 grouped diffs plus a flat `changes` list, summary counts, and follow-up tool recommendations. Supported mutating or artifact-producing tools, including expert Tcl, source/fileset/property/top operations, IP operations, simulation launch, BD apply/generate, hardware discovery, and run launch helpers, accept `capture_diff=true` to return before/after snapshot artifact URIs plus a diff artifact.

## Official Reference Resources

The help system exposes official-reference metadata through these resources:

```text
vivado://official-docs/index
vivado://official-docs/{doc_id}
```

Use `vivado_official_reference_guide(topic=...)` for AI routing. Current topics include `tcl`, `project`, `bd`, `ip`, `constraints`, `build`, `simulation`, `reports`, `hardware`, `dfx`, `methodology`, `io`, `installation`, `migration`, `libraries`, and `embedded`.

Use `vivado_search_official_docs(query=...)` to search the local PDFs under `C:\Database\FPGA\Vivado_docs`. The server uses `pdftotext` from Poppler and caches extracted text under `.vivado_mcp_text_cache` in the docs root. Set `VIVADO_MCP_PDFTOTEXT` if `pdftotext` is not on `PATH`.

The MCP also includes the AMD/Xilinx PDF download workflow from the `download-xilinx-pdf` skill:

- `vivado_search_xilinx_docs(query=...)`: search AMD KHub.
- `vivado_download_xilinx_pdf(source=...)`: resolve AMD Fluid Topics `/go`, `/v/u`, and `/r/{mapId}/root` pages, download through KHub content APIs, and verify the `%PDF` signature.
- `vivado_sync_official_docs(doc_ids=[...])`: populate or refresh the packaged Vivado official-reference catalog.
- `vivado_clean_bad_pdfs(delete_bad=false)`: find local PDFs that do not start with `%PDF`.

## Explicitly out of scope for the first version

- GUI click automation.
- Attaching to an arbitrary already-open Vivado process that did not load the MCP bridge.
- Hardware programming, configuration-memory writes, boot operations, and debug/probe mutation. Read-only hardware discovery is supported with explicit confirmation.
- Advanced IP Integrator automation beyond the generic BD action model.
