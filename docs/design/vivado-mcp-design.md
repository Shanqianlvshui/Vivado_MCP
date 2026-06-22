# Vivado MCP Design

Research date: 2026-06-23.

## Goal

Build an MCP server that lets an AI client operate AMD Vivado safely and repeatably while the user can keep the Vivado GUI open. The server should hide Vivado Tcl details behind a small set of deep workflow tools, while still returning enough logs, reports, and state for the AI to diagnose FPGA build problems.

## Source notes

Primary references used for this design:

- AMD UG835, Vivado Design Suite Tcl Command Reference Guide, 2025.2: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands
- AMD UG894, Vivado Design Suite User Guide: Using Tcl Scripting, 2025.2: https://docs.amd.com/r/en-US/ug894-vivado-tcl-scripting
- AMD UG835, Tcl Shell Mode: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/Tcl-Shell-Mode
- AMD UG835, Vivado IDE Mode: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/Vivado-IDE-Mode
- AMD UG835, `start_gui`: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/start_gui
- AMD UG835, Sourcing a Tcl Script: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/Sourcing-a-Tcl-Script
- AMD UG894, Sourcing Tcl Scripts: https://docs.amd.com/r/en-US/ug894-vivado-tcl-scripting/Sourcing-Tcl-Scripts
- AMD UG892, Design Flows Overview, Project Mode and Non-Project Mode: https://docs.amd.com/r/en-US/ug892-vivado-design-flows-overview/Understanding-Project-Mode-and-Non-Project-Mode
- AMD UG892, Using Non-Project Mode: https://docs.amd.com/r/en-US/ug892-vivado-design-flows-overview/Using-Non-Project-Mode
- AMD UG835 `launch_runs`: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/launch_runs
- AMD UG835 `wait_on_runs`: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/wait_on_runs
- AMD UG835 `report_timing` and `report_timing_summary`: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/report_timing and https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/report_timing_summary
- AMD UG835 `report_utilization`: https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/report_utilization
- MCP specification 2025-06-18: https://modelcontextprotocol.io/specification/2025-06-18
- MCP server tools: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- MCP server resources: https://modelcontextprotocol.io/specification/2025-06-18/server/resources
- Official MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Official MCP TypeScript SDK: https://github.com/modelcontextprotocol/typescript-sdk

Key facts from the references:

- Vivado has two main design flows: Project Mode and Non-Project Mode. Both can be driven through Tcl commands or batch scripts; Tcl commands are the simplest way to run Non-Project Mode.
- Non-Project Mode gives full manual control but requires the caller to manage source files, reports, checkpoints, and reruns.
- Project Mode provides project state, run infrastructure, source management, and run results, which is useful for an AI-facing first version.
- Vivado supports Tcl commands in the Tcl shell and in the IDE Tcl Console.
- Vivado can open the IDE from the Tcl shell with `start_gui`; the GUI is invoked with the current project, design, and run information.
- Vivado can source Tcl scripts from the IDE with `Tools > Run Tcl Script`, and operations in the IDE are blocked until the script completes.
- `launch_runs` is the Project Mode command for synthesis and implementation runs; `wait_on_runs` blocks until launched runs finish.
- Vivado reports can be emitted to stdout or files, and several report commands support machine-friendly options such as writing to a file or returning strings.
- MCP tools are model-controlled actions with JSON schemas. MCP resources are application-controlled context objects such as files, logs, and reports.
- MCP resources are a good fit for built-in tutorials because the model can read them as contextual guidance before choosing tools.

## Product stance

The MCP server should feel like "Vivado workflow automation with a visible Vivado session", not "remote shell with a Vivado binary".

The AI-facing interface should be small:

- Create/open a project.
- Add design inputs.
- Run flow steps.
- Ask for reports.
- Inspect logs and failure summaries.
- Open or keep open the Vivado GUI for the same session.
- Drop into raw Tcl when the user intentionally enables trusted-local expert mode.
- Ask for help or load a built-in skill before operating Vivado.

The implementation can be large:

- Tcl generation.
- Path normalization and validation.
- Vivado process management.
- Run-state polling.
- Report extraction and parsing.
- Artifact indexing.
- Safety policy enforcement.

