# Skill: Project Build Flow

Use this for ordinary Project Mode FPGA work: create/open a project, add files, run synthesis/implementation, generate reports, and summarize failures.

## Normal Flow

1. Call `vivado_check_installation`.
2. Call `vivado_start_session` with `open_gui=true`.
3. Call `vivado_create_project` or `vivado_open_project`.
4. Call `vivado_project_summary` to inspect project files, runs, IP, and block designs.
5. Call `vivado_add_sources`.
6. Call `vivado_run_synthesis`.
7. If synthesis succeeds, call `vivado_run_implementation`.
8. Call `vivado_report` for `timing_summary`, `utilization`, `drc`, and `messages`.

## Notes For AI

- Prefer workflow tools over raw Tcl for repeatable project operations.
- Link raw logs and reports as resources instead of pasting entire logs.
- If a run fails, inspect errors and critical warnings before retrying.
