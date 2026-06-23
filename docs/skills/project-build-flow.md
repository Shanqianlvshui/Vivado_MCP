# Skill: Project Build Flow

Use this for ordinary Project Mode FPGA work: create/open a project, add files, run synthesis/implementation, generate reports, and summarize failures.

## Preconditions

- A managed session exists, or the operation can run through the batch adapter.
- The target part or board part is known.
- RTL/source files and constraints are under allowed workspace roots.

## Normal Flow

1. Call `vivado_check_installation` if installation status unknown.
2. Call `vivado_start_session` with `open_gui=true` for interactive work.
3. Call `vivado_create_project` or open/register an existing project.
4. Call `vivado_project_summary` to inspect the active project, files, runs, IP, and block designs.
5. For complex projects, call `vivado_source_audit` first, then use `vivado_list_filesets` and `vivado_describe_fileset` to understand the active filesets, top modules, and included files before adding anything new.
6. For non-trivial changes, call `vivado_capture_state` first or pass `capture_diff=true` to the mutating tool.
7. Call `vivado_add_sources` for RTL and XDC files. Use the `sources_fileset`, `include_dirs`, `defines`, `library`, `file_type`, `used_in`, and `processing_order` parameters when the project is not the default `sources_1`.
8. For project IP, call `vivado_ip_catalog_search`, then `vivado_create_ip(dry_run=true)` for the plan before creation on non-trivial IP, then `vivado_describe_ip`, `vivado_ip_upgrade_check`, and `vivado_generate_ip_outputs`. Use `vivado_upgrade_ip(expect_upgrade=true)` only when the `.xci` mutation is intended.
9. For testbench work, call `vivado_prepare_simulation`, `vivado_launch_simulation`, and `vivado_analyze_xsim_logs` before changing RTL or IP based on a simulator failure.
10. For Non-project Mode, call `vivado_nonproject_read_sources`, then `vivado_nonproject_synth_design`, `vivado_nonproject_opt_design`, `vivado_nonproject_place_design`, and `vivado_nonproject_route_design`.
11. For read-only hardware discovery, call `vivado_hw_discover(expect_hardware_access=true)`; do not program devices through structured tools.
12. Call `vivado_set_top` (with `top=None` to read, or pass a value to set) to confirm or change the top module.
13. Call `vivado_set_file_properties` for files that need explicit LIBRARY / PROCESSING_ORDER / USED_IN overrides.
14. Call `vivado_xdc_order_check` and `vivado_constraint_diagnostics` to audit XDC fileset ordering, USED_IN scopes, and UG903/UG949 methodology markers before synthesis on non-trivial projects.
15. Call `vivado_run_synthesis`.
16. If synthesis succeeds, call `vivado_run_implementation`.
17. Call `vivado_analyze_reports` for `timing_summary`, `utilization`, `drc`, `power`, and `methodology`; use the returned issue IDs, evidence, and `official_doc_queries` to choose the next action.
18. Use targeted `vivado_report` calls only after the aggregate analysis points at the next failure area.
19. Summarize WNS/TNS, utilization pressure, DRC/methodology rule IDs, power totals, and the first actionable errors.

## Notes For AI

- Prefer workflow tools over raw Tcl for repeatable project operations.
- Use `capture_diff=true` on source/fileset/top/property/IP/simulation/run operations when you need a before/after audit trail; read `state_diff.summary`, `changes`, and `recommendations` first.
- Link raw logs and reports as resources instead of pasting entire logs.
- If a run fails, inspect `vivado_analyze_reports` issues before retrying.
- Do not assume a timing failure is fixed by rerunning implementation; inspect timing reports first.

## Common Problems

- `top_module_not_found`: check source sets and top property.
- `source_file_missing`: verify resolved paths and workspace roots.
- `license_error`: inspect the Vivado log before changing project files.
- `ip_locked_or_stale`: call `vivado_ip_upgrade_check` and `vivado_describe_ip`, then upgrade only through `vivado_upgrade_ip(expect_upgrade=true)`.
- `simulation_compile_or_elaboration_failed`: call `vivado_analyze_xsim_logs`, then inspect the simulation fileset with `vivado_describe_fileset`.
- `nonproject_step_failed`: inspect the command artifact and requested reports from the failed Non-project step.
- `hardware_discovery_failed`: inspect the warning rows from `vivado_hw_discover`, then verify hw_server URL, cable target, and UG908 Hardware Manager guidance.
- `timing_failed`: call `vivado_analyze_reports`, then generate timing paths for the worst setup or hold failure.
- `timing_unconstrained`: fix XDC clocks/order/scope before interpreting WNS/TNS.
- `drc_io_constraint_missing`: resolve `drc.io_standard_missing` or `drc.io_pin_unconstrained` before bitstream generation.
- `power_thermal_risk`: inspect power activity assumptions, thermal margin, and UG907 guidance before closure decisions.