That gives callers leverage and keeps Vivado-specific knowledge local to the server.

## Architecture

```text
AI client
  |
  | MCP stdio / Streamable HTTP
  v
MCP server
  |
  |-- Tool registry
  |-- Resource registry
  |-- PolicyGuard
  |-- ProjectIndex
  |-- ArtifactIndex
  |-- VivadoLocator
  |-- VivadoRunner
  |-- TclScriptBuilder
  |-- ReportParser
  |-- HelpSkills
  `-- DiagnosticsEngine
          |
          v
      vivado -mode tcl -source mcp_bridge.tcl
          |
          | optional
          v
      start_gui
```

Batch mode is still an adapter:

```text
MCP server -> VivadoBatchAdapter -> vivado -mode batch -source generated.tcl
```

## Module design

### MCP server module

External seam: MCP tools and resources.

Responsibilities:

- Register tools with JSON input schemas and structured output schemas.
- Register resource templates for logs, reports, and project summaries.
- Convert module errors into MCP tool errors.
- Keep the external tool list stable and small.

### PolicyGuard module

External seam: validation functions called before any Vivado operation.

Responsibilities:

- Ensure all project, source, constraint, report, and artifact paths are under allowed workspace roots.
- Block path traversal and shell metacharacter leaks.
- Classify operations as read-only, build-mutating, or destructive.
- Gate raw Tcl behind an explicit capability profile.
- Require explicit opt-in for destructive operations such as project deletion, cleanup, and hardware programming.
- Enforce `VIVADO_MCP_WORKSPACE` and `VIVADO_MCP_ALLOWED_ROOTS` for workflow paths.
- Allow `unrestricted` profile to source Tcl outside allowed roots for personal experiments.

### VivadoLocator module

External seam:

```text
locateVivado(config) -> VivadoInstallation
getVivadoVersion(installation) -> VersionInfo
```

Responsibilities:

- Resolve Vivado from explicit config, `VIVADO_BIN`, `PATH`, or common install directories.
- Run `vivado -version` for health checks.
- Report missing executable, unsupported OS, or version mismatch with actionable diagnostics.

### VivadoRunner module

External seam:

```text
runBatch(script, options) -> VivadoRunResult
```

Responsibilities:

- Write generated Tcl to a temporary artifact directory.
- Launch `vivado -mode batch -source <script>`.
- Capture stdout, stderr, exit code, log path, journal path, duration, and generated artifacts.
- Enforce timeout and cancellation.
- Normalize Vivado failures into error categories.

This module owns process behavior. Callers should not spawn Vivado directly.

### VivadoSession module

External seam:

```text
startSession(options) -> SessionRef
stopSession(sessionRef) -> SessionResult
callWorkflow(sessionRef, workflowRequest) -> VivadoCommandResult
getSessionState(sessionRef) -> VivadoSessionState
```

Responsibilities:

- Launch a managed Vivado Tcl process.
- Load the MCP Tcl bridge at startup.
- Optionally call `start_gui` so the same Vivado process becomes visible to the user.
- Serialize workflow commands so AI and user actions do not race.
- Track whether the session is idle, running a command, blocked by Vivado, or stopped.
- Capture logs, command transcripts, and generated reports as artifacts.

This is the preferred interactive adapter for the product.

### VivadoBridge module

External seam: a small Tcl script loaded inside Vivado.

Responsibilities:

- Receive validated command files or command envelopes from the MCP server.
- Source generated or raw Tcl inside the already-running Vivado process.
- Write command result files back to the MCP artifact directory.
- Report busy/idle/error state.
- Avoid arbitrary external input; only consume files created by the MCP server in the session directory.

The bridge is the clean way to let an external MCP server operate the same Vivado process that owns the GUI. It avoids depending on undocumented attach/RPC behavior for arbitrary already-open GUI processes.

### TclScriptBuilder module

External seam:

```text
buildCreateProjectScript(request) -> TclScript
buildRunSynthesisScript(request) -> TclScript
buildRunImplementationScript(request) -> TclScript
buildReportScript(request) -> TclScript
```

Responsibilities:

- Generate Tcl only from typed, validated request objects.
- Quote paths and Tcl values safely.
- Prefer Project Mode commands for v0.
- Emit predictable report filenames.
- Add small Tcl helper procs for common checks such as run completion and report generation.

### ProjectIndex module

External seam:

```text
registerProject(path) -> ProjectRef
getProject(ref) -> ProjectRecord
listProjects() -> ProjectRecord[]
```

Responsibilities:

- Track known `.xpr` files and project metadata.
- Avoid hidden global state in the MCP server.
- Allow every build tool call to accept an explicit project reference.

### ArtifactIndex module

External seam:

```text
recordArtifact(projectRef, artifact) -> ResourceUri
readResource(uri) -> ResourceContent
```

Responsibilities:

- Store logs, journals, reports, generated Tcl, and parsed summaries.
- Expose artifacts as MCP resources using a custom `vivado://` URI scheme.
- Enforce size limits and truncation rules for large logs.

