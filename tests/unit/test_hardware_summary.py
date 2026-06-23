from __future__ import annotations

from pathlib import Path

from vivado_mcp.hardware_summary import parse_hardware_summary


def test_parse_hardware_summary_extracts_targets_devices_and_properties(tmp_path: Path) -> None:
    tsv = tmp_path / "hardware.tsv"
    tsv.write_text(
        "\n".join(
            [
                "server\tlocalhost:3121\tconnected",
                "target\txilinx_tcf/Digilent/123\topen",
                "device\txc7a35t_0\txc7a35tcpg236-1\t0123456789abcdef\t1\tReady",
                "property\txc7a35t_0\tPROGRAM.IS_PROGRAMMED\t1",
                "warning\tno_hw_targets",
                "",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_hardware_summary(tsv)

    assert parsed["server_count"] == 1
    assert parsed["target_count"] == 1
    assert parsed["device_count"] == 1
    assert parsed["devices"][0]["programmed"] is True
    assert parsed["properties"][0]["name"] == "PROGRAM.IS_PROGRAMMED"
    assert parsed["warnings"] == ["no_hw_targets"]
