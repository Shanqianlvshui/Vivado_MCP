# Skill: Official Docs Reference

Use this whenever a Vivado task depends on command syntax, flow rules, object properties, or report interpretation.

## Normal Flow

1. Call `vivado_official_reference_guide` with a topic such as `tcl`, `project`, `bd`, `ip`, `constraints`, `build`, `simulation`, `reports`, `hardware`, `dfx`, `methodology`, `io`, `installation`, `migration`, `libraries`, or `embedded`.
2. Read the recommended document summaries and choose the smallest set of official references needed for the task.
3. Call `vivado_get_official_reference` for the selected document IDs and check `local_path_candidates` under `C:\Database\FPGA\Vivado_docs`.
4. If a local PDF is missing, call `vivado_sync_official_docs` for packaged Vivado manuals or `vivado_download_xilinx_pdf` for one specific AMD/Xilinx document.
5. Call `vivado_search_official_docs` with a command name, option, report name, or error text before generating Tcl for unfamiliar behavior.
6. For exact command syntax, treat UG835 as the command authority.
7. For object properties, treat UG912 as the property authority.
8. For workflow concepts, use the topic-specific user guide before generating Tcl.
9. Prefer structured MCP workflow tools when they cover the task.
10. Use `vivado_run_tcl` or `vivado_source_tcl` only when the workflow tools do not expose the needed command.

## Topic Routing

- Tcl command syntax: UG835, then UG894.
- Tcl script structure and object queries: UG894, plus UG893 for Tcl Console and IDE context.
- Project and source management: UG892, UG895, UG893, UG888, UG835, UG912.
- Block design and IP Integrator: UG994, UG835, UG912, UG895, UG896.
- IP customization and output products: UG896, UG994, UG1118, UG835.
- Constraints: UG903, UG899, UG912, UG835.
- Synthesis and implementation: UG901, UG904, UG906, UG949, UG1292, UG835.
- Simulation: UG900, UG896, UG835.
- Reports and closure: UG906, UG907, UG949, UG1292, UG835.
- Hardware programming and debug: UG908, UG835, UG912.
- Dynamic Function eXchange: UG909, UG835, UG912.
- I/O and clock planning: UG899, UG903, UG912, UG835.
- Installation, licensing, and release notes: UG973.
- ISE migration: UG911, UG903, UG835, UG912.
- Device primitive libraries: UG953 for 7 Series/Zynq-7000 and UG974 for UltraScale/UltraScale+.
- Embedded methodology: UG1046, then the flow-specific Vivado guides.

## Notes For AI

- The MCP package includes official-document metadata and routing guidance, not the full AMD document text or every individual IP product guide.
- The default local documentation root is `C:\Database\FPGA\Vivado_docs`; deployments can override it with `VIVADO_MCP_DOCS_ROOT`.
- Local PDF search uses Poppler `pdftotext`; set `VIVADO_MCP_PDFTOTEXT` when it is not on `PATH`.
- PDF download uses AMD KHub APIs and verifies the `%PDF` signature instead of saving Fluid Topics HTML pages.
- If an installed Vivado version differs from the packaged guide version, prefer the installed Vivado command help for version-specific syntax checks.
- Do not assume every UG835 command has a structured MCP tool. Expert mode can run raw Tcl, but workflow tools should stay the first choice for repeatable operations.
- For destructive or hardware-affecting Tcl, call out the risk before execution and use `expect_destructive=true`.