### ReportParser module

External seam:

```text
parseTimingSummary(text) -> TimingSummary
parseUtilization(text) -> UtilizationSummary
parseMessages(text) -> MessageSummary
```

Responsibilities:

- Extract common high-value fields: WNS, TNS, WHS, THS, failing endpoints, LUT/FF/BRAM/DSP usage, DRC counts, critical warnings, and errors.
- Keep the original report available as a resource.
- Treat parsing as best effort; never hide the raw report.

### DiagnosticsEngine module

External seam:

```text
summarizeRunFailure(runResult, artifacts) -> DiagnosticSummary
```

Responsibilities:

- Identify common failure classes: Vivado not found, license issue, Tcl error, missing source, top module not found, synthesis failure, implementation failure, timing failure, timeout.
- Link each diagnosis back to raw logs and reports.
- Keep recommendations conservative and reproducible.

### HelpSkills module

External seam:

```text
listSkills() -> SkillSummary[]
getSkill(id) -> SkillDocument
help(topic) -> HelpDocument
suggestNextSteps(context) -> HelpSuggestion[]
```

Responsibilities:

- Expose built-in tutorials as MCP resources.
- Offer short help answers for common topics such as sessions, projects, reports, and raw Tcl.
- Recommend a safe next tool call sequence for common user intents.
- Keep help content versioned with the MCP server.
- Allow later workspace-local custom skills without changing the core tool interface.

## First-version tool set

Tool names are written in snake case to match common MCP conventions.

### `vivado_start_session`

Starts a managed Vivado Tcl session and optionally opens the GUI.

Input:

- Optional `vivado_path`.
- Optional `workspace_dir`.
- Optional `open_gui` default true.
- Optional `project_path` to open after startup.

Output:

- `session_ref`
- Vivado version
- GUI state
- bridge state
- log resource URI

### `vivado_stop_session`

Stops a managed Vivado session.

Input:

- `session_ref`
- Optional `force` default false

Output:

- final state
- log resource URI

### `vivado_session_state`

Reads the current managed session state.

Input:

- `session_ref`

Output:

- `idle`, `busy`, `error`, or `stopped`
- current project path if known
- active run if known
- latest artifacts

### `vivado_list_sessions`

Lists active managed Vivado sessions.

Input:

- none

Output:

- session refs
- process state
- bridge state
- capability profile

### `vivado_help`

Returns concise help for a topic.

Input:

- Optional `topic`: `installation`, `gui_session`, `project_flow`, `reports`, `raw_tcl`, `capability_profiles`, or `troubleshooting`

Output:

- short explanation
- recommended next tools
- related skill resource URIs

### `vivado_list_skills`

Lists built-in tutorial skills.

Input:

- Optional `query`

Output:

- skill IDs
- titles
- summaries
- resource URIs

### `vivado_get_skill`

Returns one full skill/tutorial document.

Input:

- `skill_id`

Output:

- title
- markdown body
- resource URI

### `vivado_suggest_next_steps`

Suggests the next few MCP operations from current context.

Input:

- Optional `session_ref`
- Optional `project_ref`
- Optional `goal`
- Optional `last_error`

Output:

- recommended tool sequence
- why each step is useful
- relevant skill resource URIs

### `vivado_check_installation`

Read-only health check.

Input:

- Optional `vivado_path`.

Output:

- Found executable.
- Version string.
- Platform.
- Basic capability status.

