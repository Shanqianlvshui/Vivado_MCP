from __future__ import annotations

from pathlib import Path

from vivado_mcp.report_context import parse_report_context, unavailable_report_reasons


def test_report_context_distinguishes_top_and_ooc_runs(tmp_path: Path) -> None:
    path = tmp_path / "ctx.tsv"
    path.write_text(
        "\n".join(
            [
                "has_project\t1",
                "run\tsynth_1\tsynth_design ERROR\t0%",
                "run\tpll_synth_1\tsynth_design Complete!\t100%",
                "run\timpl_1\tNot started\t0%",
                "",
            ]
        ),
        encoding="utf-8",
    )

    context = parse_report_context(path)
    reasons = unavailable_report_reasons(context, ["timing_summary", "messages"])

    assert context["stage"] == "project_only"
    assert context["runs"][1]["scope"] == "ooc"
    assert context["recommended_actions"][0]["tool"] == "vivado_run_synthesis"
    assert reasons[0]["reason"] == "no_open_design"
    assert reasons[1]["reason"] == "unsupported_report_command"


def test_report_context_recommends_open_top_synthesis_run(tmp_path: Path) -> None:
    path = tmp_path / "ctx.tsv"
    path.write_text(
        "\n".join(
            [
                "has_project\t1",
                "run\tsynth_1\tsynth_design Complete!\t100%",
                "run\timpl_1\tNot started\t0%",
                "",
            ]
        ),
        encoding="utf-8",
    )

    context = parse_report_context(path)

    assert context["stage"] == "synthesis_complete_not_open"
    assert context["recommended_actions"][0]["tcl"] == "open_run synth_1"
