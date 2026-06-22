# Skill: Project Build Flow

Use this for ordinary Project Mode FPGA work: create/open a project, add files, run synthesis/implementation, generate reports, and summarize failures.

## Preconditions

- A managed session exists, or the operation can run through the batch adapter.
- The target part or board part is known.
- RTL/source files and constraints are under allowed workspace roots.

## Normal Flow

1. Call `vivado_check_installation` if installation status is unknown.
2. Call `vivado_start_session` with `open_gui=true` for interactive work.
3. Call `vivado_create_project` or open/register an existing project.
4. Call `vivado_project_summary` to inspect the active project, files, runs, IP, and block designs.
5. Call `vivado_add_sources` for RTL, IP, and XDC files.
6. Call `vivado_run_synthesis`.
7. If synthesis succeeds, call `vivado_run_implementation`.
8. Call `vivado_report` for `timing_summary`, `utilization`, `drc`, and `messages`.
9. Summarize WNS/TNS, utilization, critical warnings, and the first actionable errors.

## Notes For AI

- Prefer workflow tools over raw Tcl for repeatable project operations.
- Link raw logs and reports as resources instead of pasting entire logs.
- If a run fails, inspect errors and critical warnings before retrying.
- Do not assume a timing failure is fixed by rerunning implementation; inspect timing reports first.

## Common Problems

- `top_module_not_found`: check source sets and top property.
- `source_file_missing`: verify resolved paths and workspace roots.
- `license_error`: inspect the Vivado log before changing project files.
- `timing_failed`: generate timing summary and report critical paths.