### `vivado_create_project`

Creates a Project Mode project.

Input:

- Optional `session_ref`; if absent, use batch adapter.
- `project_name`
- `project_dir`
- `part` or `board_part`
- Optional `top`
- Optional `sources`
- Optional `constraints`
- Optional `force` default false

Output:

- `project_ref`
- `.xpr` path
- source/constraint counts
- generated Tcl resource URI
- log resource URI

### `vivado_add_sources`

Adds files to an existing project.

Input:

- Optional `session_ref`; if absent, use batch adapter.
- `project_ref`
- `sources`
- `constraints`
- Optional `top`

Output:

- updated file counts
- warnings
- log resource URI

### `vivado_run_synthesis`

Runs synthesis for a project.

Input:

- Optional `session_ref`; if absent, use batch adapter.
- `project_ref`
- Optional `run_name` default `synth_1`
- Optional `jobs`
- Optional `timeout_minutes`

Output:

- run status
- duration
- critical warning/error counts
- generated report resource URIs

### `vivado_run_implementation`

Runs implementation for a project.

Input:

- Optional `session_ref`; if absent, use batch adapter.
- `project_ref`
- Optional `run_name` default `impl_1`
- Optional `to_step`
- Optional `jobs`
- Optional `timeout_minutes`

Output:

- run status
- duration
- timing summary if available
- utilization summary if available
- report resource URIs

### `vivado_generate_bitstream`

Runs implementation through bitstream generation.

Input:

- Optional `session_ref`; if absent, use batch adapter.
- `project_ref`
- Optional `run_name` default `impl_1`
- Optional `jobs`
- Optional `timeout_minutes`

Output:

- bitstream path if generated
- run status
- timing summary
- log/report resource URIs

### `vivado_report`

Generates a report from the current project/run state.

Input:

- Optional `session_ref`; if absent, use batch adapter.
- `project_ref`
- `report_type`: `timing_summary`, `timing_paths`, `utilization`, `drc`, `power`, `clock_interaction`, `messages`
- Optional report-specific parameters such as `max_paths`.

Output:

- parsed summary where supported
- raw report resource URI

### `vivado_project_summary`

Generates and parses a read-only summary of the current project.

Input:

- `session_ref`
- Optional `timeout_seconds`

Output:

- current project and `.xpr` path if present
- part, board part, and top when available
- files with file types
- runs with status/progress
- IP and block design lists
- summary artifact URI

### `vivado_list_artifacts`

Lists resources generated by prior tool calls.

Input:

- Optional `project_ref`
- Optional `kind`: `log`, `journal`, `report`, `tcl`, `summary`

Output:

- artifact URI list with relative paths, sizes, and local paths.

### `vivado_read_artifact`

Reads a text artifact from a managed session.

Input:

- `session_ref`
- `artifact_id`
- Optional `max_chars`

Output:

- artifact text
- truncation flag
- artifact URI

### `vivado_run_tcl`

Runs raw Tcl inside a managed Vivado session. Enabled only in `trusted-local` or `unrestricted` capability profiles.

Input:

- `session_ref`
- `tcl`
- Optional `timeout_seconds`
- Optional `expect_destructive` default false

Output:

- Tcl result code
- Tcl result string
- command transcript resource URI
- log resource URI

This is the maximum-freedom escape hatch for expert users. It can do anything Vivado Tcl can do, including changing project state and invoking Tcl commands not modeled by workflow tools.

### `vivado_source_tcl`

Sources a Tcl file inside a managed Vivado session. Enabled only in `trusted-local` or `unrestricted` capability profiles.

Input:

- `session_ref`
- `script_path`
- Optional `tclargs`
- Optional `timeout_seconds`
- Optional `expect_destructive` default false

Output:

- Tcl result code
- Tcl result string
- command transcript resource URI
- log resource URI

## MCP resources

Use resources for context the model may need to inspect after a tool call.

Suggested URI shapes:

```text
vivado://projects/{project_id}/summary
vivado://projects/{project_id}/runs/{run_name}/log
vivado://projects/{project_id}/runs/{run_name}/journal
vivado://projects/{project_id}/reports/{report_id}
vivado://projects/{project_id}/scripts/{script_id}
vivado://artifacts/{artifact_id}
vivado://sessions/{session_ref}/artifacts/{artifact_id}
vivado://help/index
vivado://skills/index
vivado://skills/{skill_id}
```

