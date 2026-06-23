from pathlib import Path

import pytest

from vivado_mcp.tcl import (
    bd_apply_tcl,
    bd_generate_tcl,
    bd_open_or_create_tcl,
    constraint_set_apply_tcl,
    create_project_tcl,
    fileset_apply_tcl,
    hardware_discover_tcl,
    ip_catalog_search_tcl,
    ip_create_tcl,
    ip_describe_tcl,
    ip_generate_outputs_tcl,
    ip_list_tcl,
    ip_upgrade_tcl,
    nonproject_read_sources_tcl,
    nonproject_run_step_tcl,
    quote_tcl,
    report_tcl,
    simulation_launch_tcl,
    simulation_prepare_tcl,
)


def test_quote_tcl_normalizes_windows_paths() -> None:
    assert quote_tcl(Path(r"C:\Work\a b\top.v")) == "{C:/Work/a b/top.v}"


def test_create_project_tcl_supports_part_and_force() -> None:
    script = create_project_tcl(
        project_name="demo",
        project_dir=Path("build/demo"),
        part="xc7a35tcpg236-1",
        board_part=None,
        force=True,
    )
    assert "create_project {demo}" in script
    assert "-part {xc7a35tcpg236-1}" in script
    assert "-force" in script


def test_report_tcl_rejects_unknown_report_type() -> None:
    with pytest.raises(ValueError):
        report_tcl("unknown", Path("out.rpt"))


def test_bd_open_or_create_tcl_is_generic() -> None:
    script = bd_open_or_create_tcl(design_name="design_1")

    assert "create_bd_design $mcp_bd_name" in script
    assert "open_bd_design" in script
    assert "project_specific" not in script
    assert "board_preset" not in script


def test_bd_apply_tcl_builds_generic_actions() -> None:
    script = bd_apply_tcl(
        design_name="design_1",
        actions=[
            {"action": "create_cell", "name": "axi_gpio_0", "vlnv": "xilinx.com:ip:axi_gpio:*"},
            {"action": "create_port", "name": "gpio_tri_o", "direction": "O", "from": 31, "to": 0},
            {
                "action": "set_property",
                "object_type": "cell",
                "object": "axi_gpio_0",
                "properties": {"CONFIG.C_GPIO_WIDTH": 32},
            },
            {"action": "connect_net", "endpoints": ["axi_gpio_0/gpio_io_o", "gpio_tri_o"]},
        ],
    )

    assert "create_bd_cell -type ip -vlnv {xilinx.com:ip:axi_gpio:*} {axi_gpio_0}" in script
    assert "create_bd_port -dir {O} -from 31 -to 0 {gpio_tri_o}" in script
    assert "set_property -dict [list {CONFIG.C_GPIO_WIDTH} {32}]" in script
    assert "connect_bd_net [mcp_bd_endpoint {axi_gpio_0/gpio_io_o}] [mcp_bd_endpoint {gpio_tri_o}]" in script
    assert "validate_bd_design" in script
    assert "save_bd_design" in script


def test_bd_generate_tcl_can_skip_wrapper() -> None:
    script = bd_generate_tcl(design_name="design_1", target="synthesis", make_wrapper=False)

    assert "generate_target {synthesis}" in script
    assert "make_wrapper" not in script


def test_fileset_apply_tcl_sets_common_fileset_properties() -> None:
    script = fileset_apply_tcl(
        fileset="sources_1",
        include_dirs=[Path("C:/demo/include")],
        defines=["DEBUG=1", "BOARD=arty"],
        top="top",
        properties={"LIBRARY": "xil_defaultlib"},
        update_compile_order=True,
    )

    assert "set_property INCLUDE_DIRS [list {C:/demo/include}] [get_filesets {sources_1}]" in script
    assert "error [format {Fileset not found: %s} {sources_1}]" in script
    assert "{DEFINE.DEBUG=1} {} {DEFINE.BOARD=arty} {}" in script
    assert "set_property top {top} [get_filesets {sources_1}]" in script
    assert "update_compile_order -fileset {sources_1}" in script


def test_constraint_set_apply_tcl_creates_adds_and_reorders_xdc() -> None:
    script = constraint_set_apply_tcl(
        fileset="constrs_extra",
        create_if_missing=True,
        add=[Path("C:/demo/clocks.xdc"), Path("C:/demo/pins.xdc")],
        remove=[],
        used_in=["synthesis", "implementation"],
        reorder=[Path("C:/demo/pins.xdc"), Path("C:/demo/clocks.xdc")],
        active=True,
    )

    assert "create_fileset -type {constrs} {constrs_extra}" in script
    assert "add_files -fileset {constrs_extra} [list {C:/demo/clocks.xdc} {C:/demo/pins.xdc}]" in script
    assert "error [format {Constraint fileset not found: %s} {constrs_extra}]" not in script
    assert "set_property IS_ENABLED_SYNTHESIS 1 [get_filesets {constrs_extra}]" in script
    assert "reorder_files -fileset {constrs_extra} -before" in script
    assert "current_fileset -constrset [get_filesets {constrs_extra}]" in script


