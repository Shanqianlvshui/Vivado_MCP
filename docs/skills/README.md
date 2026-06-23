# Vivado MCP Skills

These documents are seed content for the MCP server's built-in help system. The server should expose them as MCP resources and make them discoverable through help tools.

Suggested resource URIs:

- `vivado://skills/index`
- `vivado://skills/gui-session`
- `vivado://skills/project-build-flow`
- `vivado://skills/block-design-flow`
- `vivado://skills/fileset-constraint-flow`
- `vivado://skills/official-docs-reference`
- `vivado://skills/raw-tcl-expert`
- `vivado://official-docs/index`

The documents are written for AI clients. They should explain when to use a capability, required preconditions, safe call sequences, common failure modes, and useful follow-up inspections.

Official-document guidance is exposed as metadata, topic routing, local PDF search, and verified AMD KHub downloads, not copied AMD document bodies. Use `vivado_official_reference_guide`, `vivado_search_official_docs`, `vivado_tcl_command_help`, `vivado_review_tcl`, `vivado_capture_state`, `vivado_state_diff`, `vivado_source_audit`, `vivado_fileset_apply`, `vivado_constraint_set_apply`, `vivado_xdc_order_check`, `vivado_ip_catalog_search`, `vivado_create_ip`, `vivado_describe_ip`, `vivado_ip_upgrade_check`, `vivado_generate_ip_outputs`, `vivado_prepare_simulation`, `vivado_launch_simulation`, `vivado_analyze_xsim_logs`, `vivado_nonproject_read_sources`, `vivado_nonproject_synth_design`, `vivado_nonproject_route_design`, `vivado_analyze_reports`, `vivado_hw_discover`, `vivado_sync_official_docs`, `vivado_download_xilinx_pdf`, `vivado_list_official_references`, and `vivado_get_official_reference` to find or populate the relevant AMD source before generating Tcl or using expert mode.