Resource rules:

- Small summaries can be embedded in tool results.
- Large logs and reports should be linked as resources.
- Text resources should be truncated with an explicit marker if they exceed the configured limit.
- Binary artifacts such as `.bit` should be listed but not blindly embedded.
- Help and skill resources should stay small enough to return in full.
- Artifact IDs should encode paths relative to the session directory, not absolute paths.

## State model

v0 should support two execution adapters behind the same workflow interface.

Interactive GUI adapter:

- `vivado_start_session` launches Vivado Tcl mode.
- The session loads the MCP bridge.
- The session opens the GUI by default with `start_gui`.
- Workflow commands run inside that same process, so the user sees project/run state update in the GUI.
- The MCP server serializes commands and exposes busy/idle state.

Batch adapter:

- Every operation launches a fresh `vivado -mode batch` process.
- Project state lives in the Vivado project and in server-maintained metadata files.
- Useful for CI, tests, and fallback operation without GUI.

Attaching to a user-opened Vivado GUI is not a v0 guarantee. To control an already-open GUI, the user must source the MCP bridge script inside that GUI session. The server can then treat it as a bridge-backed session if the handshake succeeds.

## Capability profiles

The server should support three capability profiles.

### `safe`

The AI can only call workflow tools. No raw Tcl is exposed. This is appropriate for shared repos, demos, and clients that might pass untrusted model output into tool calls.

### `trusted-local`

The AI can call workflow tools plus `vivado_run_tcl` and `vivado_source_tcl`. This is the recommended profile for this project because the user wants maximum Vivado control on a personal machine while still preserving session tracking, logs, and result files.

Rules:

- Only managed sessions are eligible.
- Every raw Tcl command is written to an artifact before execution.
- The command result is captured as a result artifact.
- The server serializes commands.
- Destructive intent is explicit in the tool input.

### `unrestricted`

The AI can submit raw Tcl with minimal guardrails. This profile is equivalent to granting the AI local code execution through Vivado Tcl, because Tcl can mutate files and invoke external commands. Keep it available for personal experimentation, but do not make it the default for published configurations.

## Project Mode first

v0 should use Project Mode as the default because it gives the AI a stable project object, source management, run infrastructure, and generated reports. This is a better fit for iterative AI workflows.

Non-Project Mode should be a later adapter for users who already have fully scripted FPGA flows. It should not leak into the first public interface.

## Error taxonomy

All tools should return consistent errors:

- `vivado_not_found`
- `unsupported_vivado_version`
- `invalid_workspace_path`
- `invalid_project`
- `tcl_generation_failed`
- `vivado_process_failed`
- `vivado_timeout`
- `license_error`
- `source_file_missing`
- `top_module_not_found`
- `synthesis_failed`
- `implementation_failed`
- `timing_failed`
- `report_parse_failed`

For failed Vivado runs, include:

- Exit code.
- Last relevant log lines.
- Raw log resource URI.
- Generated Tcl resource URI.
- Suggested next inspection step.

## Security model

The server controls a powerful local EDA tool, so it must behave like a local build orchestrator with strict input validation.

Required policies:

- No arbitrary shell command execution.
- No raw Tcl execution unless explicitly enabled through a capability profile.
- All paths must resolve under configured workspace roots.
- Workflow project/source/constraint paths must stay under allowed roots.
- `trusted-local` raw Tcl source files must stay under allowed roots; `unrestricted` may bypass this.
- Generated Tcl must be derived from structured inputs.
- Destructive operations must require explicit opt-in.
- Hardware programming must be out of scope until a later design review.
- Tool outputs must not hide warnings/errors in long logs; summarize them and link to raw logs.
- Timeouts are mandatory for every Vivado process.

In `trusted-local` and `unrestricted` profiles, raw Tcl can bypass many workflow-level guarantees. The server should make that mode obvious in tool descriptions and logs rather than pretending it is safe.

## Implementation stack recommendation

Use Python for the first implementation.

Reasons:

