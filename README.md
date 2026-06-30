# Vivado CLI

[![CI](https://github.com/Shanqianlvshui/Vivado_CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/Shanqianlvshui/Vivado_CLI/actions/workflows/ci.yml)

Vivado CLI is a CLI-first automation layer for AMD Vivado. It keeps Vivado's
native Tcl as the execution layer, adds persistent session artifacts and
structured JSON output. MCP support has been removed; the product boundary is
now the `vivado-cli` command and the Vivado Tcl bridge.

The first design target is not GUI click automation. The preferred interactive
mode is a managed Vivado Tcl session that can open the GUI with `start_gui`,
load a small Tcl bridge, and let `vivado-cli` submit audited Tcl command files
into that same Vivado process. Batch mode remains useful for CI and fallback
automation.

Current design documents:

- [Vivado CLI Design](docs/design/vivado-cli-design.md)
- [ADR 0001: Control Vivado through Tcl batch mode](docs/adr/0001-control-vivado-through-tcl-batch-mode.md)
- [ADR 0002: Support managed GUI Tcl sessions](docs/adr/0002-support-managed-gui-tcl-sessions.md)
- [ADR 0003: Support trusted-local raw Tcl](docs/adr/0003-support-trusted-local-raw-tcl.md)
- [ADR 0004: Provide built-in help and skills](docs/adr/0004-provide-built-in-help-and-skills.md)
- [ADR 0005: Remove MCP adapter and standardize on CLI](docs/adr/0005-remove-mcp-adapter-and-standardize-on-cli.md)
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
- Create, inspect, audit, dry-run/mutate, validate, and generate generic IP Integrator block designs.
- Run synthesis, implementation, and bitstream generation.
- Run Non-project Mode flows with audit/dry-run support: read RTL/XDC, check prerequisites, execute synth/opt/place/route, write checkpoints, and collect reports.
- Generate timing, utilization, DRC, methodology, power, and message reports.
- Parse common report outputs into structured summaries and aggregate report diagnostics with issue IDs, root-cause hints, quality gates, next-action plans, and official-document queries.
- Perform explicit hardware access for hw_server targets/devices, debug core/probe discovery, VIO probe readback, generic ILA capture/CSV analysis, and VIO-backed SPI register readback; hardware programming remains out of scope for structured commands.
- Capture JSON state snapshots and diff project/fileset/constraint/IP/BD/run/report state before and after risky or long-running operations.
- Store logs and generated reports as session artifacts.
- Provide built-in help/skills so AI or human CLI callers can learn the intended Vivado workflows before acting.
- Package AMD official Vivado documentation metadata and topic guidance as the authority layer for help and expert Tcl planning.

## Capability profiles

- `safe`: workflow tools only; no raw Tcl.
- `trusted-local`: workflow tools plus raw Tcl/source-file execution inside the managed Vivado session.
- `unrestricted`: raw Tcl with minimal policy checks for personal local use.

The packaged bridge in [src/vivado_cli/assets/cli_bridge.tcl](src/vivado_cli/assets/cli_bridge.tcl) is the core control path: `vivado-cli` submits Tcl files to a live Vivado Tcl/GUI session and receives result files back.

## Built-in help

The CLI exposes tutorial and authority content through JSON commands:

- `vivado-cli help topic <topic>`
- `vivado-cli assist next --goal "<task>"`
- `vivado-cli skills list`
- `vivado-cli skills get <skill_id>`
- `vivado-cli tools list`
- `vivado-cli tools describe <command-or-tool-id>`
- `vivado-cli tcl help <command>`
- `vivado-cli tcl review --file <script.tcl>`

Seed skill docs live in [docs/skills](docs/skills).

The official reference layer stores document IDs, AMD URLs, scope summaries, topic routing, and local filename candidates. It does not copy the full AMD document text into this repository.

## Install For Local Use

From a fresh clone:

```powershell
git clone https://github.com/Shanqianlvshui/Vivado_CLI.git
cd Vivado_CLI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Basic smoke checks after installation:

```powershell
.\.venv\Scripts\vivado-cli.exe --help
.\.venv\Scripts\vivado-cli.exe tools list
.\.venv\Scripts\vivado-cli.exe tcl help create_clock
```

This machine has been tested with:

```text
C:\Xilinx\Vivado\2023.1\bin\vivado.bat
```

The stable local entry point for agents and external tools is:

```powershell
C:\Tools\vivado-cli\bin\vivado-cli.exe
```

New terminals can also read the full path from:

```powershell
$env:VIVADO_CLI_EXE
```

## Fresh Clone Verification

To verify the published repository from scratch, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-cold-clone.ps1
```

The default smoke path clones `https://github.com/Shanqianlvshui/Vivado_CLI.git`,
installs the editable package in a temporary virtual environment, runs CLI help
and tool-discovery checks, compiles `src` and `tests`, and runs the fast
fake-Vivado smoke tests. Add `-Full` to run the full unit suite in the cold
clone.

## CLI Usage

`vivado-cli` is the primary entry point. It writes persistent session records
under `.vivado_cli/sessions`, so separate CLI invocations can operate the same
live Vivado process.

```powershell
vivado-cli check-installation --vivado-path C:\Xilinx\Vivado\2023.1\bin\vivado.bat

vivado-cli --workspace C:\Workspace\Vivado_mcp session start `
  --vivado-path C:\Xilinx\Vivado\2023.1\bin\vivado.bat

vivado-cli --workspace C:\Workspace\Vivado_mcp session recovery `
  --session <session_ref>

vivado-cli --workspace C:\Workspace\Vivado_mcp session timeline `
  --session <session_ref> `
  --limit 20

vivado-cli --workspace C:\Workspace\Vivado_mcp session artifacts `
  --session <session_ref> `
  --kind report `
  --limit 10

vivado-cli --workspace C:\Workspace\Vivado_mcp session read-artifact `
  --session <session_ref> `
  reports\timing_summary.rpt `
  --max-chars 12000

vivado-cli --workspace C:\Workspace\Vivado_mcp session open-project `
  --session <session_ref> `
  C:\Workspace\Vivado\XCZU19EG\XCZU19EG_TEST\projects\qt7331_adda_2023.1\qt7331_adda_2023.1.xpr

vivado-cli --workspace C:\Workspace\Vivado_mcp bd summary `
  --session <session_ref> `
  --design jesd204b_bd `
  --validate

vivado-cli --workspace C:\Workspace\Vivado_mcp run status `
  --session <session_ref> `
  --run synth_1

vivado-cli --workspace C:\Workspace\Vivado_mcp run launch `
  --session <session_ref> `
  synth_1 `
  --jobs 8

vivado-cli --workspace C:\Workspace\Vivado_mcp run launch-local `
  --session <session_ref> `
  --jobs 8 `
  synth_1

vivado-cli --workspace C:\Workspace\Vivado_mcp run diagnose `
  --session <session_ref> `
  synth_1

vivado-cli --workspace C:\Workspace\Vivado_mcp run logs `
  --session <session_ref> `
  synth_1 `
  --tail 80

vivado-cli --workspace C:\Workspace\Vivado_mcp run reset `
  --session <session_ref> `
  synth_1 `
  --expect-destructive

vivado-cli --workspace C:\Workspace\Vivado_mcp hw list-debug-cores `
  --session <session_ref> `
  --expect-hardware-access

vivado-cli --workspace C:\Workspace\Vivado_mcp hw vio-read `
  --session <session_ref> `
  --vio hw_vio_0 `
  --probe chip_config/spi_read_status `
  --probe chip_config/spi_read_req `
  --expect-hardware-access

vivado-cli --workspace C:\Workspace\Vivado_mcp hw vio-write `
  --session <session_ref> `
  --vio hw_vio_0 `
  --set chip_config/spi_read_req=0 `
  --expect-hardware-access `
  --expect-vio-write

vivado-cli --workspace C:\Workspace\Vivado_mcp hw capture-ila `
  --session <session_ref> `
  --ila hw_ila_0 `
  --depth 1024 `
  --analysis adc14 `
  --sample-rate-hz 312500000 `
  --label bringup_capture `
  --expect-hardware-access

vivado-cli --workspace C:\Workspace\Vivado_mcp hw spi-read `
  --session <session_ref> `
  --vio hw_vio_0 `
  --status-probe spi/status `
  --req-probe spi/req `
  --target-probe spi/target `
  --addr-probe spi/addr `
  --reg 2:0x0281 `
  --reg 2:0x0300 `
  --expect-hardware-access

vivado-cli --workspace C:\Workspace\Vivado_mcp tcl review `
  --file .\scripts\change_bd.tcl

vivado-cli --workspace C:\Workspace\Vivado_mcp session run-tcl `
  --session <session_ref> `
  --file .\scripts\change_bd.tcl `
  --expect-destructive
```

## Environment

`VIVADO_CLI_WORKSPACE` is the default workspace for managed sessions.
`VIVADO_CLI_ALLOWED_ROOTS` is a semicolon-separated list on Windows; workflow
paths such as projects, sources, constraints, and Tcl files in `trusted-local`
mode must stay under one of these roots. `VIVADO_CLI_DOCS_ROOT` points to the
local AMD Vivado documentation library used by the official-reference index; it
defaults to `C:\Database\domains\fpga\xilinx\vivado\docs\raw`. Set
`VIVADO_CLI_PDFTOTEXT` if `pdftotext` is not on `PATH`.

## AI Operating Flow

CLI callers should use this order:

1. Start with `vivado-cli assist next --goal "<task>"` and include `--session`, `--last-error`, or a Tcl draft with `--tcl` / `--file` when available.
2. Discover the available surface with `vivado-cli tools list`, `vivado-cli tools describe <command>`, `vivado-cli skills list`, and `vivado-cli skills get <skill_id>`.
3. Use `vivado-cli tcl help <command>` before unfamiliar Vivado Tcl; it combines official-document search, CLI coverage guidance, and optional installed Vivado help when a session is attached.
4. Use structured commands first: `project summary`, `fileset ...`, `constraint ...`, `bd ...`, `run ...`, `report`, and `hw ...`.
5. Use `vivado-cli tcl review` before raw expert Tcl, then `vivado-cli session run-tcl` or `vivado-cli session source-tcl` only when no structured command covers the task.
6. Pass explicit acknowledgements for risky actions, such as `--expect-destructive`, `--expect-hardware-access`, and `--expect-vio-write`.
7. Read `state_tracking` and `state_diff` from mutating fileset/constraint commands before launching long runs or handing the session to another agent.
8. For a resumed or stale thread, run `vivado-cli session recovery`, then inspect `session timeline`, `session artifacts`, or `session read-artifact` before changing Vivado state.
9. After mutating project state, refresh with `vivado-cli project summary`, `vivado-cli fileset describe`, `vivado-cli constraint check-order`, `vivado-cli bd summary`, or `vivado-cli run diagnose` as appropriate.

## First Manual Test

Use this sequence:

1. `vivado-cli help topic gui-session`
2. `vivado-cli tools list`
3. `vivado-cli check-installation --vivado-path C:\Xilinx\Vivado\2023.1\bin\vivado.bat`
4. `vivado-cli session start --vivado-path C:\Xilinx\Vivado\2023.1\bin\vivado.bat`
5. `vivado-cli session state --session <session_ref>`
6. `vivado-cli tcl help create_project`
7. `vivado-cli tcl review --tcl "return \"version=[version -short]\""`
8. `vivado-cli session run-tcl --session <session_ref> --tcl "return \"version=[version -short]\""`
9. `vivado-cli project summary --session <session_ref>` after opening or creating a project
10. `vivado-cli session stop --session <session_ref>`

## Implemented CLI Commands

Use `vivado-cli tools list` as the source of truth. The current top-level
groups are:

- `check-installation`
- `session start|adopt|list|state|artifacts|timeline|read-artifact|recovery|open-project|run-tcl|source-tcl|stop`
- `tcl help|review`
- `skills list|get`
- `help topic`
- `assist next`
- `tools list|describe`
- `project summary`
- `fileset list|describe|create|add-files|remove-files|set-file-properties|set-top|apply`
- `constraint diagnostics|check-order|apply`
- `bd summary|validate`
- `run status|launch|launch-local|logs|diagnose|reset`
- `report`
- `hw list-debug-cores|vio-read|vio-write|capture-ila|spi-read`

## Development Checks

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest tests\unit -q
```

The test suite includes a fake Vivado process and CLI lifecycle tests. GitHub
Actions runs the same package install, compile check, CLI smoke, and full unit
suite on `windows-latest`.

## Artifacts

Command files, result files, logs, and reports are stored under the managed session directory and exposed through artifact URIs:

```text
vivado://sessions/{session_ref}/artifacts/{artifact_id}
```

Use `vivado-cli session artifacts --session <session_ref>` to list artifact IDs
and `vivado-cli session read-artifact --session <session_ref> <artifact_id>` to
read a bounded text slice. `vivado-cli session recovery --session <session_ref>`
returns the latest analyses, snapshots, quality gates, timeline preview, and
next CLI actions for AI handoff and long-running task recovery.

Commands that generate reports, summaries, captures, snapshots, or diffs return
filesystem paths and `vivado://...` artifact URIs in their JSON output.
Structured fileset and constraint mutations attach `state_tracking` and
`state_diff` by default; pass `--no-state-diff` only for intentional bulk edits
where speed matters more than immediate audit artifacts.

## Official Reference Resources

Use `vivado-cli tcl help <command>` for Tcl command routing. It searches the
local AMD/Xilinx documentation library when available, reports the official-doc
topic, shows any structured CLI coverage for that command family, and can also
query installed Vivado help when `--session <session_ref>` is supplied.

The CLI uses the local PDF library under
`C:\Database\domains\fpga\xilinx\vivado\docs\raw` by default. Set
`VIVADO_CLI_DOCS_ROOT` to another documentation root and `VIVADO_CLI_PDFTOTEXT`
if `pdftotext` is not on `PATH`.

## Explicitly out of scope for the first version

- GUI click automation.
- Attaching to an arbitrary already-open Vivado process that did not load the CLI bridge.
- Hardware programming, configuration-memory writes, boot operations, and debug/probe mutation. Read-only hardware discovery is supported with explicit confirmation.
- Advanced IP Integrator automation beyond the generic BD action model.
