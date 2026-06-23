from __future__ import annotations

from pathlib import Path

from vivado_mcp.ip_summary import analyze_ip_upgrade, parse_ip_catalog, parse_ip_detail, parse_ip_list


def test_parse_ip_catalog_returns_search_rows(tmp_path: Path) -> None:
    path = tmp_path / "catalog.tsv"
    path.write_text(
        "catalog_ip\txilinx.com:ip:axi_gpio:2.0\taxi_gpio\tAXI GPIO\t2.0\txilinx.com\tip\t/AXI Peripheral\t1\n",
        encoding="utf-8",
    )

    parsed = parse_ip_catalog(path)

    assert parsed["count"] == 1
    assert parsed["ips"][0]["name"] == "axi_gpio"
    assert parsed["ips"][0]["supported"] is True
    assert parsed["ips"][0]["recommended_docs"][0]["doc_id"] == "UG896"


def test_parse_ip_list_and_detail(tmp_path: Path) -> None:
    list_path = tmp_path / "ips.tsv"
    list_path.write_text(
        "\n".join(
            [
                "has_project\t1",
                "current_project\tfake_project",
                "ip\taxi_gpio_0\txilinx.com:ip:axi_gpio:2.0\tC:/fake/axi_gpio_0.xci\t0\t1\t1\tGenerated",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    detail_path = tmp_path / "ip.tsv"
    detail_path.write_text(
        "\n".join(
            [
                "ip\taxi_gpio_0\txilinx.com:ip:axi_gpio:2.0\tC:/fake/axi_gpio_0.xci\t0\t1\t1\tGenerated",
                "property\tCONFIG.C_GPIO_WIDTH\t32",
                "target\tinstantiation_template",
                "target\tsynthesis",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    listed = parse_ip_list(list_path)
    detail = parse_ip_detail(detail_path)

    assert listed["has_project"] is True
    assert listed["ips"][0]["upgrade_available"] is True
    assert listed["ips"][0]["status"]["needs_upgrade"] is True
    assert listed["upgrade_check"]["upgrade_needed_count"] == 1
    assert detail["properties"]["CONFIG.C_GPIO_WIDTH"] == "32"
    assert detail["targets"] == ["instantiation_template", "synthesis"]
    assert detail["status"]["needs_upgrade"] is True


def test_analyze_ip_upgrade_flags_locked_and_stale_ip() -> None:
    summary = {
        "ips": [
            {
                "name": "axi_gpio_0",
                "vlnv": "xilinx.com:ip:axi_gpio:2.0",
                "locked": True,
                "upgrade_available": True,
                "generated": False,
                "synthesis_status": "",
            }
        ]
    }

    analysis = analyze_ip_upgrade(summary)

    assert analysis["ok"] is False
    assert analysis["upgrade_needed_count"] == 1
    issue_ids = {issue["issue_id"] for issue in analysis["issues"]}
    assert {"ip.locked", "ip.upgrade_available", "ip.outputs_not_generated"} <= issue_ids
    assert analysis["recommendations"][0]["tool"] == "vivado_describe_ip"