def test_ip_tcl_helpers_cover_catalog_create_describe_and_outputs() -> None:
    catalog = ip_catalog_search_tcl(Path("catalog.tsv"), query="axi", vendor="xilinx.com", name="axi_gpio", limit=5)
    assert "get_ipdefs -all" in catalog
    assert "set mcp_filter_query {axi}" in catalog
    assert 'string match -nocase "*$mcp_filter_query*"' in catalog
    assert "mcp_put $f catalog_ip" in catalog

    created = ip_create_tcl(
        vlnv="xilinx.com:ip:axi_gpio:2.0",
        module_name="axi_gpio_0",
        output_dir=Path("C:/demo/ip"),
        properties={"CONFIG.C_GPIO_WIDTH": 32},
    )
    assert "create_ip -vlnv {xilinx.com:ip:axi_gpio:2.0} -module_name {axi_gpio_0} -dir {C:/demo/ip}" in created
    assert "set_property -dict [list {CONFIG.C_GPIO_WIDTH} {32}] [get_ips {axi_gpio_0}]" in created

    listed = ip_list_tcl(Path("ips.tsv"))
    assert "foreach ip [get_ips -quiet]" in listed

    described = ip_describe_tcl(Path("ip.tsv"), name="axi_gpio_0")
    assert "get_ips -quiet {axi_gpio_0}" in described
    assert "GENERATE_SYNTH_CHECKPOINT" in described

    upgraded = ip_upgrade_tcl(name="axi_gpio_0")
    assert "upgrade_ip [get_ips {axi_gpio_0}]" in upgraded

    generated = ip_generate_outputs_tcl(name="axi_gpio_0", targets=["all", "synthesis"])
    assert "generate_target {all} [get_ips {axi_gpio_0}]" in generated
    assert "generate_target {synthesis} [get_ips {axi_gpio_0}]" in generated


def test_simulation_tcl_helpers_prepare_and_launch() -> None:
    prepared = simulation_prepare_tcl(
        fileset="sim_1",
        testbench_files=[Path("C:/demo/tb_top.sv")],
        top="tb_top",
        include_dirs=[Path("C:/demo/tb/include")],
        defines=["SIM=1"],
        library="xil_defaultlib",
    )

    assert "create_fileset -type {simulation} {sim_1}" in prepared
    assert "add_files -fileset {sim_1} [list {C:/demo/tb_top.sv}]" in prepared
    assert "{IS_ENABLED_SIMULATION} {1} {IS_ENABLED_SYNTHESIS} {0}" in prepared
    assert "set_property TOP {tb_top} [get_filesets {sim_1}]" in prepared
    assert "update_compile_order -fileset {sim_1}" in prepared

    launched = simulation_launch_tcl(
        Path("sim.tsv"),
        fileset="sim_1",
        mode="post-synthesis",
        sim_type="functional",
        scripts_only=True,
    )
    assert "launch_simulation -simset {sim_1} -mode {post-synthesis} -type {functional} -scripts_only" in launched
    assert "run all" not in launched
    assert "mcp_put $f simulation {sim_1} {post-synthesis} {functional} 1" in launched

    with pytest.raises(ValueError):
        simulation_launch_tcl(Path("sim.tsv"), fileset="sim_1", mode="behavioral", sim_type="timing")
    with pytest.raises(ValueError):
        simulation_launch_tcl(Path("sim.tsv"), fileset="sim_1", mode="post-implementation")


def test_nonproject_tcl_helpers_read_sources_and_run_steps() -> None:
    read_script = nonproject_read_sources_tcl(
        Path("np.tsv"),
        verilog=[Path("C:/demo/top.v")],
        systemverilog=[Path("C:/demo/tb.sv")],
        vhdl=[Path("C:/demo/pkg.vhd")],
        xdc=[Path("C:/demo/timing.xdc")],
        include_dirs=[Path("C:/demo/include")],
        defines=["SIM=0"],
        library="xil_defaultlib",
    )

    assert "read_verilog -include_dirs [list {C:/demo/include}] -define [list {SIM=0}] -library {xil_defaultlib} [list {C:/demo/top.v}]" in read_script
    assert "read_verilog -sv -include_dirs" in read_script
    assert "read_vhdl -library {xil_defaultlib} [list {C:/demo/pkg.vhd}]" in read_script
    assert "read_xdc [list {C:/demo/timing.xdc}]" in read_script
    assert "mcp_put $f file verilog" in read_script

    step_script = nonproject_run_step_tcl(
        Path("step.tsv"),
        step="synth_design",
        part="xc7a35tcpg236-1",
        top="top",
        checkpoint_path=Path("C:/demo/synth.dcp"),
        reports={"utilization": Path("C:/demo/util.rpt"), "drc": Path("C:/demo/drc.rpt")},
        extra_args={"flatten_hierarchy": "rebuilt", "mode": "out_of_context"},
    )

    assert "synth_design -top {top} -part {xc7a35tcpg236-1} -flatten_hierarchy {rebuilt} -mode {out_of_context}" in step_script
    assert "write_checkpoint -force {C:/demo/synth.dcp}" in step_script
    assert "report_utilization -file {C:/demo/util.rpt} -force" in step_script
    assert "report_drc -file {C:/demo/drc.rpt} -force" in step_script

    with pytest.raises(ValueError):
        nonproject_run_step_tcl(Path("bad.tsv"), step="synth_design", part="xc7a35tcpg236-1")
    with pytest.raises(ValueError):
        nonproject_run_step_tcl(Path("bad.tsv"), step="write_bitstream")
    with pytest.raises(ValueError):
        nonproject_run_step_tcl(
            Path("bad.tsv"),
            step="opt_design",
            extra_args={"bad;exec": "calc"},
        )


def test_hardware_discover_tcl_is_read_only() -> None:
    script = hardware_discover_tcl(
        Path("hardware.tsv"),
        hw_server_url="localhost:3121",
        target="*Digilent*",
        open_target=True,
        refresh=True,
    )

    assert "open_hw_manager" in script
    assert "connect_hw_server -url {localhost:3121}" in script
    assert "open_hw_target $hw_target" in script
    assert "refresh_hw_device $device" in script
    assert "get_hw_targets_failed" in script
    assert "get_hw_devices_failed" in script
    assert "get_hw_devices -quiet" in script
    assert "program_hw_devices" not in script
    assert "write_cfgmem" not in script
    assert "boot_hw_device" not in script
