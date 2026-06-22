from pathlib import Path

from vivado_mcp.project_summary import parse_project_summary


def test_parse_project_summary() -> None:
    path = Path("summary.tsv")
    text = "\n".join(
        [
            "has_project\t1",
            "current_project\tdemo",
            "part\txc7a35tcpg236-1",
            "file\tC:/demo/top.v\tVerilog",
            "run\tsynth_1\tComplete\t100%",
            "ip\tmy_ip",
            "block_design\tC:/demo/design_1.bd",
        ]
    )
    # Use a temp file in the current test cwd to keep the parser API simple.
    path.write_text(text, encoding="utf-8")
    try:
        summary = parse_project_summary(path)
    finally:
        path.unlink()

    assert summary["has_project"] is True
    assert summary["current_project"] == "demo"
    assert summary["files"] == [{"path": "C:/demo/top.v", "file_type": "Verilog"}]
    assert summary["runs"][0]["name"] == "synth_1"
    assert summary["ips"] == ["my_ip"]
    assert summary["block_designs"] == ["C:/demo/design_1.bd"]