- The official MCP Python SDK supports building servers, exposing tools/resources, and stdio/SSE/Streamable HTTP transports.
- Python has straightforward subprocess management and log parsing.
- Vivado users often already have Python available for tooling.
- The implementation can be packaged as a CLI that starts the MCP server over stdio.

TypeScript remains a good alternative, especially for richer schema tooling with Zod and Node-based distribution. The design should keep the MCP interface independent of implementation language.

## Suggested repository layout

```text
/
|-- src/
|   `-- vivado_mcp/
|       |-- server.py
|       |-- config.py
|       |-- policy.py
|       |-- vivado_locator.py
|       |-- vivado_runner.py
|       |-- tcl_builder.py
|       |-- project_index.py
|       |-- artifact_index.py
|       |-- report_parser.py
|       |-- help_skills.py
|       `-- diagnostics.py
|-- tests/
|   |-- unit/
|   |-- fixtures/
|   |   `-- fake_vivado/
|   `-- integration/
|-- docs/
|   |-- adr/
|   |-- design/
|   `-- skills/
|-- pyproject.toml
`-- README.md
```

## Testing strategy

Fast tests:

- Tcl quoting and generation tests.
- Path policy tests for Windows and POSIX paths.
- Fake Vivado executable tests for process handling, timeout, stdout/stderr, and failure codes.
- Parser fixture tests for timing/utilization/message reports.
- Help/skills tests that every listed skill ID has a readable resource.
- Artifact URI and artifact read tests.

Integration tests:

- Marked separately because they require an installed Vivado.
- Start with `vivado_check_installation`.
- Add minimal HDL project creation and synthesis when a compatible part is configured.

## Roadmap

### Phase 1: Server skeleton and safe runner

- Python package.
- MCP stdio server.
- `vivado_check_installation`.
- `vivado_help`, `vivado_list_skills`, and `vivado_get_skill`.
- `vivado_start_session`, `vivado_stop_session`, and `vivado_session_state`.
- `vivado_run_tcl` over the bridge for trusted-local mode.
- `VivadoSession` and `VivadoRunner` with fake Vivado tests.
- Artifact directory and resource reading.

### Phase 2: Project Mode build loop

- `vivado_create_project`.
- `vivado_add_sources`.
- `vivado_run_synthesis`.
- `vivado_run_implementation`.
- Generated Tcl captured as resources.
- Commands run through the managed GUI session when `session_ref` is provided.

### Phase 3: Reports and diagnosis

- `vivado_report`.
- Timing/utilization/message parsers.
- Failure summaries linked to logs.

### Phase 4: Non-Project Mode adapter

- Accept existing Tcl flow scripts.
- Generate reports/checkpoints around user scripts.
- Keep this as a separate internal adapter, not a separate public product.

### Phase 5: Advanced Vivado surfaces

- IP creation and configuration.
- Block design/IP Integrator flows.
- Hardware manager and programming, gated by explicit human confirmation.

## Open decisions

- Exact supported Vivado versions.
- Whether Windows is the primary target or Linux must be first-class from day one.
- Default workspace root policy for MCP clients that provide roots.
- Whether to expose Streamable HTTP in addition to stdio for remote usage.
- Whether raw Tcl should ever be shipped as a disabled-by-default tool.
- Exact bridge transport: file queue, localhost socket, or Tcl stdin protocol.
- Whether workspace-local custom skills should be loaded from `.vivado-mcp/skills/`.

## Local experiment results

On this machine, Vivado was found at:

```text
C:\Xilinx\Vivado\2023.1\bin\vivado.bat
```

Smoke tests performed:

- `vivado -mode batch -source experiments/vivado_probe.tcl` returned `version=2023.1`.
- `vivado -mode tcl -source experiments/start_gui_smoke.tcl` executed `start_gui`, continued Tcl execution, then stopped the GUI.
- `experiments/mcp_bridge.tcl` accepted an external raw Tcl command file and returned `version=2023.1`.
- The same bridge worked with GUI visible, proving that the MCP can operate a Vivado GUI session it started.

Observed wrinkle: GUI sessions on Vivado 2023.1 returned process exit code `1` during scripted shutdown even when command execution succeeded. The bridge result files are a better success signal than the final process code for GUI shutdown.
